from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.params.models import DpParamDetail


class ParamRepository:
    """DP_PARAM_D 唯讀存取（軟刪除項一律排除）。"""

    async def get_detail(self, db: AsyncSession, param_id: str, param_key: str) -> DpParamDetail | None:
        """取單筆明細；不存在回 None。"""
        stmt = select(DpParamDetail).where(
            DpParamDetail.param_id == param_id,
            DpParamDetail.param_key == param_key,
            DpParamDetail.deleted == 0,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_details(self, db: AsyncSession, param_id: str, enabled_only: bool) -> list[DpParamDetail]:
        """取某主檔的所有明細，依 SORT_ORDER 排序；enabled_only 過濾停用項。"""
        stmt = select(DpParamDetail).where(
            DpParamDetail.param_id == param_id,
            DpParamDetail.deleted == 0,
        )
        if enabled_only:
            stmt = stmt.where(DpParamDetail.is_enabled.is_(True))
        # 次要鍵 param_key：SORT_ORDER 可為 NULL / 相同值，加次要鍵確保跨查詢排序穩定
        stmt = stmt.order_by(DpParamDetail.sort_order, DpParamDetail.param_key)
        result = await db.execute(stmt)
        return list(result.scalars().all())
