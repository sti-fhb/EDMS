"""dm_seed_other_retrieval_tag_group

Revision ID: 3f7b9adcc1ee
Revises: d2a9e4c13b57
Create Date: 2026-10-19 00:31:00.000000

> 本檔原指向 `c3fcddaa575b`（#508）。開 PR 前複查發現 main 已合併 `d2a9e4c13b57`
> （ET stage add version）且同樣以 `c3fcddaa575b` 為 parent——兩支並列會造成 alembic
> 多頭、upgrade 被拒。已 re-point 至 `d2a9e4c13b57`。
> ⚠️ 多頭只在「本分支 + main」合起來才存在，單看任一邊都是單一 head。

新增第四個檢索標籤組 `OTHER`「其他」（#711）。

檢索標籤原本只有三組（`MODULE` 適用模組 / `NATURE` 文件性質 / `LEGAL` 法規關聯）。管理者想
新增的標籤若不屬於這三個面向就無處可放，而標籤組依 #507 的裁示**不開放管理者自建**，只能
由程式新增內建組。

異動說明：
- 影響 Table：`DM_TAG_GROUP`，INSERT 一列；**不預建任何標籤**（由管理者於 DP03 自行新增）
- 四個檢索組地位平等，皆為內建（`IS_BUILTIN=true`）、皆不可刪

## ⚠️ 本檔的 INSERT 不含 `DELETED`，不要照抄舊 seed

`20260806_1108_071cc687bea9` 的 INSERT 帶了 `"DELETED"` 欄位，那在它執行的時點是對的；
但 `c3fcddaa575b`（#508）已把 `DM_TAG_GROUP` 等四張受控表的 `DELETED` 砍掉——那四張表的
政策是「永不刪除、淘汰改停用」，欄位全程為 0 且無任何寫入路徑。本檔排在 #508 之後，
照抄舊體例會因欄位不存在而失敗。

## 🔴 `downgrade()` 刻意不刪這個組

**這不是忘了寫。** 三條理由，前兩條與資料無關、任何時候都成立：

1. **與「永不刪除、淘汰改停用」政策矛盾。** 四張受控表的政策就是不刪（見
   `app/dm/catalog/models.py` 與 #508）。在 migration 裡刪組，等於做一件應用層明文禁止的事。
2. **組連「停用」這條退路都沒有。** `DM_TAG` 有 `IS_ENABLED`（標籤可停用），
   `DM_TAG_GROUP` **沒有**（#507 已指出）。組一旦建立即永久存在——這是接受 #711 時
   就知道並同意的單向門。
3. **組被兩層 FK 引用，刪它會動到業務資料**（⚠️ 正式機有真文件之後才成立）：

   ```
   DM_DOCUMENT ← DM_DOC_TAG → DM_TAG → DM_TAG_GROUP
                 FK_DM_DOC_TAG_TAG    FK_DM_TAG_GROUP
   ```

   要刪組得先刪 `DM_TAG` 的標籤，而標籤又被 `DM_DOC_TAG` 引用——那是文件身上的檢索標籤。

   > 第 3 條目前尚未成立（現有環境皆為測試資料、不進正式機）。若日後有人以「反正資料是
   > 假的」質疑本節，要回到第 1、2 條，**不是放棄不刪組的決定**。
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "3f7b9adcc1ee"
down_revision: Union[str, None] = "d2a9e4c13b57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"
_GROUP_CODE = "OTHER"
_GROUP_NAME = "其他"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            'INSERT INTO "DM_TAG_GROUP" ("TAG_GROUP_CODE", "TAG_GROUP_NAME", "GROUP_TYPE", "IS_BUILTIN", '
            '"CREATED_USER", "CREATED_DATE") '
            "VALUES (:code, :name, 'RETRIEVAL', true, :u, NOW()) "
            'ON CONFLICT ("TAG_GROUP_CODE") DO NOTHING'
        ),
        {"code": _GROUP_CODE, "name": _GROUP_NAME, "u": _SEED_USER},
    )


def downgrade() -> None:
    """刻意不刪 `OTHER` 組——理由見本檔 docstring。⛔ 請勿「修正」成 DELETE。"""
