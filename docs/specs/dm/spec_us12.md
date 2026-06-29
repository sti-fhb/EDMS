# User Story 12 — 跨模組教材引用（DM ↔ ET）（UCDM12）

> 返回總檔：[spec.md](spec.md) | 模組：文件管理（DM）

## User Story

ET 教師於教材編輯時引用 DM「訓練教材」分類之文件（依 DOC_ID）；DM 端發布新版本後，ET 教材自動取得最新發布版（依 CURRENT_VERSION_ID），不需 ET 端手動更新。DM 文件被廢止後，ET 端仍呈現廢止前最後發布版本，並通知 ET 教師檢視是否移除引用。

**Priority**: P3 — 跨模組加值整合；DM 自身運作不依賴此，惟為 ET 教材與規範文件單一來源之關鍵連結。

**Independent Test**: ET 教師於教材編輯從 DM「訓練教材」分類下拉選一文件建立 DOC_ID 引用；DM 編輯者對該文件發布新版後，ET 學員開啟章節即取得最新版；DM 廢止該文件後，ET 仍呈現廢止前最後版本且 ET 教師收到檢視通知。

### Acceptance Scenarios

1. **Given** ET 教師於教材編輯介面，**When** 從 DM「訓練教材」分類下拉選取既有文件，**Then** 建立對該 DOC_ID 之引用（下拉僅顯示「訓練教材」分類之有效文件）
2. **Given** 學員於 ET 章節學習，**When** 開啟引用之教材，**Then** 系統依 DOC_ID 自動取得 DM 當前發布版本之檔案
3. **Given** DM 編輯者上傳新版本並完成簽核發布（[spec_us6.md](spec_us6.md)），**When** ET 端引用該 DOC_ID 之教材被開啟，**Then** 自動取得最新發布版（依 CURRENT_VERSION_ID），ET 端不需手動更新、無快取延遲
4. **Given** DM 文件被核准廢止，**When** ET 教材仍引用該 DOC_ID，**Then** ET 端仍呈現廢止前最後發布版本；DM 端通知 ET 教師檢視是否移除引用（DM-MSG-DM12-001）
5. **Given** DM 文件處於廢止待簽核期間，**When** ET 端取用，**Then** 仍取得廢止前最後發布版本（因文件仍對外有效）

## Functional Requirements

- **FR-001**: DM MUST 提供「訓練教材」分類文件供 ET 引用；ET 依 DOC_ID 建立引用，且 ET 端下拉**僅顯示「訓練教材」分類之有效文件**（不含其他分類、不含已廢止）
- **FR-002**: ET 取用 MUST 依 DOC_ID 解析至 DM 之當前發布版本（CURRENT_VERSION_ID）；DM 發布新版後 ET 自動取得最新版（無快取延遲、不需 ET 手動更新）
- **FR-003**: DM 文件被廢止後，ET 端 MUST 仍能呈現廢止前最後發布版本；DM 端 MUST 通知 ET 教師檢視是否移除引用
- **FR-004**: DM 文件處於廢止待簽核期間，ET 端 MUST 取得廢止前最後發布版本（文件仍對外有效）
- **FR-005**: 跨模組取用之請求 / 回應格式由 `specs/dm/contracts/` 規範（待 `/speckit.plan` 階段產出）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DM-MSG-DM12-001 | 提示 | 本文件已廢止，請通知引用此文件之 ET 教師檢視是否移除引用 | FR-003 廢止後通知 |

> 本 US 多為系統間自動行為，使用者可見訊息較少；ET 端之教材編輯 / 廢止標示行為詳見 ET 模組 spec「DM 文件廢止之 UI 規則」。

## 前置依賴

- DM 文件發布 / 廢止狀態由 [spec_us6.md](spec_us6.md) 決定；分類「訓練教材」由 [spec_us1.md](spec_us1.md) 維護
- 介接契約待 `/speckit.plan` 於 contracts/ 產出
