執行以下步驟，引導完成從「了解需求 → 建立分支 → 確認環境 → 安裝依賴 → 查閱文件（條件式）→ 規劃實作 → TDD → Code Review → Security Review → 本地 CI（可跳過）→ Commit & PR」的完整開發流程。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如自訂分支名、修改 commit message） |
| `0` / `取消` | 停止並顯示「已取消。」 |

**顯示格式**：每個選項各佔一行，以 `1.`、`2.` 開頭：
```
  1. 選項 A
  2. 選項 B
```

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要實作的 Issue 編號（必填）| `/sti-implement #25` |
| `worktree` | 使用 Worktree 隔離模式（選填）| `/sti-implement #25 worktree` |
| `branch` | 使用一般分支模式（選填）| `/sti-implement #25 branch` |

## 環境說明

- 使用者與 Claude 皆使用 **bash** 終端機
- 所有指令一律使用 **bash 語法**
- 嚴禁直接修改 `main` 分支，所有開發在 feature 分支進行
- **Worktree 路徑規則**（worktree 模式）：`../worktrees/{slug}`，slug = 分支名稱中 `/` 替換為 `-`
- **WORKTREE 絕對路徑**（worktree 模式）：步驟 2 由 `pwd` 輸出，Claude 必須記住此值並在後續所有步驟以實際路徑替換 `{WORKTREE}`，不可使用變數

## Issue 格式引用

若流程中需要建立 Issue（如補建遺漏的 Issue），必須依照 `/sti-issue-create` 的「Issue 內容模板」格式。

---

## 執行步驟

### 步驟 1：讀取 Issue

從 `$ARGUMENTS` 解析 Issue 編號（去除 `#` 符號）。
若未傳入編號，提示使用者：「請提供 Issue 編號，例如：/sti-implement #25」，並停止執行。

使用 Bash 工具執行（**同時讀 body 與留言**，留言裡可能有 `/sti-plan` 規劃藍圖與 SA 裁示）：
```bash
gh issue view {編號} --json number,title,body,assignees,labels
gh issue view {編號} --comments
```

整理並顯示以下資訊：
- Issue 編號與標題
- 任務說明（body 中的「## 任務說明」區塊）
- 範圍（body 中的「## 範圍」區塊）
- 驗收條件（body 中的「## 驗收條件」區塊）
- 注意事項（body 中的「## 注意事項」區塊，若有）

**留言盤點（不可跳過）**：掃描留言，依標記辨識 `/sti-plan` 的產出——

- **規劃留言**：含標記 `<!-- sti-plan:planning -->` 的留言（若有多則，取最新一則）。找到 → 記為 **PLAN_COMMENT**，作為步驟 7 規劃實作的底稿。
- **SA Q 留言**：含標記 `<!-- sti-plan:sa-questions -->` 的留言。找到 → 比對其後是否有 SA 的回覆留言：
  - SA 已回覆 → 把每題裁示摘要出來，列入實作依據。
  - SA 尚未回覆 → 顯示一行提示後**照常繼續，不阻斷**（是否該等 SA 由使用者人工判斷）：
    ```
    ⚠️ 偵測到 N 條 SA Q 尚未回覆，請確認是否該等 SA 回覆再開工。
    ```
- **找不到任何 `/sti-plan` 標記**（小 Issue 未先跑 `/sti-plan`）→ 屬正常情況，顯示「無規劃留言，將依 body + spec 直接規劃」，照原流程繼續。

---

### 步驟 2：建立開發分支

將 Issue 標題轉換為分支名稱：
- 移除方括號標記（如 `[Foundation]`、`[Phase 1]`）
- 轉為全小寫，空白與特殊字元替換為連字號 `-`
- 移除連續連字號與首尾連字號
- 格式：`feature/{簡化後標題}`

顯示建議分支名稱，詢問使用者：
```
分支名稱：feature/{建議名稱}
  1. 使用此名稱
  2. 自訂（直接輸入名稱，不含 feature/ 前綴）
```

