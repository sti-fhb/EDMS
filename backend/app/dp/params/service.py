"""參數唯讀查詢服務（SRVDP001）。

供各模組讀取 DP_PARAM 之參數值與清單定義（唯讀；維護僅經 DP 後台 US5）。
不快取——儲存即生效（research §7），每次讀 DB。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.params.repository import ParamRepository
from app.dp.params.schemas import ParamItem


class ParamService:
    """SRVDP001 參數唯讀服務（跨模組經 app.services 呼叫）。"""

    def __init__(self, repository: ParamRepository | None = None) -> None:
        self._repo = repository or ParamRepository()

    async def get_param_value(self, db: AsyncSession, param_id: str, key: str = "VALUE") -> str | None:
        """取單值參數；PARAM_ID / PARAM_KEY 不存在或明細停用皆回 None。

        Args:
            db: 呼叫方 AsyncSession。
            param_id: 參數主檔代碼（如 JWT）。
            key: 明細碼；單值參數固定 VALUE，群組型傳實際碼（如 ACCESS_TTL_MIN）。

        Returns:
            PARAM_VALUE 字串；查無或停用回 None（利呼叫方以預設值 fallback）。
        """
        detail = await self._repo.get_detail(db, param_id, key)
        if detail is None or not detail.is_enabled:
            return None
        return detail.param_value

    async def get_int_param(self, db: AsyncSession, param_id: str, key: str, default: int) -> int:
        """取整數參數；查無 / 停用 / 非整數字串一律回 default（利呼叫方安全 fallback）。"""
        raw = await self.get_param_value(db, param_id, key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    async def get_param_list(self, db: AsyncSession, param_id: str, enabled_only: bool = True) -> list[ParamItem]:
        """取清單型參數定義，依 SORT_ORDER 排序。

        Args:
            db: 呼叫方 AsyncSession。
            param_id: 參數主檔代碼（如 ACTION_TYPE）。
            enabled_only: True（預設）僅回啟用項；False 連停用項一併回傳。

        Returns:
            ParamItem 清單；PARAM_ID 不存在回空清單（非例外）。
        """
        details = await self._repo.list_details(db, param_id, enabled_only)
        return [
            ParamItem(key=d.param_key, value=d.param_value, is_enabled=d.is_enabled, sort_order=d.sort_order)
            for d in details
        ]
