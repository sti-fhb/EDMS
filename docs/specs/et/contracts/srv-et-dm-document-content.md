# SRVDM001 — 依 DOC_ID 取文件當前發布版（ET → DM）

**編碼**: SRVDM001（依 DM 端契約定案；2026-08-19 對齊，原 ET 側暫編號 SRVDM002 廢止）
**名稱**: 依 DOC_ID 取得文件當前發布版本之 metadata 與檔案位置，並判定廢止狀態
**提供方**: 文件管理模組（DM）
**呼叫方**: 教育訓練模組（ET）
**權威來源**: [DM contracts/document-service.md](../../dm/contracts/document-service.md)（DM 為提供方，欄位與語意以 DM 端為準）
**建立日期**: 2026-06-09（2026-08-19 依 DM 定稿契約整份對齊）
**對應 US**: [spec_us3.md](../spec_us3.md) US3 教材管理、[spec_us5.md](../spec_us5.md) US5 章節學習

---

## 說明

ET 於兩個時點依已引用之 `docId` 向 DM 取文件**當前發布版本**：

- **學員端 ET05**：開啟引用 DM 文件之教材時，取得當前發布版之 metadata 與檔案，呈現預覽 / 下載；文件已廢止時仍可閱讀廢止前最後發布版本，並顯示「此文件已廢止」標籤
- **教師端 ET02**：判定引用文件之廢止狀態，顯示警告並於發布前阻擋

DM 發布新版後 ET 下次呼叫即取得最新版（無快取延遲）。

> **編碼對調注意**：本服務於 DM 端定稿契約為 **SRVDM001**；ET 側 2026-06-09 初稿曾誤標為 SRVDM002（與「取訓練教材分類文件清單」對調）。2026-08-19 已對齊，SRVDM002 請見 [srv-et-dm-document-list.md](srv-et-dm-document-list.md)。

---

## 呼叫方式（實作層）

