"""dm_seed_func_from_manuals

Revision ID: 9c83bd25a9b2
Revises: c7d31f08a2be
Create Date: 2026-10-15 16:34:00.000000

關聯作業項目（`DM_FUNC`）改以**兩套系統的操作手冊目錄**為準，共 101 筆。

原本的 51 筆取自血液管理系統的選單種子，與實際交付的手冊有出入（手冊有而選單沒有的
五支沒進來、選單有而手冊沒有的一支多出來）。文件管理系統接下來要收的是**手冊**，
清單自然應該對齊手冊目錄。

異動說明：
- 影響 Table：`DM_FUNC`（UPSERT 101 筆、停用 1 筆），不改 schema
- 血液管理系統 74 筆（BC / BS / CP / DP / LB / MA / MC / TL）維持原代碼
- 文件管理系統 27 筆（DP / DM / ET）一律加 `EDMS-` 前綴

## 為什麼只有一邊加前綴

兩套系統的 DP 有八個代碼撞在一起且**語意交錯**——血液管理的 DP03 是「使用者維護作業」、
文件管理的 DP01 才是「使用者管理」；兩邊都有「操作記錄查詢」但一個是 DP11 一個是 DP05。
光靠名稱分不出來，必須在代碼上區分。

使用者裁示採「無前綴＝主系統」：血液管理是主系統、代碼維持原樣，文件管理（本系統）
加前綴。好處是血液管理那 51 筆代碼不變，**既有文件的 `FUNC_CODE` 引用完全不受影響**。

`EDMS-ET05` 共 9 字元，`FUNC_CODE` 為 `VARCHAR(10)`，尚餘 1 字元。日後若出現三位數
畫面代號（`EDMS-DP100`，10 字元）仍放得下，再長就要擴欄。

## 名稱以畫面為準

清單逐筆取自手冊檔名，**唯一例外是 `EDMS-ET02`**：畫面已更名為「學員學習表現」
（`navItems.ts` 的 `label`），手冊檔名與標題尚未跟上，此處採畫面現名——使用者在
文件管理系統挑作業項目時，看到的要對得上他畫面上的那一頁。

> ⚠️ 手冊側（檔名、`# ` 標題、`_tests` 的作業章節）仍是「學員」，三處一致故
> `check_consistency.py` 不會報。改手冊時這四處要一起對齊。
>
> `EDMS-ET05` 看似也不一致（手冊「課程建立與編輯」vs `label` 「課程建立」）但**不是**：
> 該頁新增模式顯示「課程建立」、編輯模式以 `title` 覆寫為「課程編輯」，手冊一本涵蓋
> 兩個模式，與 `DM08 文件新增與編輯` 同型。

## TL04 停用而非刪除

`TL04 軍人健檢資料匯入` 在選單種子裡有、手冊目錄沒有。依 `DM_FUNC` 的既有設計
「不刪除，淘汰改停用」處理——停用後不可再掛至新文件，已掛的文件不受影響，
也不會踩到 `DM_DOCUMENT.FUNC_CODE` 的外鍵。
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from sqlalchemy import text

from alembic import op

revision: str = "9c83bd25a9b2"
down_revision: Union[str, None] = "c7d31f08a2be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_USER = "SYSTEM"

#: 選單種子有、手冊沒有；停用不刪除（見檔頭）。
_RETIRED = ("TL04",)

#: (FUNC_CODE, FUNC_NAME)——逐筆取自兩套系統 `docs/manuals/{模組}/{代碼}-{名稱}.md` 的檔名。
#: 前 74 筆為血液管理系統（原代碼），後 27 筆為文件管理系統（`EDMS-` 前綴）。
_FUNCS: tuple[tuple[str, str], ...] = (
    ("BC01", "捐血登錄"),
    ("BC02", "健康問卷填寫"),
    ("BC03", "面談體檢"),
    ("BC04", "採血作業"),
    ("BC05", "收血單"),
    ("BC06", "採血報表"),
    ("BC07", "健康問卷查詢"),
    ("BC08", "軍人基本資料匯入"),
    ("BC09", "健康問卷設定"),
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
    ("BS12", "庫存統計表"),
    ("BS13", "用血預估統計表"),
    ("BS14", "儲位維護作業"),
    ("BS15", "安全庫存目標設定"),
    ("CP01", "成分血袋點收作業"),
    ("CP02", "成分聯袋維護"),
    ("CP03", "血品分離作業"),
    ("CP04", "血品核對作業"),
    ("CP05", "血品重量設定"),
    ("CP06", "彙整試管作業"),
    ("CP11", "血品家族碼維護"),
    ("CP12", "血品碼維護"),
    ("CP21", "血品分離組合參數維護"),
    ("CP31", "成分放行作業"),
    ("CP41", "血品瑕疵註記"),
    ("CP42", "血品銷毀／研究判定"),
    ("CP43", "血品狀態查詢"),
    ("CP51", "血品分離狀況統計表"),
    ("DP01", "資訊設備基本資料維護"),
    ("DP03", "使用者維護作業"),
    ("DP04", "功能選單維護"),
    ("DP05", "站點基本資料維護"),
    ("DP06", "角色維護作業"),
    ("DP08", "系統登入頁"),
    ("DP09", "系統參數維護"),
    ("DP10", "系統操作主頁面"),
    ("DP11", "操作記錄查詢"),
    ("DP12", "密碼變更作業"),
    ("DP13", "批次排程維護"),
    ("DP14", "外部系統 API Key 管理作業"),
    ("DP80", "院區編碼維護作業"),
    ("LB01", "標籤服務程式"),
    ("LB02", "歷史標籤查詢及補印作業"),
    ("LB03", "標籤服務程式下載安裝"),
    ("MA01", "管制項目維護"),
    ("MA02", "捐血人管制"),
    ("MA03", "血品回溯"),
    ("MA04", "輸血事件登錄"),
    ("MA05", "待處置血品"),
    ("MA06", "已使用血品追蹤清單"),
    ("MA07", "血品流向追溯查詢"),
    ("MA08", "輸血事件報表"),
    ("MA09", "外部列管名單匯入"),
    ("MC01", "儀表板檢視"),
    ("MC02", "建立畫面"),
    ("MC04", "畫面管理"),
    ("TL01", "手動輸入檢驗結果"),
    ("TL02", "血型攔截複驗"),
    ("TL03", "檢驗查詢"),
    ("TL05", "檢驗接收監控"),
    ("TL06", "檢驗項目設定"),
    ("TL07", "檢驗地點設定"),
    ("EDMS-DP00", "登入後主頁"),
    ("EDMS-DP01", "使用者管理"),
    ("EDMS-DP02", "權限管理"),
    ("EDMS-DP03", "系統參數與清單維護"),
    ("EDMS-DP04", "通知範本維護"),
    ("EDMS-DP05", "操作記錄查詢"),
    ("EDMS-DP06", "排程作業總覽"),
    ("EDMS-DP07", "使用者登入／登出"),
    ("EDMS-DP08", "使用者自助註冊"),
    ("EDMS-DP09", "忘記密碼"),
    ("EDMS-DP10", "個人資料維護"),
    ("EDMS-DM00", "系統儀表板"),
    ("EDMS-DM01", "文件庫"),
    ("EDMS-DM02", "簽核中心"),
    ("EDMS-DM03", "已廢止文件查詢"),
    ("EDMS-DM04", "個人專區"),
    ("EDMS-DM05", "文件變更歷程查詢"),
    ("EDMS-DM06", "閱讀統計 KPI"),
    ("EDMS-DM07", "文件詳細頁"),
    ("EDMS-DM08", "文件新增與編輯"),
    ("EDMS-ET01", "課程列表"),
    # 手冊檔名還是舊的「學員」；以畫面現名為準（見檔頭「名稱以畫面為準」）
    ("EDMS-ET02", "學員學習表現"),
    ("EDMS-ET03", "我的課程"),
    ("EDMS-ET04", "核可查詢"),
    ("EDMS-ET05", "課程建立與編輯"),
    ("EDMS-ET06", "課程學習"),
    ("EDMS-ET07", "線上測驗"),
)

_UPSERT = text(
    'INSERT INTO "DM_FUNC" ("FUNC_CODE", "FUNC_NAME", "IS_ENABLED", "CREATED_USER", "CREATED_DATE", "DELETED") '
    "VALUES (:code, :name, true, :u, :d, 0) "
    'ON CONFLICT ("FUNC_CODE") DO UPDATE SET "FUNC_NAME" = EXCLUDED."FUNC_NAME", '
    '"UPDATED_USER" = EXCLUDED."CREATED_USER", "UPDATED_DATE" = EXCLUDED."CREATED_DATE", "DELETED" = 0'
)

_SET_ENABLED = text(
    'UPDATE "DM_FUNC" SET "IS_ENABLED" = :enabled, "UPDATED_USER" = :u, "UPDATED_DATE" = :d WHERE "FUNC_CODE" = :code'
)


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    for code, name in _FUNCS:
        conn.execute(_UPSERT.bindparams(code=code, name=name, u=_SEED_USER, d=now))

    # UPSERT 不含 IS_ENABLED（避免把管理者停用過的項目復活），淘汰者另外逐筆停用
    for code in _RETIRED:
        conn.execute(_SET_ENABLED.bindparams(enabled=False, code=code, u=_SEED_USER, d=now))


def downgrade() -> None:
    """只還原 `TL04` 的啟用狀態。

    **不移除本次新增的作業項目**——它們可能已被文件以 `DM_DOCUMENT.FUNC_CODE` 引用
    （外鍵），刪除會失敗；而多出幾個可選項不會讓任何既有文件變得不正確。
    `CP42` 的名稱亦不還原：那是把半形斜線改成手冊上的全形，改回去只是把錯字放回來。
    """
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    for code in _RETIRED:
        conn.execute(_SET_ENABLED.bindparams(enabled=True, code=code, u=_SEED_USER, d=now))
