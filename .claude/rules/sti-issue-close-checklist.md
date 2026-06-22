---
description: Close GitHub Issue 前的強制檢查 SOP，避免漏接早期留言；執行 gh issue close 前載入
---

# Close GitHub Issue 強制檢查 SOP

## 為何需要此規則

GitHub Issue 經過多個 PR、多輪 review 累積留言時，容易發生：

- 只看**最後一條 reviewer 留言**就動手寫 close 摘要
- 漏掉早期的 SA Open Questions / dev 開發前提問
- 跨 PR 處理的項目沒被反向參照進 close 摘要
- 多日累積的 thread 被忽略中段內容

**真實案例**：2026-04-28 close Issue #332 時漏列「印表機主檔 Table 名稱統一（LB_PRINTERCODE → LB_PRINTER）」這條 — 此項已於 PR #387 處理，但因該討論橫跨數日且發生在開發前盤點階段（不在 reviewer 最後留言中），close 時沒被列入摘要。事後使用者指出才補留言。

---

## 強制 4 步驟（執行 `gh issue close` 前必走）

### Step 1：dump 所有留言

```bash
gh issue view <ISSUE_NUMBER> --comments
```

**禁止只看最後一條留言就動手**。要把 issue body + 所有 comments 全部讀過。

### Step 2：建立留言對照表

逐則留言（不限 reviewer，含 dev / SA / 第三方）標註：

| 留言 ID / 時間 | 作者 | 主題 | 對應的 PR | 處理狀態 | 是否在 close 摘要內 |
|--------------|------|------|----------|---------|---------------------|
| 4334067058 | alvinSTI | 收尾 5 ACs + 5 差異 | #394 | ✅ Closed | ✅ |
| 4334070893 | alvinSTI | 硬刪除理由補充 | (本則)| ✅ | ✅ |
| 4334130822 | alvinSTI | 補 Q1 表名統一 | #387 | ✅ | ⚠️ **漏接事後補** |

⚠️ 任何「處理狀態 ✅ 但不在 close 摘要內 ❌」都是**漏接警訊**，必須補入摘要。

### Step 3：強制使用結構化 close 留言模板

```markdown
## ✅ 全部處理完，本 issue 可 close

接續本 issue 累積的所有討論串，已於 PR #X1 / #X2 / ... 一次處理完畢。

## N 條原始驗收條件對應狀態

| # | 驗收條件 | 狀態 | 落地位置 |
|---|---------|------|---------|

## 跨 PR / 跨討論串處理摘要表（強制）

| 留言 / 時點 | 議題 | 處理 PR | 留言 ID | 狀態 |
|------------|------|--------|---------|------|

## 實作與原 spec 的差異紀錄

差異 1: ...
差異 2: ...

## 補充說明（若有）

- 設計選擇理由
- 後續 follow-up issue 連結
```

### Step 4：close 後驗證

```bash
# 1. 把 close 摘要再讀一次
gh issue view <N> --comments | tail -100

# 2. 對照 Step 2 的對照表，確認沒有 ⚠️ 漏接警訊
# 3. 若有遺漏 → 立即補留言（如本案 comment 4334130822）
```

---

## 紅旗：以下情境**特別容易漏接**，多看兩眼

| 情境 | 風險 |
|------|------|
| Issue 累積 > 3 條留言 | 中段留言容易被忽略 |
| Issue 跨多個 PR（> 2 個）| 早期 PR 的決策被忘 |
| Issue 跨日累積 > 3 天 | 早期 thread 容易看漏 |
| Issue 有 SA Open Questions（dev 開發前提問）| 與 reviewer 後 review 留言混雜，前者最易漏 |
| Issue 有跨模組 / 跨 repo 處理 | 跨界處理不易追蹤 |
| reviewer 多輪 review | **最後一條留言 ≠ 全部問題清單** |

---

## 與 `/sti-issue-close` Slash Command 的關係

slash command `/sti-issue-close` 會自動執行本規則的 Step 1~4，將盤點過程互動化、不易跳步。手動 close 時亦應遵循此 SOP。

## 與 `gh issue close` 的關係

`gh issue close` 是最終動作，**不是流程起點**。執行此命令前應已完成 Step 1~3 的盤點與摘要撰寫。
