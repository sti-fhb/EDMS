"""DM 閱覽者可見對象授權 model（DM_USER_TAG）。

使用者 × 「可見對象/單位」標籤（限 AUDIENCE 組）；由管理者於平台 DP 後台權限管理維護，
決定閱覽者於文件庫之可見範圍（標籤式可見性）。`USER_ID` 邏輯 FK 指向平台 `DP_USER`。
"""

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class DmUserTag(BaseModel):
    """閱覽者可見對象授權（DM_USER_TAG，明細）。

    唯一約束 (USER_ID, TAG_ID)。TAG_ID 限 AUDIENCE 組（應用層檢核）。未授予任何列之閱覽者
    僅能看到掛「全體」之文件。UPDATED_* 即權限管理「最後異動」欄之來源。
    """

    __tablename__ = "DM_USER_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("USER_TAG_ID", name="PK_DM_USER_TAG"),
        UniqueConstraint("USER_ID", "TAG_ID", name="UQ_DM_USER_TAG_USER_TAG"),
        Index("IX_DM_USER_TAG_USER", "USER_ID"),
    )

    user_tag_id: Mapped[int] = mapped_column("USER_TAG_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("DM_TAG.TAG_ID", name="FK_DM_USER_TAG_TAG"), nullable=False
    )