分支名稱確認後，判斷開發模式：
- 若 `$ARGUMENTS` 含 `worktree` → **Worktree 模式**
- 若 `$ARGUMENTS` 含 `branch` → **Branch 模式**
- 若兩者皆無 → 詢問使用者：
  ```
  請選擇開發模式：
    1. worktree（隔離目錄，適合同時處理多個功能）
    2. branch（一般分支，輕量簡單）
  ```
  - 輸入 `1` 或 `worktree` → Worktree 模式
  - 輸入 `2` 或 `branch` → Branch 模式

⚠️ **Claude 必須記住本步驟選擇的 MODE（worktree 或 branch），後續所有步驟依此決定路徑與指令格式。**

**Worktree 模式**（`{slug}` = 分支名稱中 `/` 替換為 `-`）：
```bash
git fetch origin main
mkdir -p ../worktrees
git worktree add ../worktrees/{slug} -b {分支名稱} origin/main
cd ../worktrees/{slug} && pwd
```
Claude 必須記住 `pwd` 輸出值作為 WORKTREE 絕對路徑。
提示使用者：`cd ../worktrees/{slug}`
顯示：「✅ 已建立 Worktree：{WORKTREE}，分支：{分支名稱}」

**Branch 模式**：
```bash
git fetch origin main
git checkout -b {分支名稱} origin/main
```
顯示：「✅ 已切換到分支：{分支名稱}」

---

### 步驟 2.5：Worktree 隔離 Test DB（僅 worktree 模式）

⚠️ **僅在 Worktree 模式執行；Branch 模式跳過本步驟。**

**目的**：避免多個 worktree 並行跑 integration test 時，`apply_migrations` fixture 互相 DROP SCHEMA 造成測試假性失敗。每個 worktree 配發獨立的 test DB（`test_edms_{DB_SLUG}`），對應的 `backend/.env.test` 改寫指向自己的 DB。

#### 2.5a 推導 DB 名稱

依分支名稱推導 `DB_SLUG` 與 `TEST_DB_NAME`：
- 從分支名稱（如 `feature/sti-implement-worktree-test-db-isolation`）出發
- `DB_SLUG` = 將 `/` → `_`、`-` → `_`，截斷至 44 字元
- `TEST_DB_NAME` = `test_edms_{DB_SLUG}`

PostgreSQL 識別字限長 63 字元，`test_edms_` 前綴佔 10 字元；並行測試時 pytest-xdist 還會在分支庫名後再加 `_gwNN`（最多 5 字元，見 `backend/tests/conftest.py`），故 `DB_SLUG` 限 44 字元，確保 `test_edms_{DB_SLUG}_gwNN` 不超過 63。

範例 bash 指令（Claude 在腦中執行同等邏輯）：
```bash
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
DB_SLUG=$(echo "$BRANCH_NAME" | tr '/-' '__' | cut -c1-44)
# 安全防呆：DB_SLUG 僅允許 [a-z0-9_]，防止 SQL 識別字 injection
if ! [[ "$DB_SLUG" =~ ^[a-z0-9_]+$ ]]; then
  echo "❌ DB_SLUG 含不合法字元：'$DB_SLUG'。分支名稱僅允許 [a-z0-9/-]。"
  exit 1
fi
TEST_DB_NAME="test_edms_${DB_SLUG}"
```

⚠️ **Claude 必須記住此 `TEST_DB_NAME` 值，供同 session 內的 `/sti-cleanup` 使用。**
> 若 `/sti-cleanup` 在不同 session 執行（記憶不保留），步驟 4a 會依分支名稱重新推導，結果相同，無需擔心。

#### 2.5b 複製 .env 到 worktree（依現有 SOP，只在 worktree 缺檔時複製）

從主 repo 複製三份 .env：worktree 已有對應檔則跳過（保留使用者本地修改），主 repo 缺源檔則提示：
```bash
for f in backend/.env backend/.env.test frontend/.env; do
  if [ -f "{WORKTREE}/$f" ]; then
    echo "✓ {WORKTREE}/$f 已存在，跳過複製"
  elif [ -f "{主 repo 絕對路徑}/$f" ]; then
    cp "{主 repo 絕對路徑}/$f" "{WORKTREE}/$f"
    echo "✓ copied $f"
  else
    echo "⚠ missing $f：請從 .env.example 建立主 repo 的 $f 後重跑此步驟"
  fi
done
```

