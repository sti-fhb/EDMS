執行以下步驟，互動式引導完成 git add → commit → push，並強制執行安全檢查。

## 確認機制

所有需要使用者確認的環節，一律提供**數字選項**，使用者輸入數字即可：

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如自訂 commit message） |
| `0` / `取消` | 停止並顯示「已取消。」 |

選填欄位若不填寫，請輸入「無」或 `skip`。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `all` | 自動 add 所有變更（排除敏感檔案） | `/sti-commit all` |
| 無參數 | 互動選擇要 add 的檔案 | `/sti-commit` |

---

## 執行步驟

### 步驟 1：顯示變更狀態

使用 Bash 工具執行：
```bash
git status
git diff --stat
```

整理並顯示：
- 目前分支名稱
- Staged 檔案清單
- Unstaged 檔案清單
- Untracked 檔案清單

---

### 步驟 2：安全檢查

使用 Bash 工具掃描變更檔案：

```bash
git diff --name-only
git ls-files --others --exclude-standard
```

逐一檢查以下項目：

**🚫 封鎖項目（發現則停止，不允許繼續）**：
- 檔名包含 `.env`、`.pem`、`id_rsa`、`*secret*`、`*credential*` 的檔案
- 顯示：「⛔ 發現敏感檔案：{檔名}，已停止。請確認 .gitignore 設定後再執行。」

**⚠️ 警告項目（發現則提示，詢問是否繼續）**：
- 程式碼中含有疑似硬編碼機密的字串（`sk-`、`password =`、`SECRET_KEY =`、`api_key =`）
- 使用 Bash 工具執行：
  ```bash
  git diff | grep -iE "(sk-|password\s*=|secret_key\s*=|api_key\s*=)"
  ```
- 若發現，顯示：
  ```
  ⚠️ 偵測到疑似硬編碼機密：
    1. 已確認安全，繼續
    2. 停止
  ```

**💡 提示項目（發現則提示，詢問是否繼續）**：
- `console.log` 殘留
- 使用 Bash 工具執行：
  ```bash
  git diff | grep "console.log"
  ```
- 若發現，顯示：
  ```
  💡 偵測到 console.log，建議移除後再 commit。
    1. 繼續
    2. 停止
  ```

---

### 步驟 3：選擇要加入的檔案

**若 `$ARGUMENTS` 為 `all`**：
自動選擇所有非敏感的變更檔案，顯示清單後直接進入步驟 4。

**若無參數**：
列出所有變更與 Untracked 檔案，格式如下：
```
請選擇要加入 commit 的檔案（輸入編號，多個以逗號分隔，全選請輸入 all）：

  1. [M] backend/app/modules/auth/router.py
  2. [M] backend/app/modules/auth/service.py
  3. [A] backend/app/modules/auth/schemas.py
  4. [?] .claude/commands/sti-commit.md

狀態說明：[M] 已修改  [A] 新增  [D] 刪除  [?] Untracked
```

等待使用者輸入後，顯示已選擇的檔案清單確認。

---

### 步驟 4：自動偵測關聯 Issue

使用 Bash 工具從 git log 掃描目前分支是否已有關聯 Issue：
```
git log main..HEAD --oneline | grep -oE "#[0-9]+" | head -1
```

- 若找到 Issue 編號（如 `#25`）→ 呼叫 `gh issue view {編號} --json number,title --jq '"#\(.number) \(.title)"'` 取得標題，顯示：「偵測到關聯 Issue：#25 {標題}，將自動帶入 commit message。」
- 若找不到 → 後續步驟詢問使用者手動輸入

---

### 步驟 5：填寫 Commit Message

詢問使用者 commit 類型（每次一個問題）：

```
請選擇 commit 類型：
1. feat     - 新功能
2. fix      - 修正 bug
3. refactor - 重構
4. docs     - 文件
5. test     - 測試
6. chore    - 雜項維護
7. perf     - 效能優化
```

選擇後詢問：「請輸入 commit 描述（簡短說明本次變更）：」

若步驟 4 已偵測到 Issue 編號，顯示：
```
關聯 Issue：#{編號}
  1. 使用此 Issue
  2. 自訂（直接輸入新編號）
  3. 不關聯
```
若步驟 4 未偵測到，詢問：「請輸入關聯 Issue 編號（如 25），無則輸入「無」：」

組合 commit message：
```
{type}: {描述}

[close #{Issue編號}]
```

---

### 步驟 6：預覽確認

顯示完整預覽：
```
## Commit 預覽

分支：{目前分支}
檔案：
  - {選擇的檔案 1}
  - {選擇的檔案 2}

Message：
  {type}: {描述}
  [close #{Issue編號}]
```

詢問使用者：
```
  1. 確認送出
  2. 修改（直接輸入新的 commit message）
```

---

### 步驟 7：執行 add + commit

使用 Bash 工具依序執行：
```
git add {選擇的檔案...}
git commit -m "{commit message}"
```

顯示 commit 結果（commit hash 與 message）。

---

### 步驟 8：詢問是否 push

詢問使用者：
```
  1. Push 到遠端
  2. 先跑 CI 驗證再 push
  3. 不 push
```

**選擇 `1`**：
- 使用 Bash 工具檢查分支是否有追蹤遠端：
  ```
  git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
  ```
- 若已有追蹤遠端 → 執行 `git push`
- 若為新分支（無追蹤遠端）→ 執行 `git push -u origin {分支名稱}`
- 顯示 push 結果與遠端 URL。

**選擇 `2`**：
- 使用 Bash 工具執行 `pnpm ci:quick`
- 若全部 PASSED → 自動執行 push（同選擇 1 的 push 邏輯）
- 若有 FAILED → 顯示失敗項目，提示使用者修正後重新執行 `/sti-commit`

**選擇 `3`**：
顯示：「Commit 已完成，未 push。需要時可執行 /sti-commit 或手動 push。」
