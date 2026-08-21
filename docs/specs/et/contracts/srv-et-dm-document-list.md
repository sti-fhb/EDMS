# SRVDM002 — 取訓練教材分類文件清單（ET → DM）

**編碼**: SRVDM002（依 DM 端契約定案；2026-08-19 對齊，原 ET 側暫編號 SRVDM001 廢止）
**名稱**: 取「訓練教材」分類之可引用文件清單
**提供方**: 文件管理模組（DM）
**呼叫方**: 教育訓練模組（ET）
**權威來源**: [DM contracts/document-service.md](../../dm/contracts/document-service.md)（DM 為提供方，欄位與語意以 DM 端為準）
**建立日期**: 2026-06-09（2026-08-19 依 DM 定稿契約整份對齊）
**對應 US**: [spec_us3.md](../spec_us3.md) US3 教材管理

---

## 說明

ET 教師於 ET02 教材編輯視窗，從 DM「訓練教材」分類下拉選取既有文件建立引用。本 Service 由 DM 提供，回傳該分類下**有當前發布版本**之文件清單。

> **編碼對調注意**：本服務於 DM 端定稿契約為 **SRVDM002**；ET 側 2026-06-09 初稿曾誤標為 SRVDM001（與「依 DOC_ID 取當前發布版」對調）。2026-08-19 已對齊，SRVDM001 請見 [srv-et-dm-document-content.md](srv-et-dm-document-content.md)。

---

## 呼叫方式（實作層）

ET 與 DM 同屬單一 backend，跨模組呼叫**一律經 `app/services/__init__.py` 暴露的 DM Service**（in-process），不打 DM 的 HTTP 端點，per `.claude/rules/sti-backend-boundaries.md`（API-First 隔離）。

> **不可打 DM HTTP 端點之理由**：DM 全模組端點掛有存取閘（`app/dm/deps.py`），要求呼叫者至少具備一個 DM 角色，否則 403 `DM_AUTH_001`。**ET 教師 / 學員未必具 DM 角色**，經 HTTP 呼叫必被擋。改走 in-process Service 後，ET 端授權由 ET 自行判定（教師須為課程 owner）。
>
> DM 契約所列之 HTTP 路徑 `GET /api/dm/documents` 為 DM 自身前端使用，語意等價、供對照。

**待 DM 確認**：DM 尚未於 `app/services/__init__.py` 匯出 DM Service（目前僅匯出 DP 三個 Service）。ET 開工前需與 DM 議定匯出之 Service 名稱與方法簽章。

---

## 請求

| 參數 | 型別 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| category | VARCHAR(10) | N | `TRAINING` | 分類碼；ET 教材引用固定為 `TRAINING`（訓練教材）|
| keyword | VARCHAR(100) | N | | 文件名稱關鍵字（模糊）|
| funcCode | VARCHAR(10) | N | | （選用）依關聯作業項目過濾 |

> **無分頁**：DM 端本服務不提供 page / page_size。ET02 教材下拉如需分頁 / 捲動載入，於 ET 前端就回傳結果處理。

---

## 回應

```json
{
  "total": 2,
  "items": [
    { "docId": "DM-TRAINING-000007", "docName": "成分製備訓練教材", "versionNo": "v2.0", "publishedDate": "2026-06-20T10:30:00" },
    { "docId": "DM-TRAINING-000011", "docName": "用血回報訓練教材", "versionNo": "v1.0", "publishedDate": "2026-05-26T13:42:00" }
  ]
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| total | INT | 符合條件之文件總數 |
| items | array | 文件清單（陣列名為 `items`，非 `documents`）|
| items[].docId | **VARCHAR(20)** | 文件編號，格式 `DM-{分類碼}-{6位流水號}`；**非數值型**，ET 端一律以字串儲存與傳遞 |
| items[].docName | VARCHAR(200) | 文件名稱 |
| items[].versionNo | VARCHAR(20) | 當前發布版本號（撰寫者自由文字，如 `v2.0`）|
| items[].publishedDate | TIMESTAMP | 當前版本發布時間 |

> **本服務不回傳** `file_type` / `file_size_bytes`。ET02 下拉如需顯示副檔名 / 檔案大小，須於教師選定後另呼叫 [SRVDM001](srv-et-dm-document-content.md) 逐筆取得（或省略該顯示欄位）。

---

## 業務規則

- 僅回傳**有當前發布版本**之文件（草稿 / 送審中不列）
- DM 端過濾條件為 `CURRENT_VERSION_ID` 非空 AND `STATUS in (PUBLISHED, PENDING_OBSOLETE)`：**「廢止待簽核」（PENDING_OBSOLETE）之文件仍會出現於清單**（其仍為有效文件），僅 `OBSOLETE`（已廢止）不列
- 依發布時間 DESC 排序
- 分類碼由 DM 維護；ET 不得自訂分類

---

## 錯誤碼

| 代碼 | HTTP | 說明 |
|------|------|------|
| INVALID_CATEGORY | 400 | 指定分類碼不存在 |
| （內部錯誤）| 500 | DM 內部錯誤 |

> 本服務**無 401 / UNAUTHORIZED**：DM 契約明訂「DM 與 ET 共用 `DP_USER`，認證由平台模組 DP 以簡單 JWT 處理，本服務不另做帳號驗證」。ET 側 2026-06-09 初稿所列之 `UNAUTHORIZED` / `INVALID_PARAMS` 錯誤碼已移除。

---

## 依賴狀態（提醒 SD）

✅ **DM 端已交付**（#183 / PR #189，2026-08-20 合併）：`DmDocumentService` 已自 `app/services/__init__.py` 匯出，ET 端 `app/et/common/dm_client.py` 已接上真實 Service（stub 移除）。接線測試見 `tests/integration/et/test_et_dm_integration.py`。


---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-06-09 | 0.1 | 初稿，暫編號 SRVDM001；待 DM 模組正式編碼時對齊 |
| 2026-08-19 | 1.0 | 依 DM 定稿契約整份對齊：編碼 SRVDM001 → **SRVDM002**；`document_id` BIGINT → `docId` VARCHAR(20)；分類碼 `TRAINING_MATERIAL` → `TRAINING`；回應包裝 `documents` → `items`；移除分頁與 `file_type` / `file_size_bytes`；廢止語意改採 DM 三態（`PENDING_OBSOLETE` 仍列入）；移除 401 錯誤碼；補呼叫方式（in-process Service，不打 DM HTTP 端點）與依賴狀態 |