#### 2.5c 改寫 worktree 的 backend/.env.test 中 DATABASE_URL

把 `DATABASE_URL` 路徑段 `/test_edms` 替換為 `/{TEST_DB_NAME}`，使用 Python 精準匹配（避免 sed 對特殊字元的轉義問題）。

> **前提**：此步驟假設主 repo 的 `backend/.env.test` 中 `DATABASE_URL` 末段永遠是 `test_edms`（即從未被此步驟改寫過）。步驟 2.5b 複製的是主 repo 的原始檔，故此假設通常成立。若 `DATABASE_URL` 已是其他值，Python 腳本會顯示 `❌ 未找到` 錯誤，此時請手動確認 `.env.test` 內容。

```bash
python3 -c "
import re, sys
path = sys.argv[1]
new_db = sys.argv[2]
with open(path) as f: content = f.read()
# 先檢查是否已是目標值（idempotent，重跑不報錯）
if re.search(rf'DATABASE_URL=[^\n]+/{re.escape(new_db)}\b', content):
    print(f'✓ DATABASE_URL 已是 /{new_db}（跳過改寫）')
    sys.exit(0)
content, n = re.subn(r'(DATABASE_URL=[^\n]+/)test_edms\b', rf'\1{new_db}', content)
if n == 0:
    sys.exit('❌ 未在 .env.test 找到 DATABASE_URL=...test_edms 樣式，請手動確認')
with open(path, 'w') as f: f.write(content)
print(f'✓ DATABASE_URL → /{new_db}')
" "{WORKTREE}/backend/.env.test" "{TEST_DB_NAME}"
```

#### 2.5d 在 PostgreSQL 建立隔離 test DB（idempotent）

從改寫後的 `.env.test` 解析連線資訊後建立 DB（已存在則跳過）。

> **佔位符說明**：程式碼中 `{WORKTREE}` 和 `{TEST_DB_NAME}` 是 Claude 執行前代入實際值的模板；`$DB_PASS`、`$DB_HOST` 等是 shell 執行期的環境變數，由 `eval` 展開。

```bash
eval "$(python3 -c "
import re, shlex, sys
from urllib.parse import urlparse
url = None
with open('{WORKTREE}/backend/.env.test') as f:
    for line in f:
        m = re.match(r'^\s*DATABASE_URL=(.*)$', line.rstrip('\n'))
        if m:
            url = m.group(1).strip().strip('\"').strip(\"'\")
            break
if not url: sys.exit('❌ 找不到 DATABASE_URL')
p = urlparse(url)
print(f'DB_USER={shlex.quote(p.username or \"\")}')
print(f'DB_PASS={shlex.quote(str(p.password or \"\"))}')
print(f'DB_HOST={shlex.quote(p.hostname or \"localhost\")}')
print(f'DB_PORT={p.port or 5432}')
")"

if PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc \
   "SELECT 1 FROM pg_database WHERE datname='{TEST_DB_NAME}'" 2>/dev/null | grep -q 1; then
  echo "✓ DB 已存在：{TEST_DB_NAME}（跳過建立）"
else
  PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c \
    "CREATE DATABASE \"{TEST_DB_NAME}\"" \
    && echo "✓ 已建立：{TEST_DB_NAME}" \
    || { echo "❌ 建立 DB 失敗，可能是權限不足。請執行：ALTER USER $DB_USER CREATEDB;"; exit 1; }
fi
```

> ⚠️ **權限要求**：執行帳號需有 `CREATEDB` 或 superuser 權限。若失敗，請使用者用 superuser 執行：
> ```sql
> ALTER USER <username> CREATEDB;
> ```

#### 2.5e 顯示結果

```
✅ 隔離測試 DB：{TEST_DB_NAME}
   .env.test 位置：{WORKTREE}/backend/.env.test
   清理時機：PR 合併後執行 /sti-cleanup #{Issue 編號} 會自動 DROP 此 DB
```

