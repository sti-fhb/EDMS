"""通知收件人查詢（US8 / #273）。

`DP_USER` 為平台主表，ET 僅以 `USER_ID` 引用；此處為**唯讀 join**，屬
`sti-backend-boundaries` §報表/查詢例外（已列於 `et/spec.md` 之外模組 table 引用清單），
與 `app/et/course/service.py` / `app/et/enrollment/repository.py` 之既有用法一致。
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，見模組 docstring）


@dataclass(frozen=True)
class Recipient:
    """一位可寄信的收件人。"""

    user_id: str
    user_name: str
    email: str


class EtNotifyRepository:
    """通知信所需之使用者姓名與 Email。"""

    async def recipients(self, db: AsyncSession, user_ids: Sequence[str]) -> list[Recipient]:
        """取這批使用者的姓名與 Email，**略過沒有 Email 者**。

        不以 `STATUS='ACTIVE'` 過濾：帶入課程的判定依 `ET_USER_ROLE`（見
        `tag_invite.target_user_ids`），此處若另加一道帳號狀態過濾，會出現「3 人被加入
        卻只寄 2 封」而無人知道少了誰。收件對象與成員資格保持同一組人。

        Returns:
            依 `USER_ID` 排序之收件人清單（排序使寄信順序可預期、測試可重現）。
        """
        if not user_ids:
            return []
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name, DpUser.email).where(
                DpUser.user_id.in_(list(user_ids)),
                DpUser.deleted == 0,
            )
        )
        return sorted(
            (Recipient(user_id=uid, user_name=name, email=email) for uid, name, email in rows if email),
            key=lambda r: r.user_id,
        )

    async def recipients_by_emails(self, db: AsyncSession, emails: Sequence[str]) -> list[Recipient]:
        """依 Email 批次找帳號；**查無者不出現在結果中**（由呼叫端比對出缺哪幾筆）。

        一次查完而非逐筆查：Email 邀請單次最多 50 筆，逐筆查是 50 趟往返，而呼叫端
        本來就要「先驗證全部、再決定寄不寄」，逐筆查也拿不到提早結束的好處。

        `DP_USER.EMAIL` 以小寫儲存（見 `dp/user` 之註冊流程），呼叫端須先正規化
        （`invitation/rules.parse_emails` 已做）。
        """
        if not emails:
            return []
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name, DpUser.email).where(
                DpUser.email.in_(list(emails)),
                DpUser.deleted == 0,
            )
        )
        return [Recipient(user_id=uid, user_name=name, email=email) for uid, name, email in rows]

    async def user_name(self, db: AsyncSession, user_id: str) -> str | None:
        """使用者顯示姓名（課程擁有者用於 `{TEACHER_NAME}`）。"""
        return await db.scalar(select(DpUser.user_name).where(DpUser.user_id == user_id, DpUser.deleted == 0))
