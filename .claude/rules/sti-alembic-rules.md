---
description: >
  Alembic migration 撰寫規範。
  凡涉及建立新 migration、修改現有 migration、執行 alembic 指令、
  或討論 DB schema 變更時，主動載入此規則。
paths:
  - "backend/alembic/versions/*.py"
---

# Alembic Migration 規範

## 建立前必做：head 檢查

建立新 migration **之前**，先確認目前只有一個 head：

```bash
cd backend && python3 - <<'EOF'
import os, re
d = 'alembic/versions'
revs = {}
for f in os.listdir(d):
    if not f.endswith('.py'):
        continue
    txt = open(f'{d}/{f}').read()
    r  = re.search(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', txt, re.M)
    dn = re.search(r'^down_revision(?::\s*[^=]+)?\s*=\s*(.+)', txt, re.M)
    if r:
        revs[r.group(1)] = dn.group(1).strip() if dn else 'None'
referenced = set()
for v in revs.values():
    for x in re.findall(r'["\']([^"\']+)["\']', v):
        referenced.add(x)
heads = [r for r in revs if r not in referenced]
print(f'Heads ({len(heads)}):', heads)
EOF
```

- **1 個 head** → 可繼續
- **多個 head** → 停止，告知使用者需先執行 `/sti-alembic-check` 處理後再繼續

---

## 命名規則

```bash
cd backend && alembic revision --autogenerate -m "{scope}_{description}"
```

**scope 規則**（由窄到寬，擇最適合者）：

| scope | 格式範例 | 適用情況 |
|-------|----------|----------|
| 功能代碼 | `dp03`、`bc01` | 僅影響特定功能畫面 |
| 模組 | `dp`、`bc`、`cp` | 影響整個模組，無特定功能 |
| 跨模組 | `common` | 同時影響多個模組 |

**description** 使用 snake_case 英文，簡短描述異動內容。

**禁止使用 `--rev-id` 手動指定 revision ID**，讓 Alembic 自動產生 hex ID（如 `35b63bd432e4`）以確保唯一性：

```bash
# ✅ 正確：revision ID 由 Alembic 自動產生
alembic revision --autogenerate -m "dp03_add_user_phone"
# 產生：35b63bd432e4_dp03_add_user_phone.py

# ❌ 禁止：手動指定 --rev-id 會產生非唯一的自訂編號（如 g001、e001）
alembic revision --autogenerate -m "dp03_add_user_phone" --rev-id g001
```

```bash
# 範例
alembic revision --autogenerate -m "dp03_add_user_phone"
alembic revision --autogenerate -m "dp_init_schedule_tables"
alembic revision --autogenerate -m "common_add_audit_log_index"
```

---

## Autogenerate 確認清單

autogenerate 產生後，**必須人工逐項確認**：

### ⚠️ RENAME COLUMN 陷阱

autogenerate 無法偵測欄位 rename，會誤判為「DROP 舊欄位 + ADD 新欄位」，導致**資料遺失**。
凡 Model 有 rename，手動修正 upgrade()：

```python
# ❌ autogenerate 誤判（資料會遺失）
op.drop_column("DP_USER", "TEL")
op.add_column("DP_USER", sa.Column("PHONE", sa.String(20)))

# ✅ 正確寫法
op.alter_column("DP_USER", "TEL", new_column_name="PHONE")
```

### downgrade() 是否合理

若 downgrade 不安全或無意義，留空並加註原因：

```python
def downgrade() -> None:
    # 含資料操作，downgrade 不安全，不實作
    pass
```

---

## DDL 操作：新舊 DB 相容性

autogenerate 只看 Model 與 DB 的結構差異，不考慮既有資料。以下情況需手動修正產生的 migration。

### ADD NOT NULL column（最常見的地雷）

autogenerate 只產生 `nullable=False`，舊 DB 有資料時會直接報錯。**分三步驟處理**：

```python
def upgrade() -> None:
    # Step 1：先加 nullable 欄位
    op.add_column("DP_USER", sa.Column("PHONE", sa.String(20), nullable=True))
    # Step 2：回填舊資料（依業務決定預設值）
    op.execute("UPDATE DP_USER SET PHONE = '' WHERE PHONE IS NULL")
    # Step 3：再加 NOT NULL constraint
    op.alter_column("DP_USER", "PHONE", nullable=False)
```

