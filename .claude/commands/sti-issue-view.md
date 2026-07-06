執行以下步驟，查看指定 GitHub Issue 的完整內容。

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要查看的 Issue 編號（必填）| `/sti-issue-view #22` 或 `/sti-issue-view 22` |

---

## 執行步驟

### 步驟 1：解析參數

從 `$ARGUMENTS` 解析 Issue 編號（去除 `#` 符號）。
若未傳入編號，提示使用者：「請提供 Issue 編號，例如：/sti-issue-view #22」，並停止執行。

---

### 步驟 2：取得 Issue 內容

使用 Bash 工具執行：

```bash
gh issue view {編號} --json number,title,state,assignees,labels,body,comments,createdAt,updatedAt
```

---

### 步驟 3：輸出結果

將結果整理成以下格式輸出：

```
---
## #{編號} {標題}

**狀態**：{狀態顏色 emoji + 狀態文字}
**負責人**：{GitHub 帳號（無則顯示 -）}
**Label**：{label 名稱（無則顯示 -）}
**建立時間**：{createdAt}
**最後更新**：{updatedAt}

---

### 說明
{body 完整內容}

---

### 留言（{留言數}則）
{若有留言，逐則顯示：留言者帳號 + 留言內容；若無則顯示「尚無留言」}

---
```

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
