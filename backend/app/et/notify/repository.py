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

#: `DP_USER.STATUS` 之啟用值；非此值者一律被 `core/auth.py` 擋在 API 之外。
_STATUS_ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class Recipient:
    """一位可寄信的收件人。

    `status` 為 `DP_USER.STATUS` 原值，**刻意設為必填**：#362 讓 Email 邀請從「只是寄信」
    變成「寫入成員資格」，呼叫端必須能判斷帳號是否已停用。給預設值會讓忘記帶的呼叫端
    fail-open（把停用帳號當成正常人），必填則是 `TypeError`、當場就發現。

    ⚠️ 判定一律經 `dp/users/account_status.is_account_disabled()`，**不要**自行比對
    `"DISABLED"`——`STATUS` 值域屬 DP 語意。
    """

    user_id: str
    user_name: str
    email: str
    status: str


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
            select(DpUser.user_id, DpUser.user_name, DpUser.email, DpUser.status).where(
                DpUser.user_id.in_(list(user_ids)),
                DpUser.deleted == 0,
            )
        )
        return sorted(
            (
                Recipient(user_id=uid, user_name=name, email=email, status=status)
                for uid, name, email, status in rows
                if email
            ),
            key=lambda r: r.user_id,
        )

    async def active_recipients(self, db: AsyncSession, user_ids: Sequence[str]) -> list[Recipient]:
        """同 `recipients`，但**只取帳號狀態為 `ACTIVE` 者**——供排程之週期性信件使用。

        ## 為何不是直接改 `recipients`

        那支刻意不濾帳號狀態，理由見其 docstring（收件對象要與成員資格是同一組人，否則
        「3 人被加入卻只寄 2 封」而無人知道少了誰）。那個決定對**事件觸發**的信是對的。

        ## 為何**週期性**的信必須濾

        `app/dp/users/service.py::disable_idle_accounts` 每日把閒置逾 90 天的帳號設為
        `DISABLED`，而它**完全不碰 `ET_USER_ROLE`**——於是那個人的 ET 角色列還在。
        `core/auth.py` 對非 `ACTIVE` 帳號一律 403，也就是說**停用擋住了 API、卻擋不住信**：
        一位離職／被自動停用的管理者，其信箱會無限期地每週收到全站課程統計與學員姓名，
        而郵件是當時唯一還通的管道。

        事件觸發的信只在當下寄一次、且以動作為前提（有人把他加進課程）；週期性的信沒有
        任何動作為前提，只要角色列還在就會一直寄下去——兩者的風險量級不同。
        """
        if not user_ids:
            return []
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name, DpUser.email, DpUser.status).where(
                DpUser.user_id.in_(list(user_ids)),
                DpUser.status == _STATUS_ACTIVE,
                DpUser.deleted == 0,
            )
        )
        return sorted(
            (
                Recipient(user_id=uid, user_name=name, email=email, status=status)
                for uid, name, email, status in rows
                if email
            ),
            key=lambda r: r.user_id,
        )

    async def recipients_by_emails(self, db: AsyncSession, emails: Sequence[str]) -> list[Recipient]:
        """依 Email 批次找帳號；**查無者不出現在結果中**（由呼叫端比對出缺哪幾筆）。

        一次查完而非逐筆查：Email 邀請單次最多 50 筆，逐筆查是 50 趟往返，而呼叫端
        本來就要「先驗證全部、再決定寄不寄」，逐筆查也拿不到提早結束的好處。

        `DP_USER.EMAIL` 以小寫儲存（見 `dp/user` 之註冊流程），呼叫端須先正規化
        （`invitation/rules.parse_emails` 已做）。

        ## 回傳 `status`，讓呼叫端自己決定停用帳號怎麼辦

        本方法**不**在 SQL 裡濾掉停用帳號——兩個呼叫端要的行為相反：標籤帶入那條路只是
        寄信（寄給停用者無害），Email 邀請那條會**寫入成員資格**（見
        `invitation/service._require_known_recipients`）。故值域判定交給呼叫端，以
        `dp/users/account_status.is_account_disabled()` 為準，**不得**自行比對 `"DISABLED"`
        字面值（`STATUS` 值域屬 DP 語意）。

        ⚠️ `DELETED = 0` 這道過濾對停用者**完全無效**：EDMS 沒有刪除使用者的功能，
        `DP_USER.DELETED` 從來沒有任何 code path 會設成 1，停用一律走 `STATUS`。
        """
        if not emails:
            return []
        rows = await db.execute(
            select(DpUser.user_id, DpUser.user_name, DpUser.email, DpUser.status).where(
                DpUser.email.in_(list(emails)),
                DpUser.deleted == 0,
            )
        )
        return [Recipient(user_id=uid, user_name=name, email=email, status=status) for uid, name, email, status in rows]

    async def user_name(self, db: AsyncSession, user_id: str) -> str | None:
        """使用者顯示姓名（課程擁有者用於 `{TEACHER_NAME}`）。"""
        return await db.scalar(select(DpUser.user_name).where(DpUser.user_id == user_id, DpUser.deleted == 0))
