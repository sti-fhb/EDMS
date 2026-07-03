執行以下步驟，對指定 GitHub Pull Request 進行完整 Code Review。

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
| `#編號` 或 `編號` | 要 Review 的 PR 編號（必填）| `/sti-pr-review #36` |

---

## 執行步驟

### 步驟 1：解析參數 & 取得 PR 資訊

從 `$ARGUMENTS` 解析 PR 編號（去除 `#` 符號）。
若未傳入編號，提示使用者：「請提供 PR 編號，例如：`/sti-pr-review #36`」，並停止執行。

```bash
# PR 基本資訊
gh pr view {編號} --json number,title,state,author,headRefName,baseRefName,body,isDraft,additions,deletions,changedFiles

# 變更檔案清單
gh pr diff {編號} --name-only

# CI 靜態檢查結果（取代在 worktree 本地跑 Lint）
gh pr checks {編號}
```

若 PR 狀態為 `MERGED` 或 `CLOSED`，提示使用者：
```
此 PR 已 {MERGED/CLOSED}。
  1. 仍要 Review
  2. 取消
```

顯示 PR 摘要：

```
---
## 🔍 Review PR #{編號}: {標題}

**分支**：`{headRefName}` → `{baseRefName}`
**作者**：{author}
**變更**：+{additions} / -{deletions}，共 {changedFiles} 個檔案
**CI 檢查狀態**：{gh pr checks 摘要}
**變更檔案**：
  - {逐行列出}
---
```

---

### 步驟 2：建立或更新 Review Worktree

> ⚠️ **變數持久性**：Bash tool 每次呼叫為獨立 shell。**每個 bash 區塊開頭必須重新定義路徑變數**，不得省略。

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$(dirname "$REPO_ROOT")/.review-worktree/pr-{編號}"
REVIEW_BRANCH="pr-review-{編號}"
META_FILE="$REVIEW_DIR/.review-meta.json"

git fetch origin main

# 安全性檢查：分支已存在但非 review worktree 建立
if git branch --list "$REVIEW_BRANCH" | grep -q . && \
   ! git worktree list | grep -qF "pr-{編號}"; then
  echo "ERROR: 本地已有 $REVIEW_BRANCH 分支但非 review worktree 建立"
  echo "ABORT: 請先手動執行 git branch -D $REVIEW_BRANCH 後重試"
  exit 1
fi

# ── Fetch 分流 + Worktree 狀態判斷 ──
# re-review 時 pull/N/head:$REVIEW_BRANCH 會因 worktree 鎖住分支 ref 而失敗，
# 故偵測 worktree 已存在時改走 FETCH_HEAD 路徑，不更新本地分支 ref
if [ -d "$REVIEW_DIR" ] && git worktree list | grep -qF "$REVIEW_DIR"; then
  # Worktree 已存在（re-review）
  git fetch origin "pull/{編號}/head"
  NEW_SHA=$(git rev-parse FETCH_HEAD)

  # 讀取上次 review 的 HEAD SHA
  if command -v jq &>/dev/null; then
    PREV_SHA=$(jq -r '.head_sha // empty' "$META_FILE" 2>/dev/null)
  else
    PREV_SHA=$(sed -n 's/.*"head_sha"\s*:\s*"\([^"]*\)".*/\1/p' "$META_FILE" 2>/dev/null)
  fi

  if [ -z "$PREV_SHA" ]; then
    echo "REVIEW_STATUS=FIRST_REVIEW"
  elif [ "$PREV_SHA" = "$NEW_SHA" ]; then
    echo "REVIEW_STATUS=NO_NEW_COMMITS"
  else
    echo "REVIEW_STATUS=NEW_COMMITS_SINCE_LAST_REVIEW"
    git log "${PREV_SHA}..${NEW_SHA}" --oneline
  fi
