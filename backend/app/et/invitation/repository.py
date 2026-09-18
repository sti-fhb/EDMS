"""Email 邀請資料存取（US8 / #273、#362）。

`ET_INVITATION` 已隨 #362 移除，本檔只剩課程查詢與 `ET_ENROLLMENT` 的 upsert。
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import (
    COMPLETION_NOT_STARTED,
    SOURCE_EMAIL_INVITE,
)
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment


class EtInvitationRepository:
    """課程查詢與受邀者加入課程之 upsert。

    原本還有一支 `get_enrollment()`，唯一呼叫端是已刪的 `_already_consumed`（accept 流程）。
    它**既不濾 `DELETED` 也不濾 `IS_REMOVED`**（當時刻意如此，因為呼叫端自己判斷），
    留著會變成下一個人「看起來可以直接用」的陷阱，故隨 #362 一併刪除。
    """

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def upsert_enrollment(
        self, db: AsyncSession, *, user_id: str, course_id: int, operator: OperatorInfo
    ) -> None:
        """受邀者加入課程——**已存在的列改為在籍**（`ON CONFLICT DO UPDATE`）。

        🔴 **必須 upsert，不能 INSERT**：`UQ_ET_ENROLLMENT_USER_COURSE` 為全表唯一
        （刻意，見 `progress/models.py`），被移除的學員那一列還在，`INSERT` 會撞鍵並讓
        教師看到一個指向他看不見之列的資料庫錯誤。

        🔴 **與 `tag_invite.bulk_enroll_returning` 的 `DO NOTHING` 刻意不共用實作**：
        兩者是 #247 SA Q1 裁示 C 的兩側——標籤帶入**不得**把被移除者帶回來，教師的明確
        重新邀請**可以**。看起來只差一個 `on_conflict_*` 參數，抽成共用 helper 之後任何
        人改一個預設值就會靜默打開那條被否決的路徑，而兩邊各自的測試都還會過。

        ⚠️ **`DO UPDATE` 明列欄位，禁用 `EXCLUDED` 全量覆寫**：後者會連
        `COMPLETION_STATUS` / `COMPLETED_AT` / `LAST_ACTIVITY_AT` 一起蓋掉，等於把回鍋
        學員的學習狀態重置成新加入；本表日後新增的欄位也會被一併清空
        （`ET_ENROLLMENT` 之進度相關欄位由其他 issue 持續擴充）。

        ## 🔴 `DO UPDATE` 帶 `WHERE IS_REMOVED`——只有「把被移除者帶回」才寫

        #362 之前這條路徑一輪只跑一次、且由**受邀者本人**對**自己那一列**執行（accept），
        撞鍵幾乎只可能是「他被移除過」。改成邀請即加入之後，**教師一次可對 50 列執行**，
        而重貼整份名冊「補寄一次」是最可能的操作（`EmailInviteResult` 已載明已在課程者
        亦計入）。

        少了這個 `WHERE`，那 50 位裡原本由標籤帶入、兩個月前就加入的人，`JOINED_AT` 會被
        改成今天、`JOIN_SOURCE` 被改寫成 `EMAIL_INVITE`——ET03 清單以 `JOINED_AT` 排序、
        「加入日」欄位、以及任何以加入時點判讀的報表全部失真，**而且沒有任何訊號**：
        回應照樣說「已加入 50 位」，稽核也照樣記 50。

        條件寫在 `WHERE` 裡而非先查後改，理由同 `approval/repository` 的檔頭
        （PostgreSQL READ COMMITTED 的 EvalPlanQual 會重新求值 `WHERE`）。已在籍者的
        `DO UPDATE` 條件為假 ⇒ 該列不動，這正是要的語意。
        """
        now = utcnow()
        stmt = (
            pg_insert(EtEnrollment)
            .values(
                {
                    "USER_ID": user_id,
                    "COURSE_ID": course_id,
                    "JOIN_SOURCE": SOURCE_EMAIL_INVITE,
                    "JOINED_AT": now,
                    "COMPLETION_STATUS": COMPLETION_NOT_STARTED,
                    "IS_REMOVED": False,
                    "CREATED_USER": operator.user_id,
                    "CREATED_DATE": now,
                    "DELETED": 0,
                }
            )
            .on_conflict_do_update(
                index_elements=["USER_ID", "COURSE_ID"],
                set_={
                    "IS_REMOVED": False,
                    "REMOVED_AT": None,
                    "JOIN_SOURCE": SOURCE_EMAIL_INVITE,
                    "JOINED_AT": now,
                    "UPDATED_USER": operator.user_id,
                    "UPDATED_DATE": now,
                },
                where=EtEnrollment.is_removed.is_(True),
            )
        )
        await db.execute(stmt)
        await db.flush()
