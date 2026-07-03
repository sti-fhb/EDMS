顯示所有 sti-* 指令的說明。

## 執行步驟

直接輸出以下內容，不需要執行任何工具：

---

# STI 指令總覽

## Issue 管理

| 指令 | 說明 | 範例 |
|------|------|------|
| `/sti-issue-list` | 列出所有 Issue，支援篩選參數 | `/sti-issue-list open @<github-帳號>` |
| `/sti-issue-view` | 查看單筆 Issue 完整內容（含留言） | `/sti-issue-view #22` |
| `/sti-issue-create` | 互動式逐步填寫並建立 Issue | `/sti-issue-create` |
| `/sti-issue-edit` | 互動式修改 Issue 標題、body 或 label | `/sti-issue-edit #22` |
| `/sti-issue-close` | Close Issue 完整 SOP：強制 dump body + 全部留言逐則盤點，產出驗收對應表 | `/sti-issue-close #22` |

### sti-issue-list 篩選參數

| 參數 | 說明 |
|------|------|
| `open` | 只顯示 OPEN |
| `closed` | 只顯示 CLOSED |
| `@帳號` | 只顯示指定負責人 |
| `#label名稱` | 只顯示含指定 label |

---

## PR 管理

| 指令 | 說明 | 範例 |
|------|------|------|
| `/sti-pr-list` | 列出所有 PR，支援篩選參數 | `/sti-pr-list open @<github-帳號>` |
| `/sti-pr-view` | 查看單筆 PR 詳情（含 review 狀態與留言） | `/sti-pr-view #24` |
| `/sti-pr-create` | 互動式建立 PR（預設草稿），自動帶入 PR checklist | `/sti-pr-create #25` |
| `/sti-pr-ready` | 將 Draft PR 轉為正式 PR，可選擇是否先跑本地 CI | `/sti-pr-ready #25` |
| `/sti-pr-review` | 對指定 PR 進行完整 Code Review，依等級分類問題，可提交 Review 到 GitHub | `/sti-pr-review #24` |
| `/sti-verify-review` | 驗證 Review 報告正確性，自動偵測 STALE（基於舊版程式碼）與 HALLUCINATION（AI 幻覺） | `/sti-verify-review #24` |
| `/sti-pr-review-fix` | 回應 PR Review 意見：分類問題、確認計畫、執行修正、commit & push、通知 Reviewer | `/sti-pr-review-fix #24` |

### sti-pr-list 篩選參數

| 參數 | 說明 |
|------|------|
| `open` | 只顯示 OPEN |
| `closed` | 只顯示 CLOSED/MERGED |
| `draft` | 只顯示草稿 |
| `@帳號` | 只顯示指定作者 |

---

## 開發工作流

| 指令 | 說明 | 範例 |
|------|------|------|
| `/sti-plan` | 實作前盤點：讀規格 → 判複雜度選模板 → 寫規劃留言 → 幻覺檢查列出真 SA Q → review 後 post 到 Issue | `/sti-plan #25` |
| `/sti-implement` | 完整開發流程：讀取 Issue → 建分支 → 規劃 → TDD → Code Review | `/sti-implement #25` |
| `/sti-commit` | 互動式 git add → commit → push，含安全檢查 | `/sti-commit` 或 `/sti-commit all` |

---

## SA 文件發布

| 指令 | 說明 | 範例 |
|------|------|------|
| `/sti-sa-publish` | SA 一條龍文件發布：開分支 → 選檔案 → commit → push → 開 PR → merge | `/sti-sa-publish` 或 `/sti-sa-publish et` |
| `/sti-sa-precheck` | 規格交付前自檢：逐項檢查 spec / data-model / contracts / wireframe 後再交給 SD 開發 | `/sti-sa-precheck` |
| `/sti-sa` | 載入 SA 工作規則（編碼規則、需求整理流程、Speckit 作業流程） | `/sti-sa` |

---

## Alembic 工具

| 指令 | 說明 | 範例 |
|------|------|------|
| `/sti-alembic-check` | 檢查 head 狀態：單一 head 顯示最近 3 版；多 head 顯示 content 衝突分析並引導執行 merge | `/sti-alembic-check` |
| `/sti-alembic-log` | 顯示 revision 鏈最近 N 版，含 UUID、檔名、說明對照 | `/sti-alembic-log` 或 `/sti-alembic-log 10` |

**使用時機**：`git pull` 後、建新 migration 前、開 PR 前。

---

## 清理工具

| 指令 | 用途 | 使用時機 |
|------|------|----------|
| `/sti-cleanup` | 單次清理：移除指定 worktree + 刪除 feature 分支 + 同步 main | 每次 PR 合併後執行 |
| `/sti-branch-cleanup` | 批次清理：掃描所有 `[gone]` 分支 + review worktree + 孤立 worktree | 定期維護（如每週一次） |

---

## 共用規則

| 指令 | 說明 |
|------|------|
| `/sti-help` | 顯示所有 sti-* 指令的總覽說明（即本頁） |
| `/sti-common` | 查看所有 STI 指令的確認機制、狀態顏色規則與共用規範 |

---

## 典型開發流程

```
1. /sti-issue-create          → 建立 Issue
2. /sti-plan #xx              → 實作前盤點（讀規格、選模板、寫規劃留言、列 SA Q）
3. /sti-implement #xx         → 完整開發流程（含建分支、規劃、TDD、Code Review、Commit、Draft PR）
4. /sti-pr-review #xx         → 審查 PR（含 worktree + 幻覺防護）
5. /sti-verify-review #xx     → 驗證 Review 正確性（偵測 STALE / HALLUCINATION）
6. /sti-pr-review-fix #xx     → 修正 Review 意見（只修 CONFIRMED）
7. /sti-pr-ready #xx          → Review 結束、分支不再 commit 後轉為正式 PR
8. /sti-cleanup #xx           → PR 合併後清理 worktree 與 feature 分支
```

> - PR 一律以 **Draft** 建立：draft 期間的 commit 不會觸發 CI（見 `.github/workflows/ci.yml` 的 `draft != true` 過濾），減少 CI 排隊。
> - `/sti-implement` 步驟 13 可直接 commit + 建 draft PR，也可結束後手動 `/sti-commit` + `/sti-pr-create`。
> - 批次清理失效分支與 review worktree：`/sti-branch-cleanup`。

## SA 文件發布流程

```
1. /sti-sa                → 載入 SA 工作規則
2. （修改 docs/ 文件）
3. /sti-sa-publish [模組]  → 一條龍發布（開分支 → commit → push → PR → merge）
```
