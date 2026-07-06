執行以下步驟，互動式建立 GitHub Pull Request。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容 |
| `0` / `取消` | 停止並顯示「已取消。」 |

選填欄位若不填寫，請輸入「無」或 `skip`。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#Issue編號` | 關聯的 Issue 編號（選填，自動帶入 `close #xx`）| `/sti-pr-create #25` |

---

## 執行步驟

### 步驟 1：取得分支資訊與同步檢查

使用 Bash 工具執行：

```bash
git branch --show-current
git log main..HEAD --oneline
```

接著檢查分支是否已同步 main（確保拿到最新的 CI pipeline 與共用程式碼）：

```bash
git fetch origin main
git log HEAD..origin/main --oneline
```

- 若有落後的 commit，顯示：
  ```
  ⚠️ 目前分支落後 main {N} 個 commit，建議先合併：
  git merge origin/main

  未合併 main 可能導致：
  - CI pipeline 缺失（不會自動跑測試）
  - 與其他 PR 的程式碼衝突
  - 共用規則或設定不一致

  1. 自動執行 merge
  2. 跳過（不合併）
  ```
  使用者選擇 `1` 後執行 `git merge origin/main`，若有衝突則提示手動解決後重新執行指令。

- 若已同步，顯示：「✅ 分支已同步 main。」

---

### 步驟 2：偵測關聯 Issue

**優先順序**：
- 若 `$ARGUMENTS` 有傳入 Issue 編號 → 直接使用
- 否則，從 git log 掃描 `close #xx` 找出 Issue 編號：
  ```bash
  git log main..HEAD --oneline | grep -oE "#[0-9]+" | head -1
  ```

找到 Issue 編號後，呼叫：

```bash
gh issue view {編號} --json number,title,body --jq '{number,title,body}'
```

從 Issue 資料自動預填：
- **PR 標題**：使用 Issue 標題（去除 `[Foundation]`、`[Phase X]` 前綴）
- **說明**：取 Issue body 中「## 任務說明」區塊內容
- **Test plan**：取 Issue body 中「## 驗收條件」區塊，轉為 `- [ ]` 清單

顯示：「已從 Issue #xx 自動帶入 PR 標題與說明。」

---

### 步驟 3：讀取 PR Template 並收集資訊

使用 Bash 工具讀取 PR template：

```bash
cat .github/pull_request_template.md
```

以 template 結構為 body 骨架，將蒐集到的資訊填入對應欄位：
- `## 對應 Issue` → 填入 `Closes #{Issue編號}`
- `## 變更說明` → 填入本次變更摘要（從 commit 歷史與 Issue 說明整理）
- `## 變更類型` → 勾選對應類型（`- [x]`）
- `## PR Checklist` → 保留所有項目為 `- [ ]`（由人工逐項確認）

接著逐步詢問以下資訊（每次一個問題）：

| 欄位 | 說明 | 預設值 |
|------|------|--------|
| 標題 | PR 標題（70 字以內）| 從 Issue 標題自動帶入 |
| 目標分支 | 合併目標（base branch）| `main` |
| 是否草稿 | `1` 草稿、`2` 一般 PR | 1（草稿）|
| Reviewer | 從可選帳號清單選擇（無則輸入「無」；**草稿時跳過不詢問**）| - |

⚠️ **預設建立 draft PR**：draft PR 期間的 commit 不觸發 CI（見 `.github/workflows/ci.yml` 的 `draft != true` 過濾），避免反覆修正造成 CI 排隊。轉正時機請見 `/sti-pr-ready`。

**Reviewer 詢問條件**：僅當使用者選擇「2 一般 PR」時才詢問 Reviewer；選擇草稿時跳過（轉正後由使用者自行 `gh pr edit --add-reviewer` 指派）。

詢問 Reviewer 時（僅一般 PR），先使用 Bash 工具取得可選帳號：

```bash
gh api repos/{owner}/{repo}/collaborators --jq '.[].login'
```

顯示格式：
```
請選擇 Reviewer（輸入帳號，無則輸入「無」）：
可選帳號：chanalin1229 / mengxuanchang / Sandra-168 / Sandra-888
```

---

### 步驟 4：顯示預覽並確認

收集完成後，顯示完整預覽：
- 標題、目標分支、草稿狀態、Reviewer
- 完整 body（以 template 骨架填入內容）

詢問使用者：
```
  1. 確認建立
  2. 需要修改（請說明）
```

