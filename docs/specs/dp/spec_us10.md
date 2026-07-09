# User Story 10 — 操作記錄查詢（稽核）（UCDP007，共用項）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P2 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-audit）

## User Story

作為 ET 或 DM 管理者，我要以多條件查詢全平台操作記錄（含 ET / DM 資安稽核事件）並匯出 CSV，以便進行資安稽核與異常追查。

**Priority**: P2 — 稽核**寫入**於各 US 內建（不依賴本 US）；查詢介面可於核心作業之後交付。

**Independent Test**: 以操作者 + 期間起訖 + 操作類別查得對應紀錄並展開異動前後值；匯出 CSV 內容與查詢結果一致；介面無任何刪除 / 修改功能。

### Acceptance Scenarios

1. **Given** ET 或 DM 管理者進入稽核查詢頁，**When** 以多條件（操作者、期間**起訖**、模組、操作類別 LOGIN / LOGOUT / CREATE / UPDATE / DELETE）查詢，**Then** 列出符合之 `DP_AUDIT_LOG` 紀錄（後端分頁、依時間倒序）；稽核為共用項，**兩管理者皆可查全部**（含登入等不分模組事件）
2. **Given** 查詢結果列表，**When** 展開單筆明細，**Then** 顯示完整欄位：操作者、時間（至秒）、功能 / 模組代碼、操作類別、來源 IP、異動對象、異動前後值（JSONB）
3. **Given** 查詢結果，**When** 點「匯出 CSV」，**Then** 依當前查詢條件匯出全部符合紀錄
4. **Given** 查無符合紀錄，**When** 查詢完成，**Then** 顯示空狀態提示（DP-MSG-AUDIT-001）
5. **Given** 任何使用者（含管理者）檢視本頁，**When** 尋找刪除 / 修改功能，**Then** 無此功能——日誌 append-only，不可於介面竄改 / 刪除
6. **Given** ET / DM 模組發生資安事件（帳號 / 角色權限 / 系統操作異動），**When** 事件寫入，**Then** 統一寫入同一張 `DP_AUDIT_LOG`，於本頁可查；**業務歷程**（DM 文件變更 / 閱讀、ET 學習 / 作答）不在此（留各模組）
7. **Given** 非管理者之一般使用者，**When** 嘗試存取本頁或查詢 API，**Then** 伺服器端拒絕（DP-MSG-AUDIT-002）

## Functional Requirements

- **FR-DP-US10-01**: 稽核查詢 MUST 為共用項——ET / DM 管理者皆可查全部；一般使用者 MUST NOT 可存取（僅授權使用者可存取單一日誌機制）
- **FR-DP-US10-02**: 系統 MUST 提供多條件查詢（操作者、期間起訖、模組、操作類別）與後端分頁列表；明細 MUST 含異動前後值（JSONB）
- **FR-DP-US10-03**: 系統 MUST 提供依查詢條件之 CSV 匯出
- **FR-DP-US10-04**: `DP_AUDIT_LOG` MUST 為 append-only——介面與 API MUST NOT 提供刪除 / 修改；日誌完整性以雜湊等方式確保；異動須特定授權人員（DB 層）並留軌跡
- **FR-DP-US10-05**: 日誌 MUST 至少涵蓋：更改密碼、登入成功 / 失敗、系統存取成功 / 失敗、帳號建立 / 停用、角色 / 權限修改、密碼重置、參數 / 清單 / 範本異動；欄位含使用者 ID（非個資型）、時間至秒、功能 / 資源名稱、執行結果 / 事件描述、網路來源與目的位址
- **FR-DP-US10-06**: 日誌 MUST 保留至少 1 年以上；容量失效時自動因應（如覆寫最舊）並留軌跡；每日備份與容量告警屬 IT 維運範圍（不屬系統功能）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-AUDIT-001 | 提示 | 查無符合條件之紀錄 | FR-DP-US10-02 空結果 |
| DP-MSG-AUDIT-002 | 錯誤 | 無權限存取操作記錄 | FR-DP-US10-01 越權 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1 / US7）
- 各 US 之稽核寫入（US1–US9、US11 內建）與 ET / DM 資安事件寫入（跨模組，契約見 contracts/）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §操作記錄（稽核）
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP007
- 共用規則：[spec.md](spec.md) §稽核（操作記錄）規則
