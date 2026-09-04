"""Email 邀請資料存取（US8 / #273）。

`ET_INVITATION` 與 `ET_ENROLLMENT` 之寫入都在此。
"""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import (
    COMPLETION_NOT_STARTED,
    INVITATION_JOINED,
    INVITATION_PENDING,
    SOURCE_EMAIL_INVITE,
)
from app.et.course.models import EtCourse
from app.et.invitation.models import EtInvitation
from app.et.progress.models import EtEnrollment


class EtInvitationRepository:
    """`ET_INVITATION` 之建立 / 查詢 / 消耗，以及受邀者加入課程之 upsert。"""

    async def get_course(self, db: AsyncSession, course_id: int) -> EtCourse | None:
        return await db.scalar(select(EtCourse).where(EtCourse.course_id == course_id, EtCourse.deleted == 0))

    async def upsert_pending(
        self,
        db: AsyncSession,
        *,
        course_id: int,
        email: str,
        token_hash: str,
        send_status_code: str,
        operator: OperatorInfo,
    ) -> EtInvitation:
        """建立或更新一筆待加入邀請。

        同課程同 Email 已有 `PENDING` 列時**更新該列**、不建新列（data-model
        §ET_INVITATION：「再次寄送」更新 `LAST_SENT_AT`，不建新紀錄）。否則 US12 待加入
        清單會出現同一個 Email 的重複列，教師無從判斷該重寄哪一筆。

        ⚠️ **再次寄送必須換新 token**（覆寫 `TOKEN_HASH`）：舊 token 已隨信件流出，
        沿用同一組會讓「一次性」只是延後生效——舊連結仍可被轉發者使用。覆寫的當下
        舊連結即失效。

        Args:
            send_status_code: 本次**排入 outbox** 的結果（非真實 SMTP 結果，見
                `service.py` 之說明）。

        Returns:
            建立或更新後之邀請列。
        """
        now = utcnow()
        existing = await db.scalar(
            select(EtInvitation).where(
                EtInvitation.course_id == course_id,
                EtInvitation.email == email,
                EtInvitation.status == INVITATION_PENDING,
                EtInvitation.deleted == 0,
            )
        )
        if existing is not None:
            existing.token_hash = token_hash
            existing.last_sent_at = now
            existing.send_status_code = send_status_code
            existing.updated_user = operator.user_id
            existing.updated_date = now
            await db.flush()
            return existing

        invitation = EtInvitation(
            course_id=course_id,
            email=email,
            token_hash=token_hash,
            status=INVITATION_PENDING,
            sent_at=now,
            last_sent_at=now,
            send_status_code=send_status_code,
            created_user=operator.user_id,
            created_date=now,
            deleted=0,
        )
        db.add(invitation)
        await db.flush()
        return invitation

    async def get_by_token_hash(self, db: AsyncSession, token_hash: str) -> EtInvitation | None:
        return await db.scalar(
            select(EtInvitation).where(EtInvitation.token_hash == token_hash, EtInvitation.deleted == 0)
        )

    async def consume_pending(self, db: AsyncSession, *, invitation_id: int, operator: OperatorInfo) -> bool:
        """原子消耗邀請：**只有仍為 `PENDING` 才成功**（`PENDING → JOINED`，終態）。

        🔴 **條件必須寫在 `WHERE` 裡，不可先查後改**。前一版是「`select` 讀出 → 比對
        `status` → ORM 屬性賦值」，那是 TOCTOU：兩個請求（各自獨立的 session，`get_db`
        要到 request 結束才 commit）都會在對方 commit 前讀到 `PENDING`，各自
        `upsert_enrollment`（不同 `USER_ID` → 不同列、互不阻擋），最後兩筆不帶條件的
        `UPDATE ... WHERE INVITATION_ID=:id` 依序把同一列改成 `JOINED`——**兩個人都加入
        成功**。

        那正是一次性要擋的「連結被轉發」情境，只是用並發而非循序達成。而一次性是
        #273 Q1 裁示用來取代「登入帳號 Email 比對」的**唯一**控制，被繞過就沒有第二道。
        轉發到群組聊天室、多人同時點，是最自然的觸發情境，不需要刻意攻擊。

        `READ COMMITTED` 下，後到的 `UPDATE` 會等前一筆的 row lock 釋放後**重新評估
        `WHERE`**（EvalPlanQual），此時 `STATUS` 已是 `JOINED` → 命中 0 列 → 回 False。
        故「恰好一人成功」由資料庫保證，而非由應用層的讀寫間隙保證。

        Returns:
            True 表示本次呼叫消耗成功；False 表示已被其他請求消耗（呼叫端應改走
            「已消耗」分支）。
        """
        now = utcnow()
        result = await db.execute(
            update(EtInvitation)
            .where(
                EtInvitation.invitation_id == invitation_id,
                EtInvitation.status == INVITATION_PENDING,
                EtInvitation.deleted == 0,
            )
            .values(
                status=INVITATION_JOINED,
                joined_at=now,
                updated_user=operator.user_id,
                updated_date=now,
            )
        )
        await db.flush()
        return (result.rowcount or 0) > 0

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