---

### 步驟 3：確認環境

根據 Issue 範圍判斷任務類型：

**前端任務**：
```bash
node --version
```
- Worktree 模式：讀取 `{WORKTREE}/frontend/package.json`
- Branch 模式：讀取 `frontend/package.json`

**後端任務**：
```bash
python --version && uv --version
```
- Worktree 模式：讀取 `{WORKTREE}/backend/pyproject.toml`
- Branch 模式：讀取 `backend/pyproject.toml`

**全端任務**：以上兩者皆執行。

若環境正常，快速顯示版本資訊後繼續，不需等待確認。

---

### 步驟 4：安裝依賴

顯示對應的安裝指令供使用者參考，並詢問：
```
  1. 自動安裝
  2. 已手動安裝
  3. 有問題（請說明）
```

**前端任務**：
- Worktree 模式：`cd ../worktrees/{slug}/frontend && pnpm install`
- Branch 模式：`cd frontend && pnpm install`

**後端任務**：
- Worktree 模式：`cd ../worktrees/{slug}/backend && uv sync`
- Branch 模式：`cd backend && uv sync`

**全端任務**：兩者皆執行。

- 選擇 **1**（自動安裝）→ Claude 使用 Bash 工具直接執行上述對應的安裝指令，完成後自動繼續
- 選擇 **2**（已手動安裝）→ 直接繼續
- 選擇 **3** → 使用者說明問題後協助排除

安裝完成後，確認測試框架是否就緒：

- **後端**：確認 `pyproject.toml` 是否含 `pytest`、`pytest-asyncio`、`httpx`。若無：
  - Worktree 模式：`cd ../worktrees/{slug}/backend && uv add --dev pytest pytest-asyncio httpx`
  - Branch 模式：`cd backend && uv add --dev pytest pytest-asyncio httpx`
- **前端**：確認 `package.json` 是否含 `vitest`、`@testing-library/react`。若無：
  - Worktree 模式：`cd ../worktrees/{slug}/frontend && pnpm add -D vitest @testing-library/react @testing-library/user-event jsdom`
  - Branch 模式：`cd frontend && pnpm add -D vitest @testing-library/react @testing-library/user-event jsdom`

若測試框架已存在，快速確認後繼續，不需等待。

---

### 步驟 5：查閱文件（Context7，條件式）

**預設略過此步驟。** 多數任務照抄專案既有範式即可（`usePagedQuery`、
`CrudPageLayout`、`paginate()`、`AppError`、分層架構等）——這些慣例
Context7 查不到，讀既有程式碼與 `.claude/rules/` 才準。

**只有命中以下任一條件時，才查 Context7：**

- 用到較新或變動大的 API，且專案內找不到可照抄的範例
  （如 React 19 新 hook、MUI 7 改版元件、SQLAlchemy 2 新式 query、
  Alembic 新語法）
- 引入專案尚未使用過的套件或整合模式
- 懷疑某寫法已過時（deprecated API、import 路徑改變）

命中時，使用 `mcp__claude_ai_Context7__resolve-library-id` 與
`mcp__claude_ai_Context7__query-docs` 查相關套件最新 API，
將關鍵寫法記錄下來供步驟 7 使用。

| 情境 | 查詢套件 |
|------|----------|
| 前端 UI | React 19、MUI 7、Ant Design 5（遷移中） |
| 前端路由 | React Router v7 |
| 後端 API | FastAPI 0.115+ |
| 資料庫 ORM | SQLAlchemy 2、Alembic |

未命中則直接進入步驟 6，不需詢問使用者。

---

### 步驟 6：補讀 data-model

從步驟 1 Issue body 中的 spec 路徑抽出模組代碼（如 `docs/specs/bc/...` → `bc`），讀 `docs/specs/{模組}/data-model.md` 找 Issue 涉及的 Table 定義（欄位、型別、PK/FK、約束）。

