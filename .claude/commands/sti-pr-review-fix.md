執行以下步驟，回應指定 GitHub Pull Request 的 Review 意見，自動化修正並通知 Reviewer。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如修改 commit message） |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要處理 Review 意見的 PR 編號（必填）| `/sti-pr-review-fix #44` |

---

## 執行步驟

### 步驟 1：解析參數 & 取得 PR 資訊

從 `$ARGUMENTS` 解析 PR 編號（去除 `#` 符號）。
若未傳入編號，提示使用者：「請提供 PR 編號，例如：/sti-pr-review-fix #44」，並停止執行。

使用 Bash 工具取得 PR 基本資訊：

```bash
gh pr view {編號} --json number,title,state,author,headRefName,baseRefName,body,isDraft,additions,deletions,changedFiles
```

若 PR 狀態為 MERGED 或 CLOSED，提示使用者：
```
此 PR 已 {MERGED/CLOSED}。
  1. 仍要繼續
  2. 取消
```

驗證當前分支：

```bash
git branch --show-current
```

若當前分支不是 PR 的 `headRefName`，提示使用者：
「目前分支為 `{current_branch}`，但 PR 的來源分支是 `{headRefName}`。請先執行 `git checkout {headRefName}` 後再重新執行本指令。」並停止執行。

顯示 PR 摘要：

```
---
## 🔧 Fix PR Review #{編號}: {標題}

**分支**：`{headRefName}` → `{baseRefName}`
**作者**：{author}
**變更**：+{additions} / -{deletions}，共 {changedFiles} 個檔案
---
```

---

### 步驟 2：取得最新 Review 意見

使用 Bash 工具取得 repo 資訊，再依序取得完整 Review 意見：

```bash
# 取得 owner/repo
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'

# 取得所有 review（含 review body）
gh api repos/{owner}/{repo}/pulls/{編號}/reviews --paginate --jq '.[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED" or .state == "COMMENTED" or .state == "DISMISSED") | {id: .id, user: .user.login, state: .state, body: .body, submitted_at: .submitted_at}'

# 取得所有 inline comments（行內留言，含 diff 上下文）
gh api repos/{owner}/{repo}/pulls/{編號}/comments --paginate --jq '.[] | {id: .id, user: .user.login, path: .path, line: .line, diff_hunk: .diff_hunk, body: .body, created_at: .created_at, in_reply_to_id: .in_reply_to_id}'

# 取得 PR 討論串中的一般留言（非 inline）
gh api repos/{owner}/{repo}/issues/{編號}/comments --paginate --jq '.[] | {id: .id, user: .user.login, body: .body, created_at: .created_at}'
```

> **格式說明**：以上 `--jq` 輸出為 JSONL（每行一個 JSON 物件），非 JSON array。

**注意事項：**
- 若有多輪 Review，優先處理**最新一輪**的意見（依 `submitted_at` / `created_at` 排序）。
- 忽略 `DISMISSED` 狀態的 Review。
- 若 Review 意見為空（reviewer 僅按了 Approve 無留言），提示使用者：「此 PR 沒有需要處理的 Review 意見。」並停止執行。

---

### 步驟 3：整理問題清單與修改計畫

將所有 Review 意見依嚴重等級分類：

| 等級 | 判斷依據 |
|------|----------|
| 🔴 CRITICAL | 安全漏洞、資料遺失風險、邏輯錯誤 |
| 🟠 HIGH | 違反專案規範（模組邊界、錯誤處理、Schema 規範）、明顯 Bug |
| 🟡 MEDIUM | 程式碼品質（命名不佳、重複程式碼、缺少型別標註） |
| 🟢 LOW | 風格建議、文件改善、可選優化 |

顯示修改計畫：

