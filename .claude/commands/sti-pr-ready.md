執行以下步驟，將 Draft Pull Request 轉為正式 PR（Ready for Review）。

## 使用時機

- Code Review 意見已全部處理完畢，PR 分支不會再有新 commit
- 即將請 Reviewer 審查或準備合併到 main

> **背景**：`.github/workflows/ci.yml` 已過濾 `draft != true`，draft 期間的 commit 不跑 CI；轉正時會觸發 `ready_for_review` event 跑一次 CI。此指令協助在轉正前先跑本地 CI，降低遠端 CI 紅燈後又要補 push 的機率。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`） | 執行對應選項 |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#PR編號` 或 `編號` | 要轉正的 PR 編號（必填）| `/sti-pr-ready #25` |

---

## 執行步驟

### 步驟 1：讀取並驗證 PR

從 `$ARGUMENTS` 解析 PR 編號（去除 `#` 符號）。
若未傳入編號，提示「請提供 PR 編號，例如：/sti-pr-ready #25」並停止。

使用 Bash 工具執行：

```bash
gh pr view {編號} --json number,title,state,isDraft,headRefName,author,url
```

驗證條件（任一不符則停止執行）：
- `state` 必須為 `OPEN`，否則顯示：「❌ PR #{編號} 狀態為 {state}，無法轉正。」
- `isDraft` 必須為 `true`，否則顯示：「ℹ️ PR #{編號} 已是正式 PR，無需轉正。」

顯示 PR 基本資訊：
```
📋 PR #{編號}：{標題}
   分支：{headRefName}
   作者：{author.login}
   狀態：Draft
```

---

### 步驟 2：檢查本地分支與同步狀態

```bash
git rev-parse --abbrev-ref HEAD
```

若當前分支不等於 `headRefName`，顯示：
```
⚠️ 當前分支為 {current_branch}，與 PR #{編號} 的 head ({headRefName}) 不同。
請先切換：git checkout {headRefName}
```
並停止執行。

檢查工作區乾淨、且無未推送的 commit：

```bash
git status --porcelain
git fetch origin {headRefName}
git log origin/{headRefName}..HEAD --oneline
```

- 若 `git status --porcelain` 有輸出 → 停止並提示「工作區有未提交的變更，請先 commit/stash」
- 若 `git log` 有輸出 → 停止並提示「有本地 commit 未 push，請先 `git push`」

---

### 步驟 3：選擇是否跑本地 CI

詢問使用者：
```
是否在轉正前跑一次本地 CI 驗證？
  1. 跑本地 CI（推薦；一次本地 CI 比遠端 CI 失敗再 push 節省資源）
  2. 跳過（已在 /sti-pr-review-fix 或 /sti-implement 步驟 9 跑過、且此後無新 commit）
```

**選擇 1**（跑本地 CI）：進入步驟 3a
**選擇 2**（跳過）：直接進入步驟 4

#### 步驟 3a：執行本地 CI

```bash
pnpm ci:local
```

- 若全部 PASSED → 顯示「✅ 本地 CI 通過」後繼續步驟 4
- 若有 FAILED → 停止並顯示：
  ```
  ❌ 本地 CI 失敗，請先修正後 commit & push，再重新執行 /sti-pr-ready #{編號}。
     （draft PR 期間的 push 不會觸發遠端 CI）
  ```

---

### 步驟 4：確認轉正

顯示：
```
🔄 即將執行：gh pr ready {編號}
   → 會觸發一次遠端 CI（types: ready_for_review）

  1. 確認轉正
  2. 取消
```

**選擇 1** → 繼續步驟 5
**選擇 2** / `0` → 顯示「已取消。」並停止

---

### 步驟 5：轉為正式 PR

```bash
gh pr ready {編號}
```

顯示：「✅ PR #{編號} 已轉為正式 PR（Ready for Review）。」

---

### 步驟 6：等待並檢查遠端 CI

等待 ~15 秒後輪詢 CI 狀態：

```bash
sleep 15 && gh pr checks {編號}
```

根據結果顯示：

**CI 全部通過**：
```
✅ 遠端 CI 全綠，PR #{編號} 已可 merge。
```

**CI 仍在執行中**：
```
⏳ CI 仍在執行中，可稍後執行 gh pr checks {編號} 查看。
```

**CI 有失敗**：
```
❌ 遠端 CI 有失敗項目：
  - {job_name}: ❌
  ...

可執行：
  gh run view {run_id} --log-failed    # 查看失敗原因

若需修正期間避免反覆觸發 CI，可先轉回 draft：
  gh pr ready --undo {編號}
```

---

### 步驟 7：顯示結果與下一步

```
✅ PR #{編號} 已轉正：{標題}
🔗 {URL}

下一步：
1. 確認遠端 CI 全綠（gh pr checks {編號}）
2. 如需指派 Reviewer：gh pr edit {編號} --add-reviewer {帳號}
3. 合併後執行 /sti-cleanup #{Issue編號} 清理分支
   （worktree 模式：請先回到主 repo 目錄再執行）
```

## 注意事項

- 本指令**不會自動指派 Reviewer**，由使用者視需求手動執行 `gh pr edit --add-reviewer`。
- 本指令**不會建立新 commit 或 push**；若本地 CI 失敗需修正，請離開本指令流程自行處理後再重新執行。
- 若遠端 CI 失敗，建議用 `gh pr ready --undo` 先轉回 draft，修正期間的 commit 才不會再排隊跑 CI。