Issue body 已列的 spec 子檔、Wireframe、Service 契約檔於步驟 7 規劃時依需求讀取，不在此處重複交代。若 `docs/specs/{模組}/` 不存在，跳過本步驟。

---

### 步驟 7：產出實作計畫

**若步驟 1 找到 PLAN_COMMENT（`/sti-plan` 規劃留言）**：以它為實作計畫**底稿**，不要從頭重想——
- 直接沿用其 18／10 節的架構規劃、檔案清單、AC → 測試對應、實作順序
- 套用步驟 1 整理的 **SA 裁示**：凡 SA 已回覆的 SA Q，依裁示更新計畫對應段落
- 僅就「規劃留言完成後才出現的落差」（如 spec 更新、SA 裁示）做增補，不重複造輪子

**若無 PLAN_COMMENT**：依下列來源從頭產出計畫（原流程）。

整合以下資訊產出完整實作計畫：
- PLAN_COMMENT（若有）與其後的 SA 裁示
- Issue 驗收條件
- 步驟 6 查閱的規格文件（業務規則、資料模型、跨模組契約）
- 以下架構原則：
  - 分層：`router → service → repository`，不跨層呼叫
  - 禁止跨模組直接 import Repository 或 Model，只能透過 `services/__init__.py` 暴露的 Service
  - 錯誤處理統一使用 `AppError`（`core/exceptions.py`），必須帶 `error_code` 參數（查 `docs/ref/error-codes.md`），禁止自訂例外 class
  - 禁止硬刪除，一律 `DELETED = 1`
  - 寫入型 API（POST/PUT/DELETE）一律注入 `OperatorInfo = Depends(get_operator)` 填寫 `CREATED_*` / `UPDATED_*` 欄位，禁止直接讀 `payload.sub`
  - 所有 CUD 操作必須在 Service 層呼叫 `AuditLogService.log_action()` 寫入稽核日誌（`res_id` 必填）
  - 後端分頁一律使用 `paginate()` helper（`backend/app/core/pagination.py`）
  - API 回應格式：列表用 `{ "data": [...], "meta": { "total", "page", "limit", "total_pages" } }`
  - API 錯誤回應格式：`{ "error_code": "...", "error_message": "..." }`
- Context7 查詢到的最新 API 寫法

計畫必須包含以下區塊（呈現格式由 Claude 依內容複雜度自行判斷，可使用表格、編號列表或混合）：

1. **架構規劃**：涉及哪些層、哪些檔案、模組邊界
2. **實作步驟**：依序列出要建立/修改的檔案與說明
3. **測試計畫**：每條驗收條件對應的測試名稱與檔案路徑

計畫顯示完畢後，詢問使用者：
```
  1. 確認，開始實作
  2. 需要調整（請說明）
```

- 輸入 `1` → 繼續步驟 8
- 輸入 `2` 或直接輸入調整內容 → 修改計畫後再次確認

---

### 步驟 7.5：建立安全備份點

⚠️ **此步驟為強制步驟，不得跳過。**

在開始修改任何檔案之前，記錄當前 HEAD SHA 作為 **CHECKPOINT_SHA**：
```bash
git rev-parse HEAD
```

⚠️ **Claude 必須記住此 CHECKPOINT_SHA 值，供使用者還原時使用。**

顯示：
```
🔒 安全備份點已建立：{SHA 前 7 碼}
   還原指令：git reset --soft {CHECKPOINT_SHA}
```

> **還原時機**：若後續步驟中 Claude 執行了非預期的破壞性操作，使用者可執行 `git reset --soft {CHECKPOINT_SHA}` 還原到此備份點，所有變更會回到暫存區，不會遺失。

---

### 步驟 8：TDD 實作

依確認的計畫，嚴格遵守以下循環：

```
1. 先寫測試（RED）  → 執行測試，確認失敗
2. 實作功能（GREEN）→ 執行測試，確認通過
3. 重構（IMPROVE） → 確認測試仍通過
```

**後端測試執行**（提示使用者執行）：
- Worktree 模式：`cd ../worktrees/{slug}/backend && uv run pytest {測試檔案} -v`
- Branch 模式：`cd backend && uv run pytest {測試檔案} -v`

