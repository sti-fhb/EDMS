from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, PrimaryKeyConstraint, String
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
    EDIT_SCOPE＝維護層級（#171），見該欄位說明。
    """

    __tablename__ = "DP_PARAM_D"
    __table_args__ = (
        PrimaryKeyConstraint("PARAM_ID", "PARAM_KEY", name="PK_DP_PARAM_D"),
        CheckConstraint(
            "\"EDIT_SCOPE\" IN ('ADMIN', 'READONLY', 'HIDDEN')",
            name="CK_DP_PARAM_D_EDIT_SCOPE",
        ),
    )

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
    # 維護層級（#171）：ADMIN＝管理者可於 DP07 編輯；READONLY＝顯示現值但整列唯讀；
    # HIDDEN＝不出現於維護頁。READONLY / HIDDEN 之值由 IT 於 DB 端變更，且 MUST 經 migration
    # 而非手動 UPDATE——維護頁那條會寫稽核的路徑已不存在，migration 檔是唯一的紀錄
    # （spec_us5 FR-DP-US5-11）。
    # 與 DP_PARAM_M.DETAIL_LOCK 正交：後者鎖的是 PARAM_KEY 碼值，本欄管的是誰能改這一列。
    # Python-side default 而非 server_default——見 migration 71ca59c07bd1 的 docstring。
    edit_scope: Mapped[str] = mapped_column("EDIT_SCOPE", String(20), nullable=False, default="ADMIN")
