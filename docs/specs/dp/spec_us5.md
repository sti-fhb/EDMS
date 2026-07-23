# User Story 5 — 系統參數與清單維護（UCDP006）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-params）

## User Story

作為 ET 或 DM 管理者，我要於 DP 後台維護系統參數與清單定義（平台級共用、模組級按前綴過濾），以便全平台與各模組的可配置行為有單一維護入口。

**Priority**: P1 — 全平台參數與清單定義之單一入口；ET / DM 業務下拉、產碼、檢核之資料來源。

**Independent Test**: ET 管理者僅見 `DP_`（平台級）與 `ET_` 前綴項、看不到 `DM_`；修改參數即時生效；`DETAIL_LOCK` 鎖定碼之碼值不可改；模組經唯讀查詢服務讀到最新啟用中清單。

### Acceptance Scenarios

1. **Given** ET 管理者進入系統參數 / 清單頁，**When** 頁面載入，**Then** 顯示平台級（無前綴 `DP_`）與 `ET_` 前綴之參數與清單；`DM_` 前綴項**不顯示**；DM 管理者反之；兼具兩模組管理者身分者兩者皆見
2. **Given** 管理者選取**參數**（如密碼策略、鎖定次數 / 時間、token TTL、閒置逾時、發信調校；模組級如影片大小、催辦門檻、排程時間）並編輯值，**When** 伺服器端驗證合法（型別 / 值域），**Then** 寫入 `DP_PARAM`、記錄異動稽核、即時生效（DP-MSG-PARAMS-004）
3. **Given** 管理者編輯**平台級**參數，**When** 進入編輯，**Then** 顯示警告「此為平台級參數，變更將影響全平台」（DP-MSG-PARAMS-005）後才可儲存
4. **Given** 管理者維護**清單定義**（文件分類、func_name、標籤名稱、可見對象值、DM 檢索標籤等；一個 `PARAM_ID` 下多筆 `PARAM_KEY`），**When** 新增 / 改名 / 啟用 / 停用清單項，**Then** 儲存並記錄稽核；**不開放刪除**（淘汰改停用）
5. **Given** 清單項屬 `DETAIL_LOCK` 標記之鎖定碼（如文件分類碼），**When** 嘗試修改碼值，**Then** 阻擋並提示（DP-MSG-PARAMS-002）；僅可改名稱或停用
6. **Given** 輸入之參數值不合法（型別錯誤 / 超出值域），**When** 儲存，**Then** 阻擋並提示（DP-MSG-PARAMS-001）
7. **Given** ET 管理者以直接呼叫 API 之方式存取 `DM_` 前綴項，**When** 請求到達，**Then** 伺服器端拒絕（DP-MSG-PARAMS-003，非僅前端過濾）
8. **Given** ET / DM 模組透過唯讀查詢服務讀取自己前綴之定義，**When** 清單項剛被停用，**Then** 模組端下拉即時反映（僅列啟用中項；既有引用之顯示由模組自理）

## Functional Requirements

- **FR-DP-US5-01**: 全平台參數與清單定義 MUST 統一存 `DP_PARAM_M/D`，以 `PARAM_ID` 前綴（無前綴 `DP_` 平台級 / `ET_` / `DM_` 模組級）區分歸屬；清單型以一個 `PARAM_ID` 下多筆 `PARAM_KEY` 表達
- **FR-DP-US5-02**: 維護頁 MUST 按模組過濾——模組級項僅該模組管理者可見可改（互不可見）；平台級項兩管理者皆可見可改；過濾 MUST 於伺服器端 enforce（直接呼叫 API 之越權一律拒絕）
- **FR-DP-US5-03**: 參數值儲存前 MUST 於伺服器端驗證合法性（型別 / 值域 / 必填）；不合法 MUST 拒絕
- **FR-DP-US5-04**: 清單項 MUST 支援新增 / 改名 / 啟用 / 停用；MUST NOT 開放刪除；`DETAIL_LOCK` 標記之碼建立後 MUST NOT 允許修改碼值（僅名稱 / 停用）
- **FR-DP-US5-05**: 平台 MUST 提供唯讀查詢服務供各模組讀取自己前綴之定義；讀取後之業務規則套用（分類碼嵌入 DOC_ID、func_name 唯一手冊檢核、`IS_ALL` 展開與自動邀請等）歸各模組
- **FR-DP-US5-06**: 所有參數 / 清單異動 MUST 寫入 `DP_AUDIT_LOG`（含異動前後值）並即時生效
- **FR-DP-US5-07**: 編輯平台級參數 MUST 先顯示影響全平台之警告

## 參數型別 / 值域驗證規則（FR-DP-US5-03 落地）

> **驗證規則存放**：主檔參數（`DP_PARAM_M`）為種子固定集、維護 UI **不新增主檔**（僅編輯值 / 維護清單項），故 FR-03 之型別 / 值域驗證規則以**程式碼側 registry 按 `PARAM_ID` + `PARAM_KEY` 維護**（非存於 `DP_PARAM_M` 之欄位）；不合法回 DP-MSG-PARAMS-001。以下為**平台級**參數之規則；模組級（`ET_` / `DM_`）參數值域由各模組規格定義。

