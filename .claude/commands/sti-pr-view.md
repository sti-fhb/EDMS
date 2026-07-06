執行以下步驟，查看指定 GitHub Pull Request 的完整內容。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要查看的 PR 編號（必填）| `/sti-pr-view #24` 或 `/sti-pr-view 24` |

---

## 執行步驟

### 步驟 1：解析參數

從 `$ARGUMENTS` 解析 PR 編號（去除 `#` 符號）。
若未傳入編號，提示使用者：「請提供 PR 編號，例如：/sti-pr-view #24」，並停止執行。

---

### 步驟 2：取得 PR 內容

使用 Bash 工具執行：

```bash
gh pr view {編號} --json number,title,state,author,assignees,reviewRequests,reviews,headRefName,baseRefName,isDraft,body,comments,createdAt,updatedAt,mergedAt,mergeable
```

---

### 步驟 3：輸出結果

將結果整理成以下格式輸出：

```
---
## #{編號} {標題}

**狀態**：{狀態顏色 emoji + 狀態文字}
**分支**：`{headRefName}` → `{baseRefName}`
**作者**：{author}
**負責人**：{assignees（無則顯示 -）}
**Reviewer**：{reviewRequests 中的帳號（無則顯示 -）}
**建立時間**：{createdAt}
**最後更新**：{updatedAt}
**合併時間**：{mergedAt（未合併則顯示 -）}
**可合併**：{mergeable 狀態}

---

### 說明
{body 完整內容}

---

### Review 狀態（{review 數}則）
{逐則顯示：reviewer 帳號 + 狀態（APPROVED / CHANGES_REQUESTED / COMMENTED）+ 留言摘要；若無則顯示「尚無 Review」}

---

### 留言（{留言數}則）
{逐則顯示：留言者帳號 + 留言內容；若無則顯示「尚無留言」}

---
```

狀態顏色規則：

| 條件 | 顯示 |
|------|------|
| OPEN，非草稿 | 🟢 OPEN |
| OPEN，草稿 | ⚪ DRAFT |
| MERGED | 🟣 MERGED |
| CLOSED（未合併） | 🔴 CLOSED |
