"""ET 受訓單位標籤 model（ET_TAG / ET_USER_TAG / ET_COURSE_TAG）。

**標籤庫為 ET 自持表**（非 `DP_PARAM`）——2026-08-19（#181）確認：DP 之
`module-callbacks.md` §3 / §3.1 雖仍寫「ET 之 tags 存 DP_PARAM」，但 DP 程式碼
`dp/roles/service.py` 之 `group_options()` 為模組無關實作（取 provider →
`list_audiences()`，不讀 `DP_PARAM`），且 DM 已於 2026-08-06（#127）自 `DP_PARAM`
改為 `DM_TAG` 自持表。DP 側文件對齊見 #182。

維護入口於平台 DP 後台「系統參數與清單」，經 ET 之受控主檔轉接層（SRVET004）呼叫，
DP 不直接寫 ET 表。`USER_ID` 為邏輯 FK（不設 DB 外鍵，比照 DM）。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class EtTag(BaseModel):
    """受訓單位標籤庫（ET_TAG）。

    內建種子 5 筆：全體（`IS_ALL`）/ 護理師 / 行政人員 / 軍人 / 醫檢師。
    不提供刪除、僅停用（soft-retire）：停用後不可再掛至新課程，已掛之既有課程不受影響。

    「全體」（`IS_ALL=true`）為特殊標籤，代表所有具「學員」角色之使用者，不需逐人貼標；
    **不可停用、不可改名**（於轉接層 `set_controlled_enabled` / `rename_controlled`
    伺服器端拒絕，`ET_TAG_001`）。全系統僅 1 筆 `IS_ALL=true`。
    """

    __tablename__ = "ET_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("TAG_ID", name="PK_ET_TAG"),
        UniqueConstraint("TAG_NAME", name="UQ_ET_TAG_NAME"),
    )

    tag_id: Mapped[int] = mapped_column("TAG_ID", BigInteger, Identity(), nullable=False)
    tag_name: Mapped[str] = mapped_column("TAG_NAME", String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column("IS_ACTIVE", Boolean, nullable=False, default=True)
    is_all: Mapped[bool] = mapped_column("IS_ALL", Boolean, nullable=False, default=False)
    is_builtin: Mapped[bool] = mapped_column("IS_BUILTIN", Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column("DISPLAY_ORDER", Integer, nullable=False, default=0)


class EtUserTag(BaseModel):
    """使用者 × 受訓單位標籤（ET_USER_TAG）。

    多對多（一人可屬多個受訓單位），由管理者於 DP 後台「權限管理」指派（SRVET003）。
    「全體」標籤**不需逐人建立對應**——`IS_ALL` 於查詢時展開為全部具學員角色者。

    貼標追溯（業務判定留 ET）：**新增**對應時自動補加入該標籤所有「已發布且未關閉」
    課程並寄彙整信；**移除**時既有 `ET_ENROLLMENT` 不變動。
    """

    __tablename__ = "ET_USER_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("USER_TAG_ID", name="PK_ET_USER_TAG"),
        UniqueConstraint("USER_ID", "TAG_ID", name="UQ_ET_USER_TAG_USER_TAG"),
        Index("IX_ET_USER_TAG_USER", "USER_ID"),
    )

    user_tag_id: Mapped[int] = mapped_column("USER_TAG_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_USER_TAG_TAG"), nullable=False
    )


class EtCourseTag(BaseModel):
    """課程 × 受訓單位標籤（ET_COURSE_TAG）。

    一課程可掛多個標籤；**發布前至少 1 筆**（發布檢核）。已發布課程可**新增**標籤
    （觸發該標籤人員補邀請＋寄信），**不可移除**既有標籤；草稿狀態可自由增刪。
    僅可掛 `IS_ACTIVE=true` 之標籤（既有已掛之停用標籤保留）。
    """

    __tablename__ = "ET_COURSE_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("COURSE_TAG_ID", name="PK_ET_COURSE_TAG"),
        UniqueConstraint("COURSE_ID", "TAG_ID", name="UQ_ET_COURSE_TAG_COURSE_TAG"),
        Index("IX_ET_COURSE_TAG_TAG", "TAG_ID"),
    )

    course_tag_id: Mapped[int] = mapped_column("COURSE_TAG_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_COURSE_TAG_COURSE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_COURSE_TAG_TAG"), nullable=False
    )
