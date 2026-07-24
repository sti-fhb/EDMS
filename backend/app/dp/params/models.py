from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class DpParamMaster(BaseModel):
    """功能參數主檔（DP_PARAM_M）。

    PARAM_ID 前綴決定歸屬：無前綴＝平台級（共用）、ET_ / DM_＝模組級。
    PARAM_TYPE：VALUE（單值參數）/ LIST（清單定義）。
    DETAIL_LOCK：true＝明細 PARAM_KEY 建立後不可修改碼值（如分類碼）。
    標準欄位由 BaseModel 繼承。
    """

    __tablename__ = "DP_PARAM_M"
    __table_args__ = (PrimaryKeyConstraint("PARAM_ID", name="PK_DP_PARAM_M"),)

    param_id: Mapped[str] = mapped_column("PARAM_ID", String(50), nullable=False)
    param_name: Mapped[str] = mapped_column("PARAM_NAME", String(100), nullable=False)
    param_type: Mapped[str] = mapped_column("PARAM_TYPE", String(10), nullable=False)
    detail_lock: Mapped[bool] = mapped_column("DETAIL_LOCK", Boolean, nullable=False, default=False)
    description: Mapped[Optional[str]] = mapped_column("DESCRIPTION", String(500), nullable=True)


class DpParamDetail(BaseModel):
    """功能參數明細（DP_PARAM_D，主檔一對多）。

    PARAM_NAME＝中文顯示名稱（自描述，供維護頁與各模組下拉；取代前端硬編碼）。
    PARAM_VALUE＝實際值（VALUE 型放值、LIST 型可空或放業務碼值）。
    單值參數固定 PARAM_KEY='VALUE'；清單型 PARAM_KEY 為清單項代碼。
    IS_ENABLED 控制清單項啟用 / 停用（不開放刪除，淘汰改停用）。標準欄位由 BaseModel 繼承。
    """

    __tablename__ = "DP_PARAM_D"
    __table_args__ = (PrimaryKeyConstraint("PARAM_ID", "PARAM_KEY", name="PK_DP_PARAM_D"),)

    param_id: Mapped[str] = mapped_column(
        "PARAM_ID",
        String(50),
        ForeignKey("DP_PARAM_M.PARAM_ID", name="FK_DP_PARAM_D_PARAM"),
        nullable=False,
    )
    param_key: Mapped[str] = mapped_column("PARAM_KEY", String(50), nullable=False)
    param_name: Mapped[str] = mapped_column("PARAM_NAME", String(100), nullable=False)
    param_value: Mapped[Optional[str]] = mapped_column("PARAM_VALUE", String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column("DESCRIPTION", String(500), nullable=True)
    sort_order: Mapped[Optional[int]] = mapped_column("SORT_ORDER", Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)
