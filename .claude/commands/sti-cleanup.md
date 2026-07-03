執行以下步驟，在 PR 合併後移除 Worktree、清理本地 feature 分支並同步 main。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| `0` / `取消` | 停止並顯示「已取消。」 |

> 本指令僅接受數字選項，不支援自由文字輸入。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 關聯的 Issue 編號（選填，用於顯示確認資訊）| `/sti-cleanup #25` |

## 執行時機

⚠️ **此指令僅在 PR 已合併至 main 後執行。** 若 PR 尚未合併，請勿執行。

⚠️ **此指令從主 repo 目錄執行。** 請先切換回主 repo：
```bash
cd <主 repo 目錄>
```

---

## 執行步驟

### 步驟 1：取得 Worktree 資訊

使用 Bash 工具執行：
```bash
git worktree list
```

顯示目前所有 worktree 清單，讓使用者確認待清理的項目。

---

### 步驟 2：確認 PR 已合併

若有傳入 Issue 編號，使用 Bash 工具查詢對應 PR 狀態：
```bash
gh pr list --state merged --search "#{編號}" --json number,title,state,mergedAt
```

- 若找到已合併的 PR → 顯示 PR 資訊（編號、標題、合併時間）後繼續
- 若未找到 → 詢問使用者：
  ```
  未找到對應的已合併 PR。
    1. 仍要繼續清理
    2. 取消
  ```

---

### 步驟 3：確認待清理的 Worktree 並判斷 MODE

從步驟 1 的清單中，識別出待清理的 worktree 路徑與對應分支名稱：
```bash
git worktree list --porcelain
```

**MODE 判斷（⚠️ Claude 必須記住此 MODE 值，供步驟 4 決定是否執行）：**

優先順序：
1. **若本次 session 內已記住開發 MODE**（例如同 session 內執行過 `/sti-implement`）→ 直接使用記憶值，跳過以下推導
2. **否則依 worktree 清單推導**（但注意：若同時有其他 Issue 的 worktree 存在，清單可能有歧義，需向使用者確認）：
   - 清單中存在與本次分支名稱一致的 worktree 條目 → **MODE=worktree**，記錄 `{WORKTREE_PATH}`
   - 清單中不存在對應 worktree（分支只在主 repo 存在）→ **MODE=branch**，`{WORKTREE_PATH}` 為空
   - 若不確定 → 詢問使用者：`此次開發是 worktree 模式還是 branch 模式？1. worktree  2. branch`

顯示：
```
待清理：
  模式：{worktree / branch}
  Worktree 路徑：{WORKTREE_PATH}（branch 模式為「無」）
  分支名稱：{分支名稱}
```

詢問使用者：
```
  1. 確認移除
  2. 取消
```

---

### 步驟 4：DROP 隔離 Test DB（僅 worktree 模式）

⚠️ **僅在 Worktree 模式執行；Branch 模式跳過本步驟。**

`/sti-implement` 步驟 2.5 為 worktree 配發了獨立 test DB（`test_edms_{DB_SLUG}`），本步驟對應地清掉。

#### 4a 推導 DB 名稱

從步驟 3 識別的分支名稱推導 `DB_SLUG` 與 `TEST_DB_NAME`，**規則必須與 `/sti-implement` 步驟 2.5a 完全一致**：
- `DB_SLUG` = 將分支名稱（含 `feature/` 前綴）中 `/` → `_`、`-` → `_`，截斷至 44 字元（為並行測試的 `_gwNN` 後綴預留額度，與 2.5a 一致）
- `TEST_DB_NAME` = `test_edms_{DB_SLUG}`

範例 bash 指令（Claude 在腦中執行同等邏輯）：
```bash
BRANCH_NAME={分支名稱}
DB_SLUG=$(echo "$BRANCH_NAME" | tr '/-' '__' | cut -c1-44)
# 安全防呆：DB_SLUG 僅允許 [a-z0-9_]，防止 SQL 識別字 injection
if ! [[ "$DB_SLUG" =~ ^[a-z0-9_]+$ ]]; then
  echo "❌ DB_SLUG 含不合法字元：'$DB_SLUG'。分支名稱僅允許 [a-z0-9/-]。"
  exit 1
fi
TEST_DB_NAME="test_edms_${DB_SLUG}"
```

#### 4b 安全防呆

⚠️ **DB 名必須以 `test_edms_` 為前綴，否則拒絕刪除**（避免誤砍主 `test_edms` 或其他 DB）：

```bash
case "${TEST_DB_NAME}" in
  test_edms_[a-z0-9_]*) ;;  # 前綴合法：test_edms_ + 至少一個 [a-z0-9_] 字元開頭
  *) echo "❌ DB 名 '${TEST_DB_NAME}' 不符合 test_edms_[a-z0-9_]* 規則，拒絕刪除"; exit 1 ;;
esac
```

特別注意：
- `test_edms`（無下底線結尾）不符合 `test_edms_[a-z0-9_]*` 模式，受保護
- 此 `case` 檢查確保前綴合法；字元集的完整保護來自步驟 4a 的 `[[ "$DB_SLUG" =~ ^[a-z0-9_]+$ ]]` allowlist，兩層防護互補

#### 4c 解析連線資訊並 DROP DATABASE（idempotent）

⚠️ **4c 和 DROP 邏輯整合在同一個條件區塊內**：`.env.test` 不存在時整塊跳過，不會嘗試以空變數呼叫 `psql`。