```
---
## 📋 Review 意見整理

**Reviewer**：{reviewer_login}
**Review 狀態**：{APPROVED / CHANGES_REQUESTED / COMMENTED}
**意見總數**：{總數}

### 修改計畫

| # | 等級 | 檔案 | 問題摘要 | 預計修正方式 |
|---|------|------|----------|-------------|
| 1 | 🔴 | `{path}:{line}` | {問題描述} | {修正方式} |
| 2 | 🟠 | `{path}:{line}` | {問題描述} | {修正方式} |

### 暫緩項目（若有）

| # | 原因 | 說明 |
|---|------|------|
| {編號} | {暫緩原因} | {詳細說明} |
---
```

詢問使用者：
```
  1. 確認，開始修正
  2. 需要調整（請說明）
```

- 輸入 `1` → 繼續步驟 4
- 輸入 `2` 或直接輸入調整內容 → 更新計畫後再次確認

---

### 步驟 4：執行修改

依照確認後的修改計畫逐項執行：

1. 使用 Read 工具讀取對應檔案
2. 理解上下文後使用 Edit 工具修改
3. 每修正完一項，簡短報告修改內容

**注意事項：**
- 修改範圍嚴格限制在 Review 意見指出的問題，不主動擴大。
- 若某項修正會連帶影響其他檔案，先說明再執行。
- 若 Review 意見有誤或不適用，標記為「暫緩」並說明原因，不自行跳過。

修改完成後，若專案有測試，提示使用者執行對應測試確認未破壞既有功能。

---

### 步驟 4.5：CI 快速驗證

修改完成後，使用 Bash 工具執行快速 CI 驗證：

```bash
pnpm ci:quick
```

- 若全部 PASSED → 繼續步驟 5
- 若有 FAILED → 修正後重跑，直到通過為止

---

### 步驟 5：Commit & Push

依修改性質選擇適當 commit 類型：

| 類型 | 使用時機 |
|------|----------|
| `fix` | 修正 Bug、邏輯錯誤 |
| `refactor` | 重構、改善程式碼結構 |
| `style` | 格式、命名調整 |
| `docs` | 文件改善 |

建議 commit message 格式：

```
{type}: 根據 code review 修正 {N} 項問題

- {修正項目 1 簡述}
- {修正項目 2 簡述}
```

詢問使用者：
```
  1. 確認送出
  2. 修改（直接輸入新的 commit message）
```

使用者選擇 `1` 後執行：

```bash
git add {修改的檔案}
git commit -m "$(cat <<'EOF2'
{type}: 根據 code review 修正 {N} 項問題

- {修正項目 1 簡述}
- {修正項目 2 簡述}
EOF2
)"
git push
```

若 push 失敗（遠端有新 commit），提示使用者先 pull 再重試。

---

### 步驟 6：在 PR 留言通知 Reviewer

Commit & Push 成功後，使用 Bash 工具自動在 PR 留言通知 Reviewer：

```bash
gh pr comment {編號} --body "$(cat <<'EOF'
## 🔧 Review 修正回覆

Hi @{reviewer_login}，已根據您的 Review 意見進行修正：

| # | 問題 | 修正方式 | 狀態 |
|---|------|----------|------|
| 1 | {問題摘要} | {修正說明} | ✅ 已修正 |
| 2 | {問題摘要} | {修正說明} | ✅ 已修正 |
| 3 | {問題摘要} | {暫緩原因} | ⏭️ 暫緩 |

📌 Commit: `{short_hash}` {commit_message}

請再次 Review，謝謝！
EOF
)"
```

顯示：「✅ 已在 PR #{編號} 留言通知 @{reviewer_login}。」

若本輪為最後一輪修正、分支不再 commit，顯示提示：
```
下一步：若本輪已是最後一輪修正，執行 /sti-pr-ready #{編號} 將 Draft 轉為正式 PR。
```

## 注意事項

- 步驟 1 會自動驗證當前分支是否為 PR 的 head branch，不符則停止執行。
- 若 Review 意見涉及需要討論的架構問題，建議使用者直接在 PR 上回覆討論，不要硬改。
- 若同一個 PR 有多位 Reviewer，合併處理並在留言中標記所有 Reviewer。
- 留言語言使用繁體中文。
- 若需將 Review 意見轉為新 Issue，必須依照 `/sti-issue-create` 的「Issue 內容模板」格式建立。