else
  # Worktree 不存在（首次）：fetch 到本地分支 + 建立 worktree
  git fetch origin "pull/{編號}/head:$REVIEW_BRANCH" --force
  NEW_SHA=$(git rev-parse "$REVIEW_BRANCH")

  # 清理無效殘留目錄後建立
  if [ -d "$REVIEW_DIR" ]; then
    echo "INFO: 偵測到無效的殘留目錄，自動清理後重建"
    rm -rf "$REVIEW_DIR"
    git worktree prune
  fi

  mkdir -p "$(dirname "$REVIEW_DIR")"
  if ! git worktree add "$REVIEW_DIR" "$REVIEW_BRANCH" 2>&1; then
    echo "ERROR: 無法建立 worktree，嘗試 prune 後重試"
    git worktree prune
    git worktree add "$REVIEW_DIR" "$REVIEW_BRANCH" || exit 1
  fi

  echo "REVIEW_STATUS=FIRST_REVIEW"
fi

# ── 統一後處理：merge main + submodule + meta ──
# 使用 $NEW_SHA 作為 reset 目標，避免 per-worktree FETCH_HEAD 不一致
(
  cd "$REVIEW_DIR" || exit 1
  git reset --hard "$NEW_SHA"

  if ! git merge origin/main --no-edit 2>&1; then
    echo "WARNING: 與 main 存在衝突，以 PR 原始狀態進行 review"
    git merge --abort 2>/dev/null || git reset --hard "$NEW_SHA"
  fi

  # Submodule 初始化（防禦性處理，若無 submodule 則無副作用）
  git submodule update --init --recursive 2>/dev/null || true

  if command -v jq &>/dev/null; then
    jq -n --arg sha "$NEW_SHA" --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{"head_sha": $sha, "reviewed_at": $ts}' > .review-meta.json
  else
    printf '{"head_sha": "%s", "reviewed_at": "%s"}\n' \
      "$NEW_SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .review-meta.json
  fi
)
```

若輸出 `REVIEW_STATUS=NO_NEW_COMMITS`，詢問使用者：
```
PR 自上次 Review 後沒有新 commit。
  1. 仍要重新 Review
  2. 取消
```

---

### 步驟 2b：取得前輪 Review 歷史（多輪 Review 時）

> 僅在 `REVIEW_STATUS` 非 `FIRST_REVIEW` 時執行。首輪 Review 跳過此步驟。
>
> **例外**：即使是 `FIRST_REVIEW`，也必須檢查 STALE findings 暫存檔（見下方）。

#### 2b-i. 載入 STALE findings（每次都執行）

先檢查是否有前次因 STALE 取消而保存的 findings：

```bash
STALE_FILE="/tmp/review-pr-{編號}-stale-findings.json"
if [ -f "$STALE_FILE" ]; then
  echo "STALE_FINDINGS=EXISTS"
  cat "$STALE_FILE"
else
  echo "STALE_FINDINGS=NONE"
