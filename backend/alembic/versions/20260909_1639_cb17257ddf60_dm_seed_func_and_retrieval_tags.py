"""dm_seed_func_and_retrieval_tags

Revision ID: cb17257ddf60
Revises: 7b24b5dea3ad
Create Date: 2026-09-09 16:39:00.000000

補種 DM 作業項目與三組檢索標籤。

`071cc687bea9`（DM 業務種子）只種了分類、4 個標籤組與 AUDIENCE 組的 5 個可見對象，
`DM_FUNC` 與檢索組（MODULE / NATURE / LEGAL）的標籤內容從未有 seed——正式環境實測
`GET /api/dm/editor/options` 回 `funcs: 0`、`retrieval_tags: 0`，「系統操作手冊」類文件
選不到關聯作業項目、文件庫也沒有檢索標籤可選。

異動說明：
- 影響 Table：`DM_FUNC`（51 筆）、`DM_TAG`（9 筆，掛既有 MODULE / NATURE / LEGAL 三組）
- 不做任何 DDL，純資料 seed

`DM_FUNC` 代碼與名稱取自**主系統 TBMS 的選單種子**（`DP_MENU` 之 `MENU_ID` / `MENU_NAME`），
非自行命名——本欄語意即「對應主系統作業功能代號」（見 dm/data-model.md DM_FUNC）。
僅收錄主系統選單實際存在者；只出現在需求文件而未進選單的代碼（BS12 / CP05 / CP51 /
MA07）與帶 DELETED 標記的 BC09 皆不種。

冪等：
- `DM_FUNC` 以 PK `FUNC_CODE` 衝突時 `DO UPDATE SET "FUNC_NAME"`——既有列若名稱與主系統
  不符會被更正（部署前手動建的資料有數筆名稱對不上，如 BS05 曾寫「用血回報」、
  MA01 曾寫「安全檢核」）。停用狀態 `IS_ENABLED` 不動，尊重管理者於後台的啟停。
- `DM_TAG` 無 (TAG_GROUP_CODE, TAG_NAME) 唯一約束，改以 `WHERE NOT EXISTS` 判重
  （比照 `071cc687bea9` 之標籤寫法）。
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "cb17257ddf60"
down_revision: Union[str, None] = "7b24b5dea3ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

# (FUNC_CODE, FUNC_NAME)——採血 BC / 血液庫存 BS / 成分製備 CP / 輸血檢驗 TL / 維護管理 MA
_FUNCS: tuple[tuple[str, str], ...] = (
    ("BC01", "捐血登錄"),
    ("BC02", "健康問卷填寫"),
    ("BC03", "面談體檢"),
    ("BC04", "採血作業"),
    ("BC05", "收血單"),
    ("BC06", "採血報表"),
    ("BC07", "健康問卷查詢"),
    ("BC08", "軍人基本資料匯入"),
    ("BC10", "捐血人查詢"),
    ("BC11", "邀約管理"),
    ("BS01", "入庫作業"),
    ("BS02", "訂血作業"),
    ("BS03", "出庫作業"),
    ("BS04", "領血確認"),
    ("BS05", "用血登記"),
    ("BS06", "血品退回"),
    ("BS07", "退血處理"),
    ("BS08", "回溯通知"),
    ("BS09", "銷毀作業"),
    ("BS10", "血庫盤點"),
    ("BS11", "庫存查詢"),
    ("BS13", "用血預估統計表"),
    ("BS14", "儲位維護作業"),
    ("BS15", "安全庫存目標設定"),
    ("CP01", "成分血袋點收作業"),
    ("CP02", "成分聯袋維護"),
    ("CP03", "血品分離作業"),
    ("CP04", "血品核對作業"),
    ("CP06", "彙整試管作業"),
    ("CP11", "血品家族碼維護"),
    ("CP12", "血品碼維護"),
    ("CP21", "血品分離組合參數維護"),
    ("CP31", "成分放行作業"),
    ("CP41", "血品瑕疵註記"),
    ("CP42", "血品銷毀/研究判定"),
    ("CP43", "血品狀態查詢"),
    ("TL01", "手動輸入檢驗結果"),
    ("TL02", "血型攔截複驗"),
    ("TL03", "檢驗查詢"),
    ("TL04", "軍人健檢資料匯入"),
    ("TL05", "檢驗接收監控"),
    ("TL06", "檢驗項目設定"),
    ("TL07", "檢驗地點設定"),
    ("MA01", "管制項目維護"),
    ("MA02", "捐血人管制"),
    ("MA03", "血品回溯"),
    ("MA04", "輸血事件登錄"),
    ("MA05", "待處置血品"),
    ("MA06", "已使用血品追蹤清單"),
    ("MA08", "輸血事件報表"),
    ("MA09", "外部列管名單匯入"),
)

# (TAG_GROUP_CODE, TAG_NAME)——三組皆為檢索組（RETRIEVAL），AUDIENCE 組已由 071cc687bea9 種入。
# MODULE 五值對應主系統五模組（採血 BC / 供應 BS / 成份 CP / 檢驗 TL / 醫務 MA）。
_TAGS: tuple[tuple[str, str], ...] = (
    ("MODULE", "採血"),
    ("MODULE", "供應"),
    ("MODULE", "成份"),
    ("MODULE", "檢驗"),
    ("MODULE", "醫務"),
    ("NATURE", "平時"),
    ("NATURE", "緊急"),
    ("NATURE", "戰時"),
    ("LEGAL", "衛福部"),
)

_UPSERT_FUNC = text(
    'INSERT INTO "DM_FUNC" ("FUNC_CODE", "FUNC_NAME", "IS_ENABLED", "CREATED_USER", "CREATED_DATE", "DELETED") '
    "VALUES (:code, :name, true, :u, :d, 0) "
    'ON CONFLICT ("FUNC_CODE") DO UPDATE SET "FUNC_NAME" = EXCLUDED."FUNC_NAME", '
    '"UPDATED_USER" = EXCLUDED."CREATED_USER", "UPDATED_DATE" = EXCLUDED."CREATED_DATE", "DELETED" = 0'
)

# 同一參數不可同時出現在 VALUES 與 WHERE 比較位置——asyncpg 無法推導一致型別會拋
# AmbiguousParameterError，故拆為 *_val / *_chk 兩個綁定名（比照 d5f9a2b8e614）。
_INSERT_TAG = text(
    'INSERT INTO "DM_TAG" ("TAG_GROUP_CODE", "TAG_NAME", "IS_ENABLED", "CREATED_USER", "CREATED_DATE", "DELETED") '
    "SELECT :grp_val, :name_val, true, :u, :d, 0 "
    'WHERE NOT EXISTS (SELECT 1 FROM "DM_TAG" '
    'WHERE "TAG_GROUP_CODE" = :grp_chk AND "TAG_NAME" = :name_chk)'
)


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for code, name in _FUNCS:
        conn.execute(_UPSERT_FUNC, {"code": code, "name": name, "u": _SEED_USER, "d": now})

    for group, name in _TAGS:
        conn.execute(
            _INSERT_TAG,
            {"grp_val": group, "name_val": name, "grp_chk": group, "name_chk": name, "u": _SEED_USER, "d": now},
        )


def downgrade() -> None:
    """移除本 migration 所種之作業項目與檢索標籤。

    只刪 `CREATED_USER = 'SYSTEM'` 者——部署前手動建立（`CREATED_USER='manual'`）或管理者
    於後台新增的列不受影響。已被文件引用的標籤會因 `DM_DOC_TAG` 外鍵而擋下刪除，
    此時應改以後台「停用」淘汰，而非降版。
    """
    conn = op.get_bind()
    conn.execute(
        text('DELETE FROM "DM_FUNC" WHERE "FUNC_CODE" = ANY(:codes) AND "CREATED_USER" = :u'),
        {"codes": [code for code, _ in _FUNCS], "u": _SEED_USER},
    )
    for group, name in _TAGS:
        conn.execute(
            text('DELETE FROM "DM_TAG" WHERE "TAG_GROUP_CODE" = :grp AND "TAG_NAME" = :name AND "CREATED_USER" = :u'),
            {"grp": group, "name": name, "u": _SEED_USER},
        )
