執行以下步驟，互動式引導 Close GitHub Issue 的完整 SOP，**強制盤點所有留言、避免漏接**。

> **設計緣由**：2026-04-28 close Issue #332 時漏列「印表機主檔 Table 名稱統一」這條（dev-time Q1，已於 PR #387 處理但未在 close 摘要列入），因 Issue 累積跨多 PR / 多日的 thread 容易遺漏。本指令是 close issue 盤點 SOP 的**唯一完整定義**（`.claude/rules/sti-issue-close-checklist.md` 僅為全域提醒摘要）。

## 確認機制

| 使用者回覆 | 動作 |
|---------|------|
| 數字（如 `1`、`2`、`3`） | 執行對應選項 |
| 直接輸入文字 | 視為自訂內容（如自訂留言 / 補充說明） |
| `0` / `取消` | 停止並顯示「已取消。」 |

## 參數說明（$ARGUMENTS）

| 參數 | 說明 | 範例 |
|------|------|------|
| `#編號` 或 `編號` | 要 close 的 Issue 編號（必填） | `/sti-issue-close #332` |

---

## 執行步驟

### 步驟 1：解析參數 + 預檢

從 `$ARGUMENTS` 解析 Issue 編號（去除 `#` 符號）。若未傳入，停止並提示：「請提供 Issue 編號」。

執行：

```bash
gh issue view {編號} --json number,title,state,closedAt
```

- 若 `state == CLOSED`：顯示「⚠️ Issue #{編號} 已 closed（{closedAt}），是否需要補留言而非重新 close？」並提供選項：
  1. 補一條留言（不再 close，因已 closed）
  2. 取消
- 若 `state == OPEN`：繼續步驟 2

---

### 步驟 2：dump 所有留言 + 留言對照表（強制）

```bash
gh issue view {編號} --comments --json body,comments
```

把 issue body + 所有 comments 全部讀過，**禁止只看最後一條留言就動手**。

**逐則建立留言對照表**：

| # | 留言 ID / 時點 | 作者 | 主題（一句話）| 對應的 PR | 處理狀態 |
|---|--------------|------|-------------|----------|---------|
| 1 | (issue body) | ... | ... | ... | ... |
| 2 | comment-id-xxx | ... | ... | ... | ... |
| ... | | | | | |

**特別檢查（紅旗）**：

- ⚠️ Issue 累積 > 3 條留言：中段留言容易被忽略
- ⚠️ Issue 跨多個 PR（> 2 個）：早期 PR 的決策被忘
- ⚠️ Issue 跨日累積 > 3 天：早期 thread 容易看漏
- ⚠️ Issue 有 SA Open Questions（dev 開發前提的）：與 reviewer 後 review 留言混雜，前者最易漏
- ⚠️ Issue 有跨模組 / 跨 repo 處理：跨界處理不易追蹤
- ⚠️ reviewer 多輪 review：**最後一條留言 ≠ 全部問題清單**

向使用者展示對照表，請使用者確認「處理狀態」欄是否正確：

```
留言對照表如上，請確認：
  1. 全部已處理，無漏接 → 進入步驟 3 寫 close 摘要
  2. 有漏接，需先補處理（停止）
  3. 有疑慮，請我列出每則留言原文細看
```

選 `2` → 顯示漏接的留言摘要，停止指令；選 `3` → 展示原文後再回到此選單。

---

### 步驟 3：取得本 issue 的 5 條原始驗收條件

從步驟 2 的 issue body 解析「驗收條件」段落（通常是 `## 驗收條件` 或 `**Acceptance Criteria**`），列出所有 `- [ ]` / `- [x]` checkbox 項目。

對使用者展示：

```
偵測到 N 條驗收條件：
  1. [ ] AC 1 內容...
  2. [ ] AC 2 內容...
  ...

請逐一確認狀態（輸入 y/n/s 對應 ✅ 已達成 / ❌ 未達成 / 🔵 部分達成）：
```

如果 AC 未全勾選，提示「驗收條件未全達成，是否仍要 close？」並提供選項：
1. 仍要 close（標記未達成項為「部分達成」並寫入摘要）
2. 取消，先補完 AC

---

### 步驟 4：產生結構化 close 留言（強制模板）

依下列模板產生：

```markdown
## ✅ 全部處理完，本 issue 可 close

接續本 issue 累積的所有討論串，已於 PR #X1 / #X2 / ... 一次處理完畢。

## N 條原始驗收條件對應狀態

| # | 驗收條件 | 狀態 | 落地位置 |
|---|---------|------|---------|
| 1 | ... | ✅ | PR #... |
| 2 | ... | ✅ | PR #... |
...

## 跨 PR / 跨討論串處理摘要表

| 留言 / 時點 | 議題 | 處理 PR | 留言 ID | 狀態 |
|------------|------|--------|---------|------|
| ... | ... | ... | ... | ✅ |

## 實作與原 spec 的差異紀錄

差異 1: ...
差異 2: ...

## 補充說明（若有）

- 設計選擇理由
- 後續 follow-up issue 連結
```

向使用者展示草稿，請確認：

```
Close 留言預覽如上：

  1. 確認送出（將執行 gh issue comment + gh issue close）
  2. 編輯草稿
  3. 取消
```

選 `2`：使用者修改草稿後回到此選單；選 `1` 進入步驟 5。

---

### 步驟 5：執行 comment + close

```bash
gh issue comment {編號} --body "{草稿內容}"
gh issue close {編號} --reason completed
```

成功後顯示：

```
✅ Issue #{編號} 已 close
✅ Close 留言：https://github.com/{owner}/{repo}/issues/{編號}#issuecomment-{id}
```

---

### 步驟 6：close 後驗證（最後保險）

執行：

```bash
gh issue view {編號} --comments | tail -100
```

對照步驟 2 的留言對照表，確認沒有 ⚠️ 漏接警訊。若發現遺漏：

```
⚠️ 發現以下留言可能未被 close 摘要覆蓋：
  - 留言 #...（主題：...）

是否要補一條留言？
  1. 是，補留言
  2. 否，視為已涵蓋
```

選 `1` → 引導使用者輸入補充內容後 `gh issue comment`，不重新 close。

---

## 規則來源

本指令是 close issue 盤點 SOP 的唯一完整定義；`.claude/rules/sti-issue-close-checklist.md`（全域常駐）負責在未下指令時提醒走本流程。手動 close（不走本指令）時亦須遵循相同盤點步驟。