fi
```

若 `STALE_FINDINGS=EXISTS`，將其中的 findings 加入 `review_history.previous_findings`，標記為 `status: "pending_verification"`。這些項目必須在本輪被驗證（確認是否仍存在於最新程式碼中），不可忽略。

> 即使 `REVIEW_STATUS=FIRST_REVIEW`（GitHub 上無前輪紀錄），只要 STALE findings 存在，就視為多輪 Review，`review_history.round` 至少為 2。

#### 2b-ii. 取得 GitHub 上的前輪 Review 歷史

> 若 `REVIEW_STATUS=FIRST_REVIEW` 且 `STALE_FINDINGS=NONE`，跳過此步驟。

```bash
OWNER_REPO=$(gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"')

# 前輪 review 意見（body + 時間）
gh api "repos/${OWNER_REPO}/pulls/{編號}/reviews" --paginate \
  --jq '.[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED" or .state == "COMMENTED") | {id: .id, user: .user.login, state: .state, body: .body, submitted_at: .submitted_at}'

# 作者回覆（含修正回覆表格）
gh api "repos/${OWNER_REPO}/issues/{編號}/comments" --paginate \
  --jq '.[] | {id: .id, user: .user.login, body: .body, created_at: .created_at}'
```

從回覆中整理三類清單：

| 分類 | 識別方式 | 本輪處理 |
|------|---------|---------|
| **已修正** ✅ | 作者回覆表格中標記「✅ 已修正」 | 僅驗證修正正確性，不重新審查 |
| **暫緩** ⏭️ | 作者回覆表格中標記「⏭️ 暫緩」並附理由 | **不得重提**，除非新 commit 引入新證據 |
| **待討論** 💬 | 作者回覆表格中標記「💬 待討論」 | 必須正面回應，不得迴避 |

計算 **Review 輪次**：review body 非空的 review 數量 + 1。

將整理結果注入步驟 4a 的 `meta.json` 中（新增 `review_history` 欄位）：

```json
{
  "review_history": {
    "round": 3,
    "previous_findings": [
      { "id": "HIGH-1", "summary": "...", "status": "fixed" },
      { "id": "M-1", "summary": "...", "status": "deferred", "reason": "..." },
      { "id": "M-2", "summary": "...", "status": "discussing" }
    ]
  }
}
```

> **Fallback**：若 GitHub API 呼叫失敗（rate limit、網路問題），退化為首輪模式並附註「無法取得前輪 Review 歷史，本輪按首輪模式執行」。

---

### 步驟 3：讀取變更檔案

取得完整 PR Diff：

```bash
gh pr diff {編號}
```

> 若 diff 超過 2000 行，改為依變更檔案逐一取得：`gh pr diff {編號} -- {file_path}`

**預設策略：先看 Diff，不足再主動讀取。**

你（Agent）必須遵守以下流程：
1. 所有檔案**預設只看 Diff**。
2. 若 Diff 不足以判斷模組邊界、邏輯依賴或上下文，**你必須主動呼叫 Read Tool** 讀取該檔案的相關段落，而不是在資訊不足的情況下猜測。
3. 讀取時優先指定行號範圍，避免一次讀入整個大檔案。

#### 檔案分級對照表

| 分級 | 副檔名 / 路徑模式 | 處理方式 |
|------|-------------------|----------|
| **完整讀取（強制）** | `.github/workflows/*`、`Dockerfile`、`docker-compose.yml`、`docker-compose.*.yml` | 必須完整讀取，**不得只看 Diff**；需檢查 supply chain 風險與權限設定 |
| **Diff 優先，按需讀取** | `.py` `.ts` `.tsx` `.js` `.jsx` `.vue` `.go` `.rs` `.java` `.rb` `.kt` `.swift` `.c` `.cpp` `.h` `.hpp` `.sh` | 預設看 Diff；若需要上下文，主動呼叫 Read Tool 讀取特定行範圍 |
| **僅 Diff** | `.md` `.json` `.yaml` `.yml`（非 CI/CD）`.toml` `.ini` `.cfg` `.env.example`、`alembic/versions/*.py` | 只看 Diff，不完整讀取 |
| **完全跳過** | `pnpm-lock.yaml` `package-lock.json` `uv.lock` `poetry.lock` `.min.js` `.min.css` `dist/*` `build/*` | 略過，不納入 review |

> 副檔名不在上表中時，預設歸入「僅 Diff」。

---

### 步驟 4：準備暫存檔並執行 Code Review

#### 4a. 準備暫存檔

將步驟 1~3 收集的資訊寫入暫存檔，供 `code-reviewer` agent 讀取：

```bash
# Diff 檔案
gh pr diff {編號} > /tmp/review-pr-{編號}-diff.patch
```

使用 **Write tool** 寫入 meta.json（`/tmp/review-pr-{編號}-meta.json`）：

```json
{
  "source": "sti-pr-review",
  "pr_number": {編號},
  "branch": "{headRefName}",
  "issue_number": null,
  "head_sha": "{步驟 2 記錄的 NEW_SHA}",
  "ci_status": "{gh pr checks 摘要：success / failure / pending / unknown}",
  "implementation_summary": "{PR body 摘要}",
  "diff_file": "/tmp/review-pr-{編號}-diff.patch",
  "changed_files": ["{逐行列出}"],
  "created_at": "{ISO 8601 時間}"
}
```

#### 4b. Spawn code-reviewer agent

使用 **Agent tool** spawn `code-reviewer` agent，prompt 中傳入暫存檔路徑：

```
請審查 PR #{編號}。

暫存檔路徑：
- meta.json：/tmp/review-pr-{編號}-meta.json
- diff：/tmp/review-pr-{編號}-diff.patch

請先用 Read tool 讀取 meta.json 和 diff 檔案，確認讀取成功後再開始審查。
CI 檢查狀態：{ci_status}（若 CI 已回報 Lint 錯誤，直接整合進報告，重點放在 CI 抓不到的問題）。

⚠️ 若 meta.json 包含 review_history，代表這是第 {round} 輪 Review，請嚴格遵守「多輪 Review 收斂規則」：
- 不得重提 status=deferred 的項目
- 不得推翻前輪建議（除非有新 commit 證據）
- 第三輪起僅審查新 commit 的 diff
```

等待 agent 回傳報告。

#### 4c. 清理暫存檔

無論 code-reviewer agent 是否成功完成審查、是否提交到 GitHub，都必須清理暫存檔：

```bash
rm -f /tmp/review-pr-{編號}-meta.json /tmp/review-pr-{編號}-diff.patch
```

> ⚠️ **不要在此步驟清理 STALE findings 暫存檔**（`/tmp/review-pr-{編號}-stale-findings.json`）。該檔案僅在步驟 6 成功提交 Review 到 GitHub 後才清理，確保未提交的 findings 不會遺失。

---

### 步驟 5：展示 Review 報告

將 `code-reviewer` agent 回傳的報告直接展示給使用者。報告格式由 agent 統一產出，此處不再定義。

---

### 步驟 6：提交 Review 到 GitHub

詢問使用者：
```
是否要將此 Review 提交到 GitHub？
  1. 提交 Review（發布到 PR 頁面）
  2. 僅本地查看（不提交）
```

若選擇提交：

**Step A**：檢查 PR HEAD 是否在分析期間發生變動（防止提交基於舊版程式碼的 review）：

```bash
# ORIGINAL_SHA 為步驟 2 中記錄的 NEW_SHA
CURRENT_HEAD=$(gh pr view {編號} --json headRefOid --jq .headRefOid)
echo "分析時 HEAD: {ORIGINAL_SHA}"
echo "目前 HEAD:   $CURRENT_HEAD"
if [ "{ORIGINAL_SHA}" != "$CURRENT_HEAD" ]; then
  echo "⚠️ STALE: PR HEAD 已從 {ORIGINAL_SHA} 變為 $CURRENT_HEAD"
  echo "分析期間有新的 commit 推送，Review 內容可能已過時。"
else
  echo "✅ HEAD 未變動，可安全提交。"
fi
```

若偵測到 STALE，**必須停止提交**並提示使用者：
```
⚠️ PR HEAD 在分析期間已變動（{ORIGINAL_SHA} → {CURRENT_HEAD}），
本次 Review 基於舊版程式碼，建議重新執行 /sti-pr-review {編號}。
  1. 仍要提交
  2. 取消
```

若使用者選擇取消，**必須將本輪 findings 寫入 STALE 暫存檔**，避免重新執行時遺失：

使用 **Write tool** 將本輪報告中所有 findings 寫入 `/tmp/review-pr-{編號}-stale-findings.json`：

```json
{
  "stale_sha": "{ORIGINAL_SHA}",
  "saved_at": "{ISO 8601 時間}",
  "findings": [
    { "id": "H-1", "level": "HIGH", "summary": "...", "file": "...", "detail": "..." },
    { "id": "M-1", "level": "MEDIUM", "summary": "...", "file": "...", "detail": "..." }
  ]
}
```

> 此檔案供下次執行 `/sti-pr-review {編號}` 時，步驟 2b 自動載入。

**Step B**：使用 **Write tool** 將報告寫入暫存檔後執行。

依 code-reviewer 結論決定使用哪個子指令：

| 結論 | 子指令 | 是否需要自我 Review 檢查 |
|------|--------|--------------------------|
| APPROVE | `--approve` | 需要（GitHub 禁止 approve 自己的 PR） |
| REQUEST_CHANGES | `--request-changes` | 需要（GitHub 禁止 request-changes 自己的 PR） |
| COMMENT | `--comment` | 不需要（對自己 PR 發 comment 本來就合法） |

⚠️ **自我 Review 防呆**：僅在結論為 APPROVE 或 REQUEST_CHANGES 時執行身份檢查；COMMENT 直接提交，省去 2 次 API 呼叫。

```bash
REVIEW_BODY_FILE="/tmp/sti-review-pr-{編號}-body.md"

# 執行時將 {結論} 替換為 code-reviewer 產出的結論（approve / request-changes / comment）
case "{結論}" in
  approve|request-changes)
    PR_AUTHOR=$(gh pr view {編號} --json author --jq .author.login)
    CURRENT_USER=$(gh api user --jq .login 2>/dev/null || echo "UNKNOWN")
    echo "PR 作者: $PR_AUTHOR / 當前使用者: $CURRENT_USER"

    if [ "$PR_AUTHOR" = "$CURRENT_USER" ] || [ "$CURRENT_USER" = "UNKNOWN" ]; then
      # 自我 Review 或無法確認身份 → 降級為 --comment
      echo "（自我 Review，降級為 --comment）"
      gh pr review {編號} --comment --body-file "$REVIEW_BODY_FILE"
    elif [ "{結論}" = "approve" ]; then
      gh pr review {編號} --approve --body-file "$REVIEW_BODY_FILE"
    else
      gh pr review {編號} --request-changes --body-file "$REVIEW_BODY_FILE"
    fi
    ;;
  comment)
    # 對自己 PR 發 comment 本來就合法，不需查身份
    gh pr review {編號} --comment --body-file "$REVIEW_BODY_FILE"
    ;;
esac

rm -f "$REVIEW_BODY_FILE"

# Review 成功提交後，清理 STALE findings 暫存檔（若存在）
rm -f "/tmp/review-pr-{編號}-stale-findings.json"
```

> 若降級為 `--comment`，在報告開頭附註：「（自我 Review，僅以 comment 形式提交）」

顯示：「✅ Review 已提交到 PR #{編號}。」

---

### 步驟 7：清理 Worktree（選做）

詢問使用者：
```
是否要清理 Review Worktree？
  1. 保留（方便後續 re-review）
  2. 清理（刪除 worktree 與暫存分支）
```

若選擇清理：

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$(dirname "$REPO_ROOT")/.review-worktree/pr-{編號}"
REVIEW_WORKTREE_ROOT="$(dirname "$REPO_ROOT")/.review-worktree"

git worktree remove "$REVIEW_DIR" --force 2>/dev/null || true
git branch -D "pr-review-{編號}" 2>/dev/null || true
git worktree prune
rmdir "$REVIEW_WORKTREE_ROOT" 2>/dev/null || true
```

若選擇保留，提示：「Worktree 已保留，下次執行 `/sti-pr-review {編號}` 會自動更新。」

---

## 注意事項

- Review 語言使用繁體中文。
- 若 diff 超過 2000 行，依變更檔案逐一取得：`gh pr diff {編號} -- {file_path}`
- 在任意分支上執行，review 上下文都基於最新 main + PR 變更，不受 reviewer 當前分支影響。
- Merge main 時若有衝突，自動放棄並保持 PR 原始狀態，不阻擋 review 流程。
- **已知限制**：此 Agent 的 review 結果非確定性，相同 PR 不同執行可能產生不同深度的報告。CI 靜態檢查結果（`gh pr checks`）是唯一具確定性的品質依據，應優先信任。
- **格式契約**：報告格式（`### 🔴 CRITICAL` 等前綴）為 `/sti-verify-review` 的解析依據，修改格式前需同步更新 `sti-verify-review.md`。
