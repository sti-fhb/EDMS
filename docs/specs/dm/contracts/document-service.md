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

> DM 與 ET 共用 `DP_USER`（平台模組 DP 定義），認證由平台模組 DP 以簡單 JWT 處理；本服務不另做帳號驗證。

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

## in-process Service 介面（ET 呼叫方式，**權威**）

依 `.claude/rules/sti-backend-boundaries.md`（API-First 隔離），ET 與 DM 同屬單一 backend，**ET 一律經 `app/services/__init__.py` 匯出之 in-process DM Service 呼叫，不打上述 HTTP 端點**（HTTP 端點掛 `app/dm/deps.py` 存取閘，要求呼叫者具至少一個 DM 角色，否則 403 `DM_AUTH_001`；ET 師生未必具 DM 角色會被擋）。上述 REST 路徑為 **DM 自身前端**使用、語意等價，僅供對照。

### 匯出

```python
# app/services/__init__.py（現僅匯出 DP 三個 Service，需新增 DM 門面）
from app.dm.integration.service import DmDocumentService   # 實作位置 SD 可定，建議 app/dm/integration/
```

### 類別與方法簽章

`DmDocumentService`：

| 方法 | 對應 | 簽章 | 回傳 |
|------|------|------|------|
| `get_current_by_doc_id` | SRVDM001 | `(db, doc_id: str)` | `DmCurrentVersion` |
| `list_training_documents` | SRVDM002 | `(db, *, category="TRAINING", keyword="", func_code=None)` | `list[DmDocItem]` |
| `read_file_for_reference` | 取檔（見下節）| `(db, *, doc_id: str, version_id: int)` | `DmFileContent` |

### 回傳型別（DTO）

```python
@dataclass(frozen=True)
class DmCurrentVersion:       # get_current_by_doc_id
    doc_id: str
    doc_name: str
    category_code: str
    current_version_id: int
    version_no: str
    file_name: str
    file_mime: str
    published_date: datetime
    status: str              # PUBLISHED / OBSOLETE
    obsolete: bool

@dataclass(frozen=True)
class DmDocItem:             # list_training_documents 之清單項目
    doc_id: str
    doc_name: str
    version_no: str
    published_date: datetime

@dataclass(frozen=True)
class DmFileContent:         # read_file_for_reference
    path: str               # 落地檔路徑；ET 以 FileResponse 回給學員，不自行解析路徑另作他用
    mime: str
    name: str
```

> DTO 欄位對應上方 REST JSON（camelCase → snake_case）；`list_training_documents` 之 `total` 由 `len(回傳 list)` 得出，不另包裝物件。

### 錯誤對映（in-process 丟 `AppError`，非 REST 字串）

| 上方 REST error | in-process `AppError`（status, error_code）|
|-----------------|-------------------------------------------|
| `DOC_NOT_FOUND` | 404, `DM_DOC_001`（查無此文件）|
| `NO_PUBLISHED_VERSION` | 409, `DM_DOC_013`（文件尚無已發布版本）|
| `INVALID_CATEGORY` | 400, `DM_DOC_010`（受控選項無效或已停用）|

> ET 端以 `AppError.error_code` 判斷；error_code 對齊 `docs/ref/error-codes.md`（`DM_DOC_013` 為本 US 新增）。

---

## 檔案內容取用（ET 學員取教材檔）

SRVDM001 只回 metadata，**不回檔案內容**。ET 學員端 ET05 呈現預覽 / 下載時，經 `read_file_for_reference(db, doc_id, version_id)` 取檔：

- **不掛 DM 角色閘**：此方法不做 DM 角色 / DM 可見性檢查（與 DM 自身 HTTP 取檔端點不同）。**授權由 ET 端自行判定後才呼叫**（學員須為該課程已加入且未移除、章節已解鎖）；DM 端信任 ET 已把關，只負責交檔。
- **僅限目前發布版**（決策 D-1）：`version_id` 必須等於該文件 `CURRENT_VERSION_ID`，否則 `AppError(403, DM_DOC_002)`。ET 教材恆取當前發布版，不需舊版。
- **不寫 `DM_DOC_READ` 閱讀紀錄**（決策 D-2）：ET 代學員取檔不計入 DM 閱讀統計（US13）；ET 學員之學習 / 閱讀由 ET 端自行統計，避免 DM KPI 混入 ET 情境。
- **實體檔缺失**回 `AppError(404, DM_DOC_001)`（統一 404、不外洩落地路徑）。

> **決策紀錄**：D-1（限目前版）、D-2（不寫閱讀紀錄）於 2026-08-20 交付前自檢（`/sti-sa-precheck dm us12`）採預設建議定案。若 ET 日後需「舊版取用」或「ET 閱讀計入 DM KPI」，另議擴充。

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