同 [SRVDM002](srv-et-dm-document-list.md#呼叫方式實作層)：一律經 `app/services/__init__.py` 暴露的 DM Service（in-process），不打 DM 的 HTTP 端點（DM 存取閘 `app/dm/deps.py` 要求呼叫者具 DM 角色，ET 學員未必具備）。

DM 契約所列之 HTTP 路徑 `GET /api/dm/documents/{docId}/current` 為 DM 自身前端使用，語意等價、供對照。

---

## 請求

| 參數 | 型別 | 必填 | 說明 |
|------|------|------|------|
| docId | **VARCHAR(20)** | Y | 文件編號，格式 `DM-{分類碼}-{6位流水號}`（如 `DM-TRAINING-000007`）；**非數值型** |

> ET 側 2026-06-09 初稿之 `return_mode`（URL / STREAM）**已廢除**——DM 端本服務不提供該參數，檔案取得方式見下方「檔案內容之取得」。

---

## 回應

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

| 欄位 | 型別 | 說明 |
|------|------|------|
| docId | VARCHAR(20) | 回顯 |
| docName | VARCHAR(200) | 文件名稱 |
| categoryCode | VARCHAR(10) | 分類碼（ET 教材恆為 `TRAINING`）|
| currentVersionId | BIGINT | 當前發布版之版本 ID（**取檔案時必須帶此值**）|
| versionNo | VARCHAR(20) | 當前發布版本號 |
| fileName | VARCHAR | 檔名（供下載時之顯示名）|
| filePath | VARCHAR | DM 儲存路徑；**ET 不得直接以此路徑讀檔**（見下方）|
| fileMime | VARCHAR | MIME 類型（供 ET 判定可否 inline 預覽）|
| publishedDate | TIMESTAMP | 當前版本發布時間 |
| status | VARCHAR(20) | `PUBLISHED`（含廢止待簽核期間，仍對外有效）或 `OBSOLETE` |
| obsolete | BOOLEAN | 已廢止時為 `true`，但**仍回傳廢止前最後發布版本**之位置；ET 據此顯示「此文件已廢止」標籤、教師端阻擋發布 |

> **DM 不回傳** `file_size_bytes` 與廢止時間。ET 側 2026-06-09 初稿之 `is_deprecated` / `deprecated_at` / `file_type` / `file_size_bytes` / `content_url` / `content_base64` 欄位**皆已移除**：廢止判定改用 `obsolete` + `status`，副檔名由 `fileName` / `fileMime` 推得。若 ET 畫面確需顯示廢止時間或檔案大小，須另與 DM 議定擴充。

---

## 檔案內容之取得

本服務**只回 metadata，不回檔案內容**。ET 學員端 ET05 呈現 PDF 預覽 / 下載時：

- **不得**以回應之 `filePath` 直接讀檔——違反模組邊界（`.claude/rules/sti-backend-boundaries.md`），且 DM 正在強化 storage-root 路徑穿越圍籬（DM Issue #160）
- 應以 `docId` + `currentVersionId` 經 DM 提供之檔案存取能力取檔；DM 現有端點為 `GET /api/dm/documents/{docId}/versions/{versionId}/file?disposition=preview|download`

⚠ **待 DM 議定（開工前必須有結論）**：DM 現有檔案端點掛有 DM 存取閘（要求至少一個 DM 角色，否則 403 `DM_AUTH_001`），**ET 學員多半無 DM 角色會被擋**。需請 DM 於 `app/services/__init__.py` 另暴露不掛 DM 角色閘之檔案讀取 Service，改由 ET 自行判定 ET 端授權（學員須為該課程已加入且未移除之學員、章節已解鎖）。此外 DM 端點對「舊版下載」回 403、download 會寫 `DM_DOC_READ` 閱讀紀錄，ET 取檔是否計入該紀錄亦須一併確認。

---

## 業務規則

- 恆取 `DM_DOCUMENT.CURRENT_VERSION_ID` 指向之版本；DM 發布新版後 ET 下次呼叫即取得最新版（ET 不快取）
- 文件廢止屬**文件層**，其版本仍維持 `PUBLISHED`：`obsolete=true` 時仍回傳該版位置，學員仍可閱讀
- 教師端 ET02 於 `obsolete=true` 時顯示警告，並於課程發布檢核時阻擋（per spec.md 發布檢核「無引用之廢止 DM 文件」）

---

## 錯誤碼

| 代碼 | HTTP | 說明 |
|------|------|------|
| DOC_NOT_FOUND | 404 | `docId` 不存在 |
| NO_PUBLISHED_VERSION | 409 | 文件存在但尚無已發布版本（仍為草稿 / 送審中）|
| （內部錯誤）| 500 | DM 內部錯誤 |

> ET 側初稿之 `DOCUMENT_NOT_FOUND` / `INVALID_PARAMS` / `UNAUTHORIZED` 已改為上表（DM 端定義）。本服務不另做帳號驗證（認證由平台 DP 之 JWT 處理）。

---

## 依賴狀態（提醒 SD）

✅ **DM 端已交付**（#183 / PR #189，2026-08-20 合併）：`DmDocumentService` 已自 `app/services/__init__.py` 匯出，ET 端 `app/et/common/dm_client.py` 已接上真實 Service（stub 移除）。接線測試見 `tests/integration/et/test_et_dm_integration.py`。


---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-06-09 | 0.1 | 初稿，暫編號 SRVDM002；待 DM 模組正式編碼時對齊 |
| 2026-08-19 | 1.0 | 依 DM 定稿契約整份對齊：編碼 SRVDM002 → **SRVDM001**；`document_id` BIGINT → `docId` VARCHAR(20)；移除 `return_mode` / `content_url` / `content_base64`（DM 只回 metadata）；`is_deprecated` / `deprecated_at` → `obsolete` + `status`；移除 `file_type` / `file_size_bytes`；錯誤碼改採 DM 定義（含 `NO_PUBLISHED_VERSION`）；新增「檔案內容之取得」章節並標示 DM 存取閘擋 ET 學員之待議事項；補呼叫方式與依賴狀態 |