**前端測試執行**（提示使用者執行）：
- Worktree 模式：`cd ../worktrees/{slug}/frontend && pnpm test`
- Branch 模式：`cd frontend && pnpm test`

**中間備份**：每完成一個驗收條件的 IMPROVE 階段（重構完成、測試仍通過），立即建立 checkpoint commit：
```bash
git add -A
git commit -m "chore(checkpoint): acceptance criteria {N} done for #{Issue 編號}"
```

每完成一個驗收條件，更新進度顯示：
```
進度：[✅] 驗收條件 1  [⬜] 驗收條件 2  [⬜] 驗收條件 3
🔒 最近備份：{SHA 前 7 碼}（驗收條件 {N}）
```

**TS 型別預檢（僅前端 / TS 任務必做，Python 任務跳過）**：

vitest 透過 esbuild 跑測試會略過 TypeScript 型別檢查，所以 TDD 階段測試全綠不代表型別正確。為避免後續 Code Review 看到型別錯誤的程式碼浪費篇幅，TS 任務在 TDD 完成後、進入 Code Review 前必須先跑型別檢查：

- Worktree 模式：`cd {WORKTREE}/frontend && pnpm tsc --noEmit`
- Branch 模式：`cd frontend && pnpm tsc --noEmit`

若有型別錯誤 → 修正後再進入 Code Review。Python 任務不需此步驟（pytest 一定要 import 才跑得起來，型別問題會在測試階段就先爆出）。

⚠️ **TDD 完成後暫停，向使用者報告以下摘要：**
- 新增/修改的檔案清單
- 測試結果（通過/失敗數量）
- TS 型別預檢結果（TS 任務）／已跳過（Python 任務）

然後詢問：
```
  1. 繼續（進入 Code Review）
  2. 需要調整（請說明）
```

---

### 步驟 9：Code Review

實作完成後，準備暫存檔並 spawn `code-reviewer` agent 進行審查。

> ℹ️ Code Review 在本地 CI 之前執行，避免 reviewer 提出結構性建議後又要重跑一次完整 CI（含 integration tests）。

#### 9a. 準備暫存檔

取得目前分支名稱並 slug 化（將 `/` 替換為 `-`），將變更資訊寫入暫存檔：

```bash
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
BRANCH_SLUG="${BRANCH_NAME//\//-}"
git diff origin/main...HEAD > /tmp/review-local-${BRANCH_SLUG}-diff.patch
```

使用 **Write tool** 寫入 meta.json（`/tmp/review-local-<BRANCH_SLUG>-meta.json`）：

```json
{
  "source": "sti-implement",
  "pr_number": null,
  "branch": "{BRANCH_NAME}",
  "issue_number": {Issue 編號},
  "head_sha": "{git rev-parse HEAD}",
  "ci_status": "unknown",
  "implementation_summary": "{步驟 7 計畫摘要}",
  "diff_file": "/tmp/review-local-{BRANCH_SLUG}-diff.patch",
  "changed_files": ["{git diff --name-only origin/main...HEAD}"],
  "created_at": "{ISO 8601 時間}"
}
```

#### 9b. Spawn code-reviewer agent

使用 **Agent tool** spawn `code-reviewer` agent，prompt 中傳入暫存檔路徑與審查邊界：

```
請審查本地分支 {BRANCH_NAME} 的變更。

暫存檔路徑：
- meta.json：/tmp/review-local-{BRANCH_SLUG}-meta.json
- diff：/tmp/review-local-{BRANCH_SLUG}-diff.patch

請先用 Read tool 讀取 meta.json 和 diff 檔案，確認讀取成功後再開始審查。

【審查重點】
✅ 必看：
- 模組分層（router → service → repository）是否被違反
- 跨模組是否直接 import Repository / Model（應只透過 services/__init__.py 暴露的 Service）
- 業務邏輯正確性、邊界條件、race condition
- 測試是否涵蓋驗收條件中的真實情境（不只是 happy path）
- AppError / error_code / 稽核日誌（AuditLogService）/ 軟刪除（DELETED=1）/ OperatorInfo 等專案規範
- 安全相關但 lint 抓不到的問題（例如 SQL 拼接、未驗證的輸入流向）

❌ 請忽略（CI 會處理）：
- import 順序、單雙引號、空白、行長
- ruff / ESLint 可自動修復的格式議題
- 純 Prettier / Black 排版偏好

如發現純風格議題，僅在「會誤導讀者」時才提，否則略過。
```

