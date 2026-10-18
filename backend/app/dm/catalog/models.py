"""DM 受控資料 model（DM_CATEGORY / DM_FUNC / DM_TAG_GROUP / DM_TAG）。

分類 / func_name / 標籤庫皆採共通維護：不開放刪除、淘汰改停用、停用後既有引用保留。
分類碼供 DOC_ID 嵌入、建立後鎖定。標籤組分權限（AUDIENCE）與檢索（RETRIEVAL）兩用途。

## ⛔ 四張表一律繼承 `BaseModelNoDelete`，不要改回 `BaseModel`（#508）

上面那句「不開放刪除」是這四張表的政策，`BaseModelNoDelete` 是它在程式裡的落實。
在 #508 之前它們繼承 `BaseModel`，帶著一個**全後端沒有任何寫入路徑、永遠是 0**
的 `DELETED` 欄位，結果是每個讀取端各自決定要不要濾——濾不濾都沒差，**直到哪天有差**。
當時實況已經不一致：`adapter.py` 只有 `list_controlled_kinds` 一處濾，
`list_controlled` / `list_audiences` 都沒濾。

⛔ 若日後發現某處「少濾了 DELETED」，**正解不是補上過濾**，而是確認這四張表根本
沒有該欄位。

### 什麼守得住、什麼守不住（2026-10-18 變異實測）

| 注入 | 會不會被擋 |
|---|---|
| 四個 model 改回 `BaseModel` | ✅ unit 結構測試紅，且 integration 大面積紅（`UndefinedColumnError`）|
| 只改 model、**migration 沒砍欄位** | ⚠️ **unit 全綠**，只有 integration 紅（INSERT 撞 `NotNullViolationError`）|
| 補一道 `DELETED = 0` 過濾回來 | ✅ 立刻 `AttributeError`，**不會靜默生效** |

⇒ **model 與 migration 兩半必須一起改**，而守住它們的是**不同層**的測試：
model 那半 unit 擋得住，**migration 那半只有 integration 擋得住**。改這裡時別只跑 unit。

> 第三列是本次重構真正的收穫：欄位不存在時，「順手補一道看似缺少的過濾」會當場炸掉，
> 而不是悄悄多一個恆真條件。這正是 #508 想防的那條路。

⚠️ `DM_DOC_TAG`（`dm/document/models.py`）是**不同的表**，有真正的軟刪除復用機制，
它繼承 `BaseModel` 是對的，不要一起改。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModelNoDelete


class DmCategory(BaseModelNoDelete):
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


class DmFunc(BaseModelNoDelete):
    """關聯作業項目 / func_name（DM_FUNC）。

    系統操作手冊類文件可標記之主系統作業功能代號；受控、不可自由輸入；不刪除只停用。
    """

    __tablename__ = "DM_FUNC"
    __table_args__ = (PrimaryKeyConstraint("FUNC_CODE", name="PK_DM_FUNC"),)

    func_code: Mapped[str] = mapped_column("FUNC_CODE", String(10), nullable=False)
    func_name: Mapped[str] = mapped_column("FUNC_NAME", String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)


class DmTagGroup(BaseModelNoDelete):
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


class DmTag(BaseModelNoDelete):
    """標籤（DM_TAG）。

    受控標籤庫；撰寫者只能挑選不可自由輸入；不刪除只停用。AUDIENCE / UNIT 組之停用採 soft-retire
    （不收回既有可見性）；AUDIENCE 組含通用值「全體」、UNIT 組含「全單位」（文件掛上即不限該維度）。

    **組內名稱唯一**（`UQ_DM_TAG_GROUP_NAME`，#437）：`visibility.audience_pair_match` 以
    `TAG_NAME` 字串辨識兩個通用值，若組內可出現同名標籤，把某個具體單位改名為「全單位」即等於
    讓所有掛該單位的文件對全體閱覽者開放——稽核只會留下一筆「改名」，不會記可見範圍擴大。
    """

    __tablename__ = "DM_TAG"
    __table_args__ = (
        PrimaryKeyConstraint("TAG_ID", name="PK_DM_TAG"),
        UniqueConstraint("TAG_GROUP_CODE", "TAG_NAME", name="UQ_DM_TAG_GROUP_NAME"),
        Index("IX_DM_TAG_GROUP", "TAG_GROUP_CODE"),
    )

    tag_id: Mapped[int] = mapped_column("TAG_ID", BigInteger, Identity(), nullable=False)
    tag_group_code: Mapped[str] = mapped_column(
        "TAG_GROUP_CODE", String(20), ForeignKey("DM_TAG_GROUP.TAG_GROUP_CODE", name="FK_DM_TAG_GROUP"), nullable=False
    )
    tag_name: Mapped[str] = mapped_column("TAG_NAME", String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column("IS_ENABLED", Boolean, nullable=False, default=True)
