執行以下步驟，列出此專案所有 GitHub Pull Request。

## 參數說明（$ARGUMENTS）

使用者可傳入以下參數（空白分隔，可組合使用）：

| 參數 | 說明 | 範例 |
|------|------|------|
| `open` | 只顯示 OPEN 的 PR | `/sti-pr-list open` |
| `closed` | 只顯示 CLOSED/MERGED 的 PR | `/sti-pr-list closed` |
| `@帳號` | 只顯示指定作者的 PR | `/sti-pr-list @<github-帳號>` |
| `draft` | 只顯示草稿 PR | `/sti-pr-list draft` |

參數可組合，例如：`/sti-pr-list open @<github-帳號>` 顯示 Sandra-168 的所有 OPEN PR。
未傳入任何參數時，顯示全部 PR。

---

## 執行步驟

### 步驟 1：解析篩選參數

解析 `$ARGUMENTS`，判斷篩選條件：
- 含 `open` → 只顯示 OPEN
- 含 `closed` → 只顯示 CLOSED/MERGED
- 含 `draft` → 只顯示草稿
- 含 `@帳號` → 只顯示該帳號的 PR
- 無參數 → 顯示全部

---

### 步驟 2：取得 PR 清單

使用 Bash 工具執行：

```bash
gh pr list --limit 100 --state all --json number,title,state,author,assignees,headRefName,baseRefName,isDraft,createdAt,mergedAt
```

---

### 步驟 3：整理並輸出

依篩選條件過濾，整理成以下格式輸出：

| 編號 | 標題 | 狀態 | 分支 | 作者 | 負責人 |
|------|------|------|------|------|--------|
| #xx  | 標題 | 狀態（含顏色 emoji）| `head → base` | 作者帳號 | 負責人帳號（無則 -）|

狀態顏色規則：

| 條件 | 顯示 |
|------|------|
| OPEN，非草稿 | 🟢 OPEN |
| OPEN，草稿 | ⚪ DRAFT |
| MERGED | 🟣 MERGED |
| CLOSED（未合併） | 🔴 CLOSED |

---

### 步驟 4：統計摘要

顯示符合篩選條件的各狀態各幾筆。