### 平台級 VALUE 參數（多鍵參數組，PARAM_TYPE=VALUE）

| PARAM_ID | PARAM_KEY | 型別 | 值域 | 依據 |
|----------|-----------|------|------|------|
| `JWT` | `ACCESS_TTL_MIN` | 正整數（分）| 1–15 | spec 明載（含敏感資料系統 ≤ 15 分）|
| `JWT` | `RENEW_MAX_HOURS` | 正整數（時）| 1–24 | 建議（單日上限）|
| `PWD_POLICY` | `MIN_LEN` | 正整數 | 8 ≤ 值 ≤ `ADMIN_MIN_LEN` | spec 明載（一般 8）|
| `PWD_POLICY` | `ADMIN_MIN_LEN` | 正整數 | ≥ `MIN_LEN`（預設 12）| spec 明載（特權 12）|
| `PWD_POLICY` | `CHAR_TYPES` | 正整數 | 1–4（大小寫 / 數字 / 符號 4 類）| spec 明載 |
| `PWD_POLICY` | `HISTORY_COUNT` | 非負整數 | 0–24（預設 3）| 建議 |
| `PWD_POLICY` | `EXPIRY_DAYS` | 正整數（天）| 1–90 | spec 明載（最短 1、最長 90）|
| `PWD_POLICY` | `EXPIRY_REMIND_DAYS` | 正整數（天）| 1 ≤ 值 < `EXPIRY_DAYS`（預設 7）| 建議（須早於到期）|
| `LOGIN` | `FAIL_LOCK_COUNT` | 正整數 | ≥ 1（預設 5，建議 3–10）| spec 明載（預設 5）|
| `LOGIN` | `LOCK_MINUTES` | 正整數（分）| ≥ 1（預設 30）| spec 明載 |
| `LOGIN` | `RESET_TOKEN_TTL_MIN` | 正整數（分）| ≥ 1（預設 30）| spec 明載 |
| `LOGIN` | `EMAIL_CHANGE_TTL_MIN` | 正整數（分）| ≥ 1（預設 30）| spec 明載 |
| `LOGIN` | `IDLE_DISABLE_DAYS` | 正整數（天）| ≥ 1（預設 90）| spec 明載 |
| `MAIL` | `RATE_PER_MIN` | 正整數 | ≥ 1（預設 60）| 建議 |
| `MAIL` | `RETRY_MAX` | 非負整數 | 0–10（預設 5）| 建議 |
| `MAIL` | `RETRY_INTERVAL_MIN` | 正整數（分）| ≥ 1（預設 2）| 建議 |

### 跨欄位一致性（同 PARAM_ID 內）

- `PWD_POLICY.ADMIN_MIN_LEN` ≥ `PWD_POLICY.MIN_LEN`
- `PWD_POLICY.EXPIRY_REMIND_DAYS` < `PWD_POLICY.EXPIRY_DAYS`

### LIST 型（清單定義）之驗證

- `ACTION_TYPE` 等平台級清單、`ET_` / `DM_` 清單：新增 / 改名時 `PARAM_KEY`（碼）非空且同 `PARAM_ID` 內唯一、`PARAM_VALUE`（名稱）非空；`DETAIL_LOCK=true` 者碼值建立後不可改（DP-MSG-PARAMS-002）

> 「建議」值域為 SD 實作之 sanity guard 上限；型別 / 下限 / 跨欄位規則為硬性檢核。若業務需調整「建議」上限，實作時回報 SA 更新本表。

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-PARAMS-001 | 錯誤 | 參數值不合法，請確認格式與值域 | FR-DP-US5-03 驗證失敗 |
| DP-MSG-PARAMS-002 | 錯誤 | 此代碼已鎖定，不可修改代碼值（僅可修改名稱或停用）| FR-DP-US5-04 鎖定碼 |
| DP-MSG-PARAMS-003 | 錯誤 | 無權限維護此模組之參數 | FR-DP-US5-02 越權 |
| DP-MSG-PARAMS-004 | 成功 | 已儲存並即時生效 | FR-DP-US5-06 完成 |
| DP-MSG-PARAMS-005 | 警告 | 此為平台級參數，變更將影響全平台（ET 與 DM）| FR-DP-US5-07 平台級編輯 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1 / US7）
- 參數 / 清單之初始種子資料（平台級 `JWT` / `PWD_POLICY` / `LOGIN` / `MAIL`、模組級各項）於 data-model / migration 階段定義
- 各模組讀取後之業務規則落地由 ET / DM 實作（跨模組）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §系統參數與清單定義
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP006
- 共用規則：[spec.md](spec.md) §定義 vs 關聯分層、§模組過濾與共用項
- 參數清單：[`_refs/09-平台模組.md`](../../_refs/09-平台模組.md) §5 可配置參數與清單