> ⚠️ 上述審查邊界僅限本 spawn prompt，不修改 `code-reviewer` agent 定義檔本身（該 agent 為 `/sti-pr-review`、`/sti-pr-review-fix`、`/sti-verify-review` 共用）。

#### 9c. 清理暫存檔

> 無論 code-reviewer agent 是否成功完成審查，都必須執行此步驟清理暫存檔。

```bash
rm -f /tmp/review-local-${BRANCH_SLUG}-meta.json /tmp/review-local-${BRANCH_SLUG}-diff.patch
```

審查完成、所有議題修正完畢後，繼續步驟 10。

---

### 步驟 10：Security Review

使用 **security-reviewer** agent 針對本次修改的檔案進行安全檢查。

重點檢查項目：
- 無硬編碼機密（API 金鑰、密碼、Token）
- 所有使用者輸入已驗證
- 防止 SQL Injection（使用參數化查詢）
- 認證／授權已正確驗證
- 錯誤訊息不洩漏敏感資料

發現 CRITICAL 等級問題 → 立即修正後重新檢查，不得繼續。

---

### 步驟 11：本地 CI 驗證

⚠️ **此步驟在 Code Review / Security Review 全部修正完成後才執行**，避免 review 議題修正後又要重跑一次完整 CI（含 integration tests）。

#### 11a. 選擇執行模式

> ⚠️ **選擇跳過前請自行確認**：本次變更**完全沒有**碰到 `.py`、`.ts`、`.tsx`、`.js`、`.jsx`、`.sql`、Alembic migration、`pyproject.toml`、`package.json` 等會影響執行行為的檔案。若有疑慮，一律選 1。

詢問使用者：
```
本次變更是否需要執行完整 local CI？
  1. 執行完整 CI（建議：涉及程式碼異動）
  2. 跳過 CI 直接進入下一步驟（適用：純文件 / 註解 / 空白異動）
```

- 選擇 **1** → 進入 11b
- 選擇 **2** → 設定 `CI_SKIPPED=true`，跳到步驟 12（E2E 會依任務性質自動判斷需要與否，純文件 / 註解 / 空白異動通常會直接跳過進入步驟 13 Commit & PR）

⚠️ **若使用者選擇 2，Claude 必須記住 `CI_SKIPPED=true` 旗標，並在步驟 12 之後的完成摘要中強制使用「CI 跳過情境」版本，明確標示「⚠️ Local CI 已跳過」。** 比照步驟 7.5 的 `CHECKPOINT_SHA` 記憶機制，此旗標貫穿後續所有步驟直到流程結束。

#### 11b. 執行完整 CI（選擇 1）

使用 Bash 工具執行完整本地 CI（對應 GitHub CI 所有 job）：

- Worktree 模式：`cd {WORKTREE} && pnpm ci:local`
- Branch 模式：`pnpm ci:local`

腳本會依序執行：ruff lint → ruff format → unit tests → integration tests（需 DB）→ ESLint → type-check → frontend tests。

⚠️ **有任何 FAILED 項目時不得繼續，必須先修正所有錯誤。**

- 若全部 PASSED → 快速顯示結果後繼續
- 若有 FAILED → 逐一修正對應問題後，重新執行 `pnpm ci:local` 直到通過為止
- SKIPPED 項目（如 DB 未連線跳過 integration tests）可接受，但需在後續 PR 說明中標註

---

### 步驟 12：E2E 測試（選做）

依據功能類型判斷是否需要 E2E 測試：

- **需要**：涉及使用者登入流程、主要 CRUD 操作、跨頁面互動
- **跳過**：純後端 API、設定頁、簡單 CRUD 無複雜互動

