"""DM 受控資料 model（DM_CATEGORY / DM_FUNC / DM_TAG_GROUP / DM_TAG）。

分類 / func_name / 標籤庫皆採共通維護：不開放刪除、淘汰改停用、停用後既有引用保留。
分類碼供 DOC_ID 嵌入、建立後鎖定。標籤組分權限（AUDIENCE）與檢索（RETRIEVAL）兩用途。
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class DmCategory(BaseModel):
    """文件分類（DM_CATEGORY）。

    4 內建（SOP / MANUAL / TRAINING / OTHER）+ 管理者自訂（平面）。CATEGORY_CODE 為 PK、
    唯一英數、建立後鎖定（供 DOC_ID 嵌入）；內建分類碼固定僅可改名。不刪除、淘汰改停用。
    """

    __tablename__ = "DM_CATEGORY"
    __table_args__ = (PrimaryKeyConstraint("CATEGORY_CODE", name="PK_DM_CATEGORY"),)

    category_code: Mapped[str] = mapped_column("CATEGORY_CODE", String(10), nullable=False)
    category_name: Mapped[str] = mapped_column("CATEGORY_NAME", String(50), nullable=False)
    is_builtin: Mapped[bool] = mapped_column("IS_BUILTIN", Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)


class DmFunc(BaseModel):
    """關聯作業項目 / func_name（DM_FUNC）。

    系統操作手冊類文件可標記之主系統作業功能代號；受控、不可自由輸入；不刪除只停用。
    """

    __tablename__ = "DM_FUNC"
    __table_args__ = (PrimaryKeyConstraint("FUNC_CODE", name="PK_DM_FUNC"),)

    func_code: Mapped[str] = mapped_column("FUNC_CODE", String(10), nullable=False)
    func_name: Mapped[str] = mapped_column("FUNC_NAME", String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)


class DmTagGroup(BaseModel):
    """標籤組（DM_TAG_GROUP）。

    4 內建組（AUDIENCE / MODULE / NATURE / LEGAL）；GROUP_TYPE 分權限（AUDIENCE，可見對象/單位）
    與檢索（RETRIEVAL）兩用途。AUDIENCE 組為標籤式可見性之權限依據。
    """

    __tablename__ = "DM_TAG_GROUP"
    __table_args__ = (PrimaryKeyConstraint("TAG_GROUP_CODE", name="PK_DM_TAG_GROUP"),)

    tag_group_code: Mapped[str] = mapped_column("TAG_GROUP_CODE", String(20), nullable=False)
    tag_group_name: Mapped[str] = mapped_column("TAG_GROUP_NAME", String(50), nullable=False)
    group_type: Mapped[str] = mapped_column("GROUP_TYPE", String(10), nullable=False, default="RETRIEVAL")
    is_builtin: Mapped[bool] = mapped_column("IS_BUILTIN", Boolean, nullable=False, default=True)


class DmTag(BaseModel):
    """標籤（DM_TAG）。

    受控標籤庫；撰寫者只能挑選不可自由輸入；不刪除只停用。AUDIENCE 組之停用採 soft-retire
    （不收回既有可見性）；AUDIENCE 組含通用值「全體」（文件掛上即所有閱覽者可見）。
    """

    __tablename__ = "DM_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("TAG_ID", name="PK_DM_TAG"),
        Index("IX_DM_TAG_GROUP", "TAG_GROUP_CODE"),
    )

    tag_id: Mapped[int] = mapped_column("TAG_ID", BigInteger, Identity(), nullable=False)
    tag_group_code: Mapped[str] = mapped_column(
        "TAG_GROUP_CODE", String(20), ForeignKey("DM_TAG_GROUP.TAG_GROUP_CODE", name="FK_DM_TAG_GROUP"), nullable=False
    )
    tag_name: Mapped[str] = mapped_column("TAG_NAME", String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)
