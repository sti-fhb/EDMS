# Service 契約：文件取用（DM → ET）

**編碼**: SRVDM001（依 DOC_ID 取當前發布版）、SRVDM002（取訓練教材分類文件清單）
**日期**: 2026-06-24
**對應 FR**: spec_us12 FR-001~004（跨模組教材引用）
**對應 UC**: UCDM12
**介接方向**: 教育訓練模組（ET）→ 文件管理模組（DM）
**類型**: 內部服務（SRV）— 模組間溝通

---

## 概述

ET 教材引用 DM「訓練教材」分類之文件。ET 端以 **SRVDM002** 取得可引用之文件清單（建立引用之下拉），以 **SRVDM001** 依已引用之 DOC_ID 取得文件**當前發布版本**之 metadata 與檔案位置（學員學習時取最新版）。DM 發布新版後 ET 自動取得最新版（無快取延遲）；DM 文件廢止後仍回傳廢止前最後發布版本並標示廢止旗標。

> DM 與 ET 共用 user table（SSO），認證由共用機制處理；本服務不另做帳號驗證。

---

## 端點

### SRVDM001 — 依 DOC_ID 取當前發布版

**方法**: GET
**路徑**: `/api/dm/documents/{docId}/current`

#### 請求參數

| 參數 | 型別 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| docId | VARCHAR(20) | Y | | 文件編號（DM-{分類碼}-{流水號}）|

#### 回應格式 — 成功

```json
{
  "docId": "DM-TRAINING-000007",
  "docName": "成分製備訓練教材",
  "categoryCode": "TRAINING",
  "currentVersionId": 1402,
  "versionNo": "v2.0",
  "fileName": "成分製備-v2.0.pdf",
  "filePath": "/dm-files/2026/DM-TRAINING-000007/v2.0.pdf",
  "fileMime": "application/pdf",
  "publishedDate": "2026-06-20T10:30:00",
  "status": "PUBLISHED",
  "obsolete": false
}
```

**HTTP 狀態碼**: 200

**欄位說明**：
- `currentVersionId` / `versionNo`：當前發布版（依 DM_DOCUMENT.CURRENT_VERSION_ID）；DM 發布新版後即回傳新版
- `status`：`PUBLISHED`（含廢止待簽核期間，仍對外有效）或 `OBSOLETE`
- `obsolete`：文件已廢止時為 `true`，但仍回傳廢止前最後發布版本之檔案位置（ET 端據此顯示「此文件已廢止」標籤）

#### 回應格式 — 失敗

```json
{ "error": "DOC_NOT_FOUND", "message": "查無此文件" }
```

**HTTP 狀態碼**: 404（文件不存在）/ 409（文件尚無已發布版本）/ 500

#### 錯誤代碼

| 代碼 | 說明 |
|------|------|
| DOC_NOT_FOUND | DOC_ID 不存在 |
| NO_PUBLISHED_VERSION | 文件存在但尚無已發布版本（仍為草稿 / 送審中）|

---

### SRVDM002 — 取訓練教材分類文件清單

**方法**: GET
**路徑**: `/api/dm/documents`

#### 請求參數

| 參數 | 型別 | 必填 | 預設 | 說明 |
|------|------|------|------|------|
| category | VARCHAR(10) | N | TRAINING | 分類碼；ET 教材引用固定為 `TRAINING`（訓練教材）|
| keyword | VARCHAR(100) | N | | 文件名稱關鍵字（模糊）|
| funcCode | VARCHAR(10) | N | | （選用）依關聯作業項目過濾 |

#### 回應格式 — 成功

```json
{
  "total": 2,
  "items": [
    { "docId": "DM-TRAINING-000007", "docName": "成分製備訓練教材", "versionNo": "v2.0", "publishedDate": "2026-06-20T10:30:00" },
    { "docId": "DM-TRAINING-000011", "docName": "用血回報訓練教材", "versionNo": "v1.0", "publishedDate": "2026-05-26T13:42:00" }
  ]
}
```

**HTTP 狀態碼**: 200

**欄位說明**：
- 僅回傳**有當前發布版本**之文件（草稿 / 送審中 / 已廢止不列）
- 預設僅「訓練教材」分類；ET 端下拉不顯示其他分類、不顯示已廢止文件

#### 回應格式 — 失敗

```json
{ "error": "INVALID_CATEGORY", "message": "分類碼不存在" }
```

**HTTP 狀態碼**: 400 / 500

#### 錯誤代碼

| 代碼 | 說明 |
|------|------|
| INVALID_CATEGORY | 指定分類碼不存在 |

---

## 處理邏輯

1. **SRVDM001**：依 docId 查 DM_DOCUMENT → 取 `CURRENT_VERSION_ID` 指向之 DM_DOC_VERSION（即現行 / 廢止前最後發布版，其版本 STATUS=PUBLISHED）；文件 STATUS=OBSOLETE 時 `obsolete=true`、仍回傳該版位置（廢止屬文件層、版本維持 PUBLISHED）；`CURRENT_VERSION_ID` 為 null（首版尚未發布）時回 NO_PUBLISHED_VERSION。
2. **SRVDM002**：查 DM_DOCUMENT where CATEGORY_CODE=category AND CURRENT_VERSION_ID 非空 AND STATUS in (PUBLISHED, PENDING_OBSOLETE)；依關鍵字 / funcCode 過濾；依發布時間 DESC 回傳。
3. DM 發布新版（核准並發布）即更新 CURRENT_VERSION_ID，故 ET 下次呼叫 SRVDM001 即取得最新版（無快取延遲）。
4. DM 文件廢止後 DM 端另發通知提示 ET 教師檢視引用（spec_us12 FR-003）。

---

## 對應資料表

- `DM_DOCUMENT`（DOC_ID / CATEGORY_CODE / CURRENT_VERSION_ID / STATUS）
- `DM_DOC_VERSION`（VERSION_NO / FILE_* / PUBLISHED_DATE / STATUS）

> 跨模組互動之認證、錯誤碼細則與 ET 端引用儲存方式，最終以雙方 plan 階段協調為準。