若需要，使用 **e2e-runner** agent 以 Playwright 撰寫並執行測試，涵蓋正常操作與邊界情況。

---

顯示完成摘要（依步驟 11 是否執行 CI 而異）：

**正常情境**（步驟 11 選擇 1，CI 通過）：
```
✅ 所有驗收條件已實作
✅ Code Review 完成
✅ Security Review 完成
✅ Local CI 通過
```

**CI 跳過情境**（步驟 11 選擇 2）：
```
✅ 所有驗收條件已實作
✅ Code Review 完成
✅ Security Review 完成
⚠️ Local CI 已跳過（請確認本次變更為純文件 / 註解 / 空白異動，否則建議在 push 前手動跑 pnpm ci:local）
```

---

### 步驟 13：Commit & PR

```
請選擇下一步：
  1. 繼續 commit → push → 建立 PR（一氣呵成）
  2. 僅 commit → push（稍後再建 PR）
  3. 結束（稍後手動執行 /sti-commit + /sti-pr-create）
```

---

#### 13a. Commit & Push（選擇 1 或 2）

顯示 `git status` 讓使用者確認檔案清單（Worktree 模式在 `{WORKTREE}` 下執行，Branch 模式在專案根目錄執行）。

**安全檢查**：掃描變更檔案，發現以下則停止：
- `.env`、`.pem`、`id_rsa`、`*secret*`、`*credential*` 等敏感檔案
- 疑似硬編碼機密（`sk-`、`password =`、`SECRET_KEY =`）
- `console.log` 殘留（提示，非封鎖）

建議 commit message（依 conventional commits 格式）：
```
feat: {Issue 標題}

close #{Issue 編號}
```

詢問使用者：
```
  1. 確認送出
  2. 修改（直接輸入新的 commit message）
```

```bash
cd {WORKTREE 或專案根目錄}
git add {檔案}
git commit -m "{confirmed message}"
git push -u origin {分支名稱}
```

- 選擇 **2** → 顯示以下提示後結束：
  ```
  ✅ 已 commit & push。稍後建立 PR 請執行：
  /sti-pr-create #{Issue編號}
  ```

- 選擇 **1** → 繼續進入 13b

---

#### 13b. 建立 Draft PR（選擇 1）

⚠️ **一律建立 draft PR**：draft PR 期間的 commit 不觸發 CI（見 `.github/workflows/ci.yml` 的 `draft != true` 過濾），避免反覆修正造成 CI 排隊。轉正時機請見 `/sti-pr-ready`。

讀取 `.github/pull_request_template.md`，以步驟 1 取得的 Issue 資訊自動預填：
- **標題**：Issue 標題（去除 `[Foundation]`、`[Phase X]` 前綴）
- **body**：`Closes #{Issue 編號}` + 變更說明 + PR Checklist

顯示完整預覽，詢問使用者：
```
  1. 確認建立（draft PR）
  2. 修改內容（請說明）
```

```bash
gh pr create --draft --title "{標題}" --base main --body-file "/tmp/sti-pr-{Issue編號}-body.md"
```

Draft PR 不觸發 CI，**不輪詢 CI 狀態**、**不自動指派 Reviewer**。

最後顯示：
```
✅ Draft PR 已建立：#{PR編號} {標題}
🔗 {URL}

下一步：
1. 收到 Review 意見後執行 /sti-pr-review-fix #{PR編號} 修正
2. 修正全部完成、分支不再 commit 後執行 /sti-pr-ready #{PR編號} 轉為正式 PR
3. PR 合併後執行 /sti-cleanup #{Issue編號} 清理分支
   （worktree 模式：請先回到主 repo 目錄再執行）
```

---

#### 選擇 3 → 顯示提示後結束

```
下一步：
1. 執行 /sti-commit 提交變更
2. 執行 /sti-pr-create #{Issue編號} 建立 PR
3. PR 合併後執行 /sti-cleanup #{Issue編號} 清理分支
   （worktree 模式：請先回到主 repo 目錄再執行）
```