### 縮小欄位長度

autogenerate 不會警告長度縮小。執行前必須確認現有資料不超過新長度，
並在 docstring 說明「已確認現有資料最長 N 碼」。

### 不相容型別轉換（如 VARCHAR → INTEGER）

```python
op.alter_column("DP_SCHEDULE", "RETRY_COUNT",
    type_=sa.Integer(),
    postgresql_using="RETRY_COUNT::integer"
)
```

### ADD UNIQUE constraint

先確認無重複資料再 apply，或於同一 migration 先清理重複資料。

---

## 大表索引與約束

> **判斷標準**：Table 資料量 > 10 萬筆時，使用本節的寫法以避免鎖表。
>
> **索引命名慣例**：一般索引使用 `IX_{MODULE}_{TABLE}_{欄位}` 前綴；唯一索引使用 `UQ_` 前綴（與 CONSTRAINT 命名一致）。

### CREATE INDEX CONCURRENTLY

PostgreSQL 的 `CONCURRENTLY` **不能在 transaction 內執行**。Alembic 預設將 migration 包在 transaction 裡，直接寫會報：

```
ERROR: CREATE INDEX CONCURRENTLY cannot run inside a transaction block
```

**必須搭配 `autocommit_block()` 讓該段在 transaction 外執行**：

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "IX_DP_AUDIT_LOG_CREATED_DATE ON DP_AUDIT_LOG (CREATED_DATE)"
        )

def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS IX_DP_AUDIT_LOG_CREATED_DATE")
```

> ⚠️ `autocommit_block()` 內的每條 DDL 會**獨立 commit，沒有 transaction 回滾保護**。請只放需要 `CONCURRENTLY` 的指令；其他一般 DDL（如 `op.add_column`）寫在區塊**外**，避免前一條成功、後一條失敗時資料庫留在半成品狀態。
>
> ⚠️ `CREATE INDEX CONCURRENTLY` 失敗時 PostgreSQL 會留下 **INVALID 狀態的索引**，`IF NOT EXISTS` 會誤判為「已存在」而跳過，導致實際上沒有可用索引。重跑 migration 前請先確認：`SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '{TABLE}' AND indexname = '{INDEX}'`，若狀態為 INVALID，需先 `DROP INDEX {INDEX}` 再重跑。

**同一支 migration 同時需要加欄位 + 建索引時**，務必分開放置：

```python
def upgrade() -> None:
    # 一般 DDL 寫在 autocommit_block 外，享有 transaction 回滾保護
    op.add_column("DP_AUDIT_LOG", sa.Column("EVENT_TYPE", sa.String(20), nullable=True))

    # CONCURRENTLY 單獨放進 autocommit_block
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "IX_DP_AUDIT_LOG_EVENT_TYPE ON DP_AUDIT_LOG (EVENT_TYPE)"
        )
```

### ADD UNIQUE（兩階段）

直接下 `ADD CONSTRAINT UNIQUE` 在大表會長時間鎖表。正確做法是先建索引再附加 constraint，`ADD CONSTRAINT` 這步幾乎是秒級完成：

```python
def upgrade() -> None:
    # Step 1：建立唯一索引（不鎖表，可在線完成）
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "UQ_DP_USER_EMAIL ON DP_USER (EMAIL)"
        )
    # Step 2：附加 constraint（利用已建好的索引，幾乎瞬間完成）
    op.execute(
        "ALTER TABLE DP_USER "
        "ADD CONSTRAINT UQ_DP_USER_EMAIL UNIQUE USING INDEX UQ_DP_USER_EMAIL"
    )

def downgrade() -> None:
    op.execute("ALTER TABLE DP_USER DROP CONSTRAINT IF EXISTS UQ_DP_USER_EMAIL")
    # 索引會隨 constraint 一併移除，不需額外 DROP INDEX