---

### 步驟 5：建立 PR

使用者選擇 `1` 後，使用 Bash 工具執行，body 以 template 骨架為基礎填入。**草稿 PR 必須加 `--draft`，且不加 `--reviewer`**：

```bash
gh pr create --title "{標題}" --base {目標分支} --body "$(cat <<'EOF'
## 對應 Issue

Closes #{Issue編號}

## 變更說明

{本次變更摘要}

## 變更類型

- [ ] feat（新功能）
- [ ] fix（Bug 修復）
- [ ] refactor（重構）
- [ ] docs（文件）
- [x] {對應類型}（{說明}）
- [ ] chore（雜項）
- [ ] perf（效能優化）
- [ ] ci（CI/CD）

## PR Checklist

- [ ] 未直接 import 其他模組的 Repository 或 Model
- [ ] 未在 SQL 中跨模組 JOIN 其他模組的 table
- [ ] 若新增對外 Service，已更新 `services/__init__.py` 與 `__all__`
- [ ] 錯誤處理使用 `AppError`，不是自訂例外
- [ ] 刪除操作使用軟刪除（`is_deleted = TRUE`），非硬刪除
- [ ] API Response 格式符合規範（`data` + `meta`）
- [ ] 若新增 Table/Model，欄位遵守共用欄位規範（見 `sti-backend-modules.md` 的 BaseModel 說明）
- [ ] 有對應的 Unit Test
- [ ] 已通過 TypeScript type-check（`pnpm type-check`）
- [ ] Ruff / ESLint 無錯誤
- [ ] 無 `console.log` 殘留
- [ ] 已執行 Code Review（使用 Claude Code reviewer 或人工審查）

🤖 Generated with Claude Code
EOF
)" [--draft] [--reviewer {帳號}]
```

---

### 步驟 6：等待 CI 並檢查結果

**若本次建立的是草稿 PR**（步驟 3 選擇 `1` 草稿）：

不輪詢 CI，顯示下列訊息後直接跳到步驟 7：
```
📝 Draft PR 不觸發 CI（見 .github/workflows/ci.yml 的 draft != true 過濾）。

下一步：
1. 收到 Review 意見後執行 /sti-pr-review-fix #{PR編號} 修正
2. 修正完成、分支不再 commit 後執行 /sti-pr-ready #{PR編號} 轉為正式 PR
```

---

**若本次建立的是一般 PR**（步驟 3 選擇 `2` 一般 PR）：

PR 建立後，等待 CI 開始執行（約 15 秒），然後輪詢檢查狀態：

```bash
sleep 15 && gh pr checks {PR編號}
```

根據結果分為三種情況：

**情況 A：CI 全部通過**
```
✅ CI 全部通過！PR 已準備好接受 Review。
```

**情況 B：CI 仍在執行中**
```
⏳ CI 仍在執行中，目前狀態：
  - Backend Lint: ✅
  - Backend Unit Tests: ⏳ pending
  - ...

建議等 CI 跑完確認全綠後再請 Reviewer 審查。
```

**情況 C：CI 有失敗**
```
❌ CI 有失敗項目：
  - Backend Lint: ❌
  - Frontend Type Check: ❌

建議先修復 CI 問題再請人 Review。可執行：
  gh run view {run_id} --log-failed    # 查看失敗原因
```
- 建議轉為草稿以避免反覆 commit 觸發 CI 排隊：
  ```
    1. 轉為草稿（推薦，修正期間不跑 CI）
    2. 維持正式 PR
  ```
  - 選擇 `1` 後執行 `gh pr ready --undo {PR編號}`

---

### 步驟 7：顯示結果

最後顯示 PR 編號、URL 與下一步指引。

**若為草稿 PR**：
```
✅ Draft PR 已建立：#{編號} {標題}
🔗 {URL}

下一步：
1. 收到 Review 意見後執行 /sti-pr-review-fix #{PR編號} 進行修正
2. 修正完成、分支不再 commit 後執行 /sti-pr-ready #{PR編號} 轉為正式 PR
3. PR 合併後執行 /sti-cleanup #{Issue編號} 清理分支
```

**若為一般 PR**：
```
✅ PR 已建立：#{編號} {標題}
🔗 {URL}

下一步：
1. 確認 CI 全部通過（綠燈）
2. 等待 Reviewer 審查
3. 收到意見後執行 /sti-pr-review-fix #{PR編號} 進行修正
```
