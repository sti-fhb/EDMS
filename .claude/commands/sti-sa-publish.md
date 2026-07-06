執行以下步驟，引導 SA 成員完成文件異動的一條龍發布流程：開分支 → 選檔案 → commit → push → 開 PR → merge。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如自訂分支名稱、commit message） |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 適用對象

此指令專為 SA（系統分析師）設計，用於將 `docs/` 下的文件異動（需求文件、使用案例、規格文件等）發布至主線。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| 無參數 | 互動引導完整流程 | `/sti-sa-publish` |
| `模組代碼` | 預帶模組資訊（如 bc、bs、cp 等） | `/sti-sa-publish bc` |

---

## 執行步驟

### 步驟 1：同步最新 main

使用 Bash 工具執行：

```bash
git fetch origin main
git status
```

若目前不在 `main` 分支，顯示：「目前在 `{分支名稱}` 分支，此指令需從 `main` 開始。請先切換：`git checkout main`」並停止。

確認在 `main` 後，執行：

```bash
git pull --rebase origin main
```

- 成功 → 顯示：「✅ 已同步最新 main。」
- 若有衝突 → 顯示：「⚠️ pull --rebase 有衝突，請手動解決後重新執行。」並停止。

---

### 步驟 2：顯示異動檔案清單

使用 Bash 工具執行：

```bash
git status --short
```

整理並顯示異動檔案（分類為：新增、修改、刪除）：

```
📄 偵測到以下異動：
  新增：
    docs/requirements/RQET.md
  修改：
    docs/_refs/10-教育訓練文件管理模組.md
    docs/use-cases/et/usecases.md
  刪除：
    （無）
```

若無任何異動，顯示：「沒有需要發布的變更。」並停止。

---

### 步驟 3：建立分支

根據 `$ARGUMENTS` 與異動檔案自動推薦分支名稱：
- 規則：`docs/{模組代碼}-{異動類型}`，例如：
  - `docs/et-rq-update`（教育訓練模組需求更新）
  - `docs/dm-usecase-add`（文件管理使用案例新增）
  - `docs/sa-spec-update`（跨模組規格更新）
- 若無法判斷，建議 `docs/sa-update-{YYYYMMDD}`（用今天日期）

詢問使用者：

```
建議分支名稱：docs/{推薦名稱}
  1. 使用此名稱
  2. 自訂名稱
```

選擇 `2` 時，使用者輸入自訂名稱（格式建議：`docs/xxx`）。

確認後執行：

```bash
git checkout -b {分支名稱}
```

顯示：「✅ 已建立並切換至分支 `{分支名稱}`。」

---

### 步驟 4：選擇要 commit 的檔案

顯示完整異動清單（含檔案路徑），詢問使用者：

```
請選擇要包含在此次 commit 的檔案：
  1. 全部檔案
  2. 選擇部分檔案
```

- 選擇 `1`：`git add` 所有異動的 `docs/` 檔案（排除非 docs 的異動）
  ```bash
  git add docs/
  ```
  若有 `docs/` 以外的異動，另外列出並詢問是否一併加入。

- 選擇 `2`：逐一詢問每個檔案是否加入（`y` / `n`），依使用者回答執行 `git add {檔案}`。

執行完畢後，顯示 staged 狀態：

```bash
git diff --cached --stat
```

---

### 步驟 5：撰寫 commit message

根據異動檔案自動推薦 commit message：
- 修改需求文件 → `docs: 更新 {模組} 需求文件`
- 修改使用案例 → `docs: 更新 {模組} 使用案例`
- 新增規格文件 → `docs: 新增 {模組} 規格文件`
- 混合修改 → `docs: 更新 {模組} SA 文件`

詢問使用者：

```
建議 commit message：docs: {推薦訊息}
  1. 使用此訊息
  2. 自訂訊息
```

選擇 `2` 時，使用者輸入自訂訊息（格式建議：`docs: {說明}`）。

確認後執行：

```bash
git commit -m "{commit message}"
```

顯示：「✅ Commit 完成。」

---

### 步驟 6：Push 分支

執行：

```bash
git push -u origin {分支名稱}
```

- 成功 → 顯示：「✅ 已 push 至遠端分支 `{分支名稱}`。」
- 失敗 → 顯示錯誤訊息並停止。

---

### 步驟 7：建立 Pull Request

自動產生 PR 標題與 body，詢問使用者確認：

**PR 標題**：`docs: {commit message 去掉 "docs: " 前綴}`

**PR Body**：

```
## 變更說明

{根據 commit message 與異動檔案整理的說明}

## 異動檔案

{列出所有 staged 的檔案路徑}

## 驗收條件

- [ ] 文件內容符合 `docs/_refs/` 中的 source of truth
- [ ] 編號格式正確（RQ/UC 編號不重整、不重複）
- [ ] 跨模組引用正確

🤖 Generated with Claude Code（/sti-sa-publish）
```

詢問使用者：

```
PR 預覽：
  標題：{標題}
  目標分支：main

  1. 確認建立 PR
  2. 修改標題
  3. 取消
```

確認後執行：

```bash
gh pr create \
  --title "{PR標題}" \
  --base main \
  --body "$(cat <<'EOF'
{body內容}
EOF
)"
```

顯示 PR 編號與 URL。

---

### 步驟 8：嘗試合併 PR

詢問使用者：

```
是否立即合併此 PR？
  1. 是，立即合併
  2. 否，留待人工審閱後合併
```

選擇 `2` → 顯示完成摘要（跳至步驟 9，不執行合併）。

選擇 `1` → 執行：

```bash
gh pr merge {PR編號} --merge --delete-branch
```

根據結果：

**情況 A：合併成功**

```
✅ PR 已合併至 main，遠端分支已刪除。
```

接著同步本地：

```bash
git checkout main && git pull origin main && git branch -d {分支名稱}
```

顯示：「✅ 本地已切回 main 並同步最新版本。」

**情況 B：合併有衝突**

```
⚠️ 合併發生衝突，無法自動合併。

請通知負責人（Sandra-168）協助解決衝突：
  PR URL：{PR URL}

衝突解決方式：
  1. 在 GitHub 上使用 Web Editor 解決衝突
  2. 或執行以下指令在本地解決：
     git fetch origin main
     git merge origin/main
     # 手動解決衝突後：
     git add .
     git commit
     git push origin {分支名稱}

PR 保留開啟中，待衝突解決後重新合併。
```

停止，不繼續。

---

### 步驟 9：顯示完成摘要

```
## 發布完成！

✅ 分支：{分支名稱}
✅ Commit：{commit message}
✅ PR：#{PR編號} {PR標題}
🔗 {PR URL}
{若已合併 → ✅ 已合併至 main}
{若未合併 → ⏳ 待合併（PR 開啟中）}

異動檔案：
{列出所有發布的檔案}
```