```

> ⚠️ Step 2 的 `ADD CONSTRAINT` 不要放進 `autocommit_block()`，留在 migration 主 transaction 內執行——這樣萬一 constraint 驗證失敗（例如 Step 1 完成後又寫入重複資料）可以隨 migration 回滾；也避免與 Step 1 的 CONCURRENTLY 操作混在同一個 autocommit 區塊造成半成品狀態。

---

## Seed Data 安全寫法

autogenerate 不產生資料操作，seed 需手動寫入 upgrade()。

**禁止直接 INSERT**（新 DB 可跑，舊 DB 有資料時會 duplicate key 錯誤）：

```python
# ❌ 禁止
op.execute("INSERT INTO DP_MENU (MENU_ID, ...) VALUES ('DP03', ...)")
```

**依資料性質選擇寫法**：

```python
# ✅ 開發期資料（選單、角色、ref code）→ 先刪後 INSERT，允許重建
# ⚠️ DELETE 必須附明確 WHERE 條件，禁止 DELETE FROM {TABLE} 無 WHERE（會清空整張表）
op.execute("DELETE FROM DP_MENU WHERE MENU_ID = 'DP03'")
op.execute("INSERT INTO DP_MENU (MENU_ID, MENU_NAME, ...) VALUES ('DP03', '使用者管理', ...)")

# ✅ 生產必保留資料 → ON CONFLICT DO UPDATE，不刪除現有資料
op.execute("""
    INSERT INTO DP_MENU (MENU_ID, MENU_NAME, SORT_ORDER)
    VALUES ('DP03', '使用者管理', 3)
    ON CONFLICT (MENU_ID) DO UPDATE
    SET MENU_NAME = EXCLUDED.MENU_NAME,
        SORT_ORDER = EXCLUDED.SORT_ORDER
""")
```

**若 seed 值來自外部來源（設定檔、CSV、環境變數），必須使用參數化查詢，禁止用 f-string 或字串拼接**：

```python
from sqlalchemy import text

# ✅ 參數化寫法（防止 SQL Injection）
op.execute(
    text("INSERT INTO DP_MENU (MENU_ID, MENU_NAME) VALUES (:id, :name)")
    .bindparams(id=menu_id, name=menu_name)
)

# ❌ 禁止（若 menu_id 來自外部來源，此寫法有 SQL Injection 風險）
op.execute(f"INSERT INTO DP_MENU (MENU_ID) VALUES ('{menu_id}')")
```

---

## Docstring 規範

每個 migration 的 module docstring 必須包含：

```python
"""dp03_add_user_phone

Revision ID: cfdaf2082784
Revises: b3018e58f1d2
Create Date: 2026-04-15

新增 DP_USER.PHONE 欄位，儲存使用者聯絡電話。  ← 簡述行（必填）

異動說明：
- 影響 Table：DP_USER
- PHONE 欄位：VARCHAR(20)，NOT NULL
- 舊有資料回填空字串後設 NOT NULL（見 Step 2）
"""
```

### 結構定義

| 區段 | 位置 | 說明 |
|------|------|------|
| slug | 第 1 行 | autogenerate 自動產生，與 `-m` 參數相同 |
| metadata | 第 3–5 行 | `Revision ID` / `Revises` / `Create Date`（autogenerate 自動產生） |
| **簡述行** | **Create Date 之後，空一行的第一個非空白行** | **繁體中文，一句話概述本次異動（≤ 30 字）** |
| 詳細說明 | 簡述行之後 | 影響 Table、欄位規格、非標準處理說明（選填） |

### 簡述行規則

- **位置固定**：`Create Date:` 行之後，空一行，緊接的第一行
- **語言**：繁體中文
- **長度**：≤ 30 字（`/sti-alembic-log` 會截斷超過部分）
- **內容**：一句話說明「做了什麼」，不重複 slug 的英文描述

### 必填項目

- 簡述行（繁體中文，≤ 30 字）
- 影響哪些 Table
- 若有非標準處理（分步驟、手動修正 autogenerate），說明原因

---

## 不撰寫 migration 一次性驗收測試

不撰寫驗證特定 revision apply 後結果的一次性測試（例如：某 column 是 NOT NULL、某 seed 已存在、某型別已轉成 timestamptz）。Schema 與 seed 變更應由對應模組的 service / API integration test 間接覆蓋。
