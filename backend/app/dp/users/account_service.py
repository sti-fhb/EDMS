"""帳號狀態唯讀查詢服務（跨模組出口，#250）。

其他頂層模組（ET / DM）在**寫入前判斷帳號可用性**時走這裡，不直接 JOIN `DP_USER`——
依 `sti-backend-boundaries.md`，報表 / 查詢類唯讀 JOIN 雖為例外，但「查詢結果若作為
寫入或狀態判斷的依據，同樣視為業務邏輯」，須經對方模組 Service。

純顯示用途（如下拉清單）仍可走唯讀 JOIN，見 `app/dm/roles/reviewer_query.py`。

刻意只暴露唯讀布林：`UsersService` 含建立 / 停用 / 解鎖等寫入方法，整個匯出等於把
帳號寫入能力交給其他模組。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.dp.users.account_status import is_account_usable
from app.dp.users.service import UsersService


class AccountQueryService:
    """帳號狀態唯讀查詢（跨模組）。"""

    def __init__(self, users: UsersService | None = None) -> None:
        self._users = users or UsersService()

    async def is_usable(self, db: AsyncSession, user_id: str) -> bool:
        """帳號目前是否可用（未停用、未鎖定中）。

        查無帳號（含軟刪除）回 False——跨模組呼叫端多為「此人可否承接任務」之判斷，
        不存在的帳號一律視為不可用（fail-closed）。DP 內部若需區分「查無」與「不可用」，
        請直接用 `UsersService.get_account_status`。

        Args:
            db: DB session。
            user_id: 目標帳號 USER_ID。

        Returns:
            可用 True；停用 / 鎖定中 / 查無 回 False。
        """
        account = await self._users.get_account_status(db, user_id)
        if account is None:
            return False
        return is_account_usable(status=account.status, locked_until=account.locked_until, now=utcnow())