```bash
WORKTREE_ENV_TEST="{WORKTREE_PATH}/backend/.env.test"
if [ ! -f "$WORKTREE_ENV_TEST" ]; then
  echo "⚠️ 找不到 $WORKTREE_ENV_TEST，跳過 DROP DATABASE（可能是手動建立的 worktree）"
else
  # 用 heredoc + sys.argv[1] 傳遞路徑，避免路徑含空格或單引號時截斷（H-2 修正）
  eval "$(python3 - "$WORKTREE_ENV_TEST" <<'PYEOF'
import re, shlex, sys
from urllib.parse import urlparse
url = None
with open(sys.argv[1]) as f:
    for line in f:
        m = re.match(r'^\s*DATABASE_URL=(.*)$', line.rstrip('\n'))
        if m:
            url = m.group(1).strip().strip('"').strip("'")
            break
if not url: sys.exit('❌ 找不到 DATABASE_URL')
p = urlparse(url)
print(f'DB_USER={shlex.quote(p.username or "")}')
print(f'DB_PASS={shlex.quote(str(p.password or ""))}')
print(f'DB_HOST={shlex.quote(p.hostname or "localhost")}')
print(f'DB_PORT={p.port or 5432}')
PYEOF
  )"

  # DROP 邏輯緊接在 eval 成功後，在同一 else 區塊內執行
  if PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc \
     "SELECT 1 FROM pg_database WHERE datname='${TEST_DB_NAME}'" 2>/dev/null | grep -q 1; then
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c \
      "DROP DATABASE \"${TEST_DB_NAME}\" WITH (FORCE)" \
      && echo "✅ 已 DROP：${TEST_DB_NAME}" \
      || DROP_FAILED=1
  else
    echo "ℹ️ DB ${TEST_DB_NAME} 不存在（可能已 DROP 過或從未建立），跳過"
  fi

  # 安全網：清掉並行測試（pytest-xdist）殘留的 worker 庫 test_edms_{slug}_gwNN
  # 正常情況由 backend/tests/integration/conftest.py 跑完自清，此處僅處理硬當機殘留
  WORKER_DBS=$(PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -tAc \
    "SELECT datname FROM pg_database WHERE datname LIKE '${TEST_DB_NAME}_gw%'" 2>/dev/null)
  for wdb in $WORKER_DBS; do
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c \
      "DROP DATABASE IF EXISTS \"$wdb\" WITH (FORCE)" >/dev/null 2>&1 \
      && echo "✅ 已 DROP 殘留 worker 庫：$wdb"
  done
fi
```

若 DROP 失敗（`DROP_FAILED=1`），顯示以下訊息並詢問使用者（**不自動停止整個清理流程**）：

```
❌ DROP DB 失敗，可能有連線未釋放（如 pytest 異常終止）。

手動終止連線 SQL：
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid();

請選擇：
  1. 繼續後續清理步驟（Worktree 移除、分支刪除），稍後手動 DROP DB
  2. 停止，手動終止連線後重跑 /sti-cleanup
```

- 選擇 **1** → 繼續步驟 5（標記 DROP 待辦，完成摘要中標示）
- 選擇 **2** → 停止

---

### 步驟 5：移除 Worktree

⚠️ **僅在 Worktree 模式執行；Branch 模式跳過本步驟。**

使用 Bash 工具執行（從主 repo 目錄）：
```bash
git worktree remove {WORKTREE_PATH}
```

- 若成功 → 顯示：「✅ 已移除 Worktree：{WORKTREE_PATH}」
- 若失敗（worktree 有未 commit 的變更）→ 顯示：「⚠️ Worktree 有未提交的變更，無法移除。請先處理後再執行，或使用 `git worktree remove --force {WORKTREE_PATH}` 強制移除。」並停止，不自動執行強制移除。

---

### 步驟 6：同步 main 並刪除分支

使用 Bash 工具執行：
```bash
git checkout main && git pull origin main && git branch -d {分支名稱}
```

- 若 `branch -d` 成功 → 繼續
- 若失敗（提示 not fully merged）→ 顯示：「⚠️ 分支刪除失敗。若確認 PR 已合併，請執行 `git branch -D {分支名稱}` 強制刪除。」並停止，不自動強制刪除。

---

### 步驟 7：清理 Worktree 記錄

使用 Bash 工具執行：
```bash
git worktree prune
```

---

### 步驟 8：顯示完成摘要

依 MODE 條件化顯示不同內容：

**Worktree 模式**：
```
## 清理完成！

✅ 已 DROP 隔離 Test DB：{TEST_DB_NAME}
✅ 已移除 Worktree：{WORKTREE_PATH}
✅ 已切換至 main 並同步最新版本
✅ 已刪除本地分支：{分支名稱}

目前 main 最新 commit：
{git log --oneline -3 的輸出}

下一步建議：
執行 /sti-issue-list open 查看下一個待處理的 Issue。
```

> 若步驟 4 DROP 失敗且選擇繼續，將「✅ 已 DROP」改為「⚠️ DB 未 DROP（待手動處理）：{TEST_DB_NAME}」。

**Branch 模式**：
```
## 清理完成！

✅ 已切換至 main 並同步最新版本
✅ 已刪除本地分支：{分支名稱}

目前 main 最新 commit：
{git log --oneline -3 的輸出}

下一步建議：
執行 /sti-issue-list open 查看下一個待處理的 Issue。
```
