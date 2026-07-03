執行以下步驟，列出此專案所有 GitHub Issue。

## 參數說明（$ARGUMENTS）

使用者可傳入以下參數（空白分隔，可組合使用）：

| 參數 | 說明 | 範例 |
|------|------|------|
| `open` | 只顯示 OPEN 的 Issue | `/sti-issue-list open` |
| `closed` | 只顯示 CLOSED 的 Issue | `/sti-issue-list closed` |
| `@帳號` | 只顯示指定負責人的 Issue | `/sti-issue-list @<github-帳號>` |
| `#label名稱` | 只顯示指定 Label 的 Issue | `/sti-issue-list #blocked` |

參數可組合，例如：`/sti-issue-list open #blocked` 顯示所有 OPEN 且有 blocked label 的 Issue。
未傳入任何參數時，顯示全部 Issue。

---

## 執行步驟

### 步驟 1：解析篩選參數

解析 `$ARGUMENTS`，判斷篩選條件：
- 含 `open` → 只顯示 OPEN
- 含 `closed` → 只顯示 CLOSED
- 含 `open` 與 `closed` → 兩者皆顯示
- 含 `@帳號` → 只顯示該帳號為負責人的 Issue
- 含 `#label名稱` → 只顯示含該 label 的 Issue
- 無參數 → 顯示全部

---

### 步驟 2：取得 Issue 清單

使用 Bash 工具執行：

```bash
gh issue list --limit 100 --state all --json number,title,state,assignees,labels,body
```

---

### 步驟 3：整理並輸出

依步驟 1 的篩選條件過濾結果，整理成以下格式輸出：

| 編號 | 標題 | 說明 | 狀態 | Label | 負責人 |
|------|------|------|------|-------|--------|
| #xx  | 標題 | body 第一行（無則顯示 -）| 狀態（含顏色 emoji）| label 名稱（無則顯示 -）| GitHub 帳號（無則顯示 -）|

狀態顏色規則：

| 條件 | 顯示 |
|------|------|
| OPEN，無負責人 | 🔴 OPEN |
| OPEN，有負責人 | 🟡 OPEN |
| CLOSED | 🟢 CLOSED |

Label 意義對照：

| Label | 意義 |
|-------|------|
| `blocked` | 等待其他 Issue 完成才能開始 |

---

### 步驟 4：統計摘要

顯示符合篩選條件的 OPEN 與 CLOSED 各幾筆。
