"""DM 閱覽者可見對象授權 model（DM_USER_TAG）。

使用者 × (單位, 職位) 配對；由管理者於平台 DP 後台權限管理維護，決定閱覽者於文件庫之
可見範圍（標籤式可見性）。`USER_ID` 邏輯 FK 指向平台 `DP_USER`。
"""

from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class DmUserTag(BaseModel):
    """閱覽者可見對象授權（DM_USER_TAG，明細）。

    一列即一組 (單位, 職位) 配對（#437）：`TAG_ID` 存職位（限 AUDIENCE 組，應用層檢核）、
    `UNIT_TAG_ID` 存單位（限 UNIT 組）。唯一約束 (USER_ID, TAG_ID, UNIT_TAG_ID)，NULLS NOT DISTINCT。

    **`UNIT_TAG_ID` 允許 NULL，語意為「單位未指定」**，非「不限單位」——判定上僅能匹配文件側掛
    「全單位」之配對（`visibility.py`）。此為 #437 導入單位維度前既有授權之過渡狀態：既有列保持
    NULL，其可見範圍與導入前完全相同；管理者補上單位後才**額外**看得到指定單位之文件。

    未授予任何列之閱覽者僅能看到掛「全體」之文件。UPDATED_* 即權限管理「最後異動」欄之來源。
    """

    __tablename__ = "DM_USER_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("USER_TAG_ID", name="PK_DM_USER_TAG"),
        UniqueConstraint(
            "USER_ID", "TAG_ID", "UNIT_TAG_ID", name="UQ_DM_USER_TAG_USER_TAG", postgresql_nulls_not_distinct=True
        ),
        Index("IX_DM_USER_TAG_USER", "USER_ID"),
    )

    user_tag_id: Mapped[int] = mapped_column("USER_TAG_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("DM_TAG.TAG_ID", name="FK_DM_USER_TAG_TAG"), nullable=False
    )
    unit_tag_id: Mapped[Optional[int]] = mapped_column(
        "UNIT_TAG_ID", BigInteger, ForeignKey("DM_TAG.TAG_ID", name="FK_DM_USER_TAG_UNIT"), nullable=True
    )
