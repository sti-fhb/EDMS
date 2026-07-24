from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dp.params.models import DpParamDetail, DpParamMaster


class ParamRepository:
    """DP_PARAM_M / DP_PARAM_D 存取（軟刪除項一律排除）。唯讀方法供 SRVDP001；維護寫入方法供 US5。"""

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

    # ── 維護（US5）：主檔查詢 + 明細寫入 ──

    async def list_masters(self, db: AsyncSession) -> list[DpParamMaster]:
        """取所有參數主檔（排除軟刪除），依 PARAM_ID 排序。前綴過濾由 service 依操作者身分套用。"""
        stmt = select(DpParamMaster).where(DpParamMaster.deleted == 0).order_by(DpParamMaster.param_id)
        return list((await db.execute(stmt)).scalars().all())

    async def get_master(self, db: AsyncSession, param_id: str) -> DpParamMaster | None:
        """以 PARAM_ID 取主檔（排除軟刪除）；不存在回 None。"""
        stmt = select(DpParamMaster).where(DpParamMaster.param_id == param_id, DpParamMaster.deleted == 0)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def update_detail(
        self,
        db: AsyncSession,
        *,
        detail: DpParamDetail,
        fields: dict,
        operator_id: str,
        now: datetime,
    ) -> None:
        """更新明細欄位（fields 僅含要更動的鍵：名稱/值/說明/啟停）+ 稽核欄位並 flush。"""
        for attr in ("param_name", "param_value", "description", "is_enabled"):
            if attr in fields:
                setattr(detail, attr, fields[attr])
        detail.updated_user = operator_id
        detail.updated_date = now
        await db.flush()

    async def create_detail(
        self,
        db: AsyncSession,
        *,
        param_id: str,
        param_key: str,
        param_name: str,
        param_value: str | None,
        description: str | None,
        sort_order: int | None,
        operator_id: str,
        now: datetime,
    ) -> DpParamDetail:
        """新增清單項明細 + 稽核欄位並 flush。"""
        detail = DpParamDetail(
            param_id=param_id,
            param_key=param_key,
            param_name=param_name,
            param_value=param_value,
            description=description,
            sort_order=sort_order,
            is_enabled=True,
            created_user=operator_id,
            created_date=now,
        )
        db.add(detail)
        await db.flush()
        return detail
