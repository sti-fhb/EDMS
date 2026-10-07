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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel

#: `ET_TAG.TAG_TYPE` 之兩個值；刻意與 DM 之 `GROUP_TYPE` 同值（DP02 以 `kind == "UNIT"` 判定配對模式）
TAG_TYPE_AUDIENCE = "AUDIENCE"
TAG_TYPE_UNIT = "UNIT"


class EtTag(BaseModel):
    """受訓對象標籤庫（ET_TAG）——**職位**與**單位**兩類，以 `TAG_TYPE` 區分（#538）。

    | `TAG_TYPE` | 內建種子 | 通用值（`IS_ALL`）|
    |---|---|---|
    | `AUDIENCE`（職位）| 全體 / 護理師 / 行政人員 / 軍人 / 醫檢師 | 全體 |
    | `UNIT`（單位）| 全單位 + 20 個單位（複製自 DM，只對齊一次）| 全單位 |

    課程與使用者都掛 `(單位, 職位)` 配對（見 `catalog/pair.py`）。不提供刪除、僅停用
    （soft-retire）：停用後不可再出現於新配對，既有配對不受影響。

    通用值（`IS_ALL=true`）代表「不限」：課程掛 `(全單位, 全體)` 即全部具學員角色者，
    不需逐人貼標。**不可停用、不可改名**（轉接層伺服器端拒絕，`ET_TAG_001`）。
    **每個 `TAG_TYPE` 僅 1 筆** `IS_ALL=true`（`UX_ET_TAG_TYPE_ALL`）。

    ⭐ 通用值一律以 `IS_ALL` 判定、**不以名稱判定**——DM 以 `TAG_NAME` 辨識「全單位」，
    把某個單位改名為「全單位」即等於擴權（#437 follow-up 1）。
    """

    __tablename__ = "ET_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("TAG_ID", name="PK_ET_TAG"),
        UniqueConstraint("TAG_NAME", name="UQ_ET_TAG_NAME"),
        Index("UX_ET_TAG_TYPE_ALL", "TAG_TYPE", unique=True, postgresql_where=text('"IS_ALL"')),
    )

    tag_id: Mapped[int] = mapped_column("TAG_ID", BigInteger, Identity(), nullable=False)
    tag_name: Mapped[str] = mapped_column("TAG_NAME", String(50), nullable=False)
    tag_type: Mapped[str] = mapped_column(
        "TAG_TYPE", String(10), nullable=False, default=TAG_TYPE_AUDIENCE, server_default=TAG_TYPE_AUDIENCE
    )
    is_active: Mapped[bool] = mapped_column("IS_ACTIVE", Boolean, nullable=False, default=True)
    is_all: Mapped[bool] = mapped_column("IS_ALL", Boolean, nullable=False, default=False)
    is_builtin: Mapped[bool] = mapped_column("IS_BUILTIN", Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column("DISPLAY_ORDER", Integer, nullable=False, default=0)


class EtUserTag(BaseModel):
    """使用者 × 受訓對象配對（ET_USER_TAG）——一列為一組 `(單位, 職位)`（#538）。

    一人可有多組配對，由管理者於 DP 後台「權限管理」指派（SRVET003）。
    `UNIT_TAG_ID` 為 NULL ＝**單位未指定**（#538 導入前之既有指派），只匹配課程端「全單位」。
    人身上不掛通用值（「全體」「全單位」）——它們是課程端「不限」的語意。

    貼標追溯（業務判定留 ET）：**新增**對應時自動補加入該標籤所有「已發布且未關閉」
    課程並寄彙整信；**移除**時既有 `ET_ENROLLMENT` 不變動。
    """

    __tablename__ = "ET_USER_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("USER_TAG_ID", name="PK_ET_USER_TAG"),
        # NULLS NOT DISTINCT：否則單位未指定（NULL）的列不受唯一約束保護，可重複寫入同一組
        UniqueConstraint(
            "USER_ID", "TAG_ID", "UNIT_TAG_ID", name="UQ_ET_USER_TAG_USER_TAG", postgresql_nulls_not_distinct=True
        ),
        Index("IX_ET_USER_TAG_USER", "USER_ID"),
    )

    user_tag_id: Mapped[int] = mapped_column("USER_TAG_ID", BigInteger, Identity(), nullable=False)
    user_id: Mapped[str] = mapped_column("USER_ID", String(20), nullable=False)
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_USER_TAG_TAG"), nullable=False
    )
    unit_tag_id: Mapped[int | None] = mapped_column(
        "UNIT_TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_USER_TAG_UNIT"), nullable=True
    )


class EtCourseTag(BaseModel):
    """課程 × 受訓對象配對（ET_COURSE_TAG）——一列為一組 `(單位, 職位)`（#538）。

    一課程可掛多組；**發布前至少 1 組**（發布檢核）。已發布課程可**新增**配對
    （觸發該配對對應人員補邀請＋寄信），**不可移除**既有配對；草稿狀態可自由增刪。
    新配對的兩欄皆須 `IS_ACTIVE=true`（既有配對中已停用者保留）。

    `UNIT_TAG_ID` **NOT NULL**：課程端兩欄必填，「不限單位」以「全單位」表達。
    """

    __tablename__ = "ET_COURSE_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("COURSE_TAG_ID", name="PK_ET_COURSE_TAG"),
        UniqueConstraint(
            "COURSE_ID", "TAG_ID", "UNIT_TAG_ID", name="UQ_ET_COURSE_TAG_COURSE_TAG", postgresql_nulls_not_distinct=True
        ),
        Index("IX_ET_COURSE_TAG_TAG", "TAG_ID"),
    )

    course_tag_id: Mapped[int] = mapped_column("COURSE_TAG_ID", BigInteger, Identity(), nullable=False)
    course_id: Mapped[int] = mapped_column(
        "COURSE_ID", BigInteger, ForeignKey("ET_COURSE.COURSE_ID", name="FK_ET_COURSE_TAG_COURSE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        "TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_COURSE_TAG_TAG"), nullable=False
    )
    unit_tag_id: Mapped[int] = mapped_column(
        "UNIT_TAG_ID", BigInteger, ForeignKey("ET_TAG.TAG_ID", name="FK_ET_COURSE_TAG_UNIT"), nullable=False
    )
