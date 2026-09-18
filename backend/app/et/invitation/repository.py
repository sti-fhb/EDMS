"""Email 邀請資料存取（US8 / #273）。

`ET_INVITATION` 與 `ET_ENROLLMENT` 之寫入都在此。
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
    """`ET_INVITATION` 之建立 / 查詢 / 消耗，以及受邀者加入課程之 upsert。"""

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def get_enrollment(self, db: AsyncSession, *, user_id: str, course_id: int) -> EtEnrollment | None:
        return await db.scalar(
            select(EtEnrollment).where(EtEnrollment.user_id == user_id, EtEnrollment.course_id == course_id)
        )

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
            )
        )
        await db.execute(stmt)
        await db.flush()
