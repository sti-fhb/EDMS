# SRVDM002 — 取得 DM 文件最新版內容

> **暫編號**：本服務由 DM 模組提供；正式編碼待 DM 模組 spec 定稿時對齊。本文件先以「SRVDM002」佔位。

**編碼**: SRVDM002（暫）
**名稱**: 取得 DM 文件最新版本內容與廢止狀態
**提供方**: 文件管理模組（DM）
**呼叫方**: 教育訓練模組（ET）
**建立日期**: 2026-06-09
**對應 US**: [spec_us3.md](../spec_us3.md) US3 教材管理、[spec_us5.md](../spec_us5.md) US5 章節學習

---

## 說明

ET 學員於 ET05 章節學習頁開啟引用 DM 文件之教材時，由本 Service 取得該文件之**最新版本內容**（PDF 預覽用之檔案串流或 URL、檔案類型、檔案大小）以及**廢止狀態**（若已廢止仍可閱讀廢止前最後版本，per spec.md）。ET 教師於 ET02 編輯頁亦透過此 Service 判定文件廢止狀態以顯示警告 / 阻擋發布。

---

## 介接流程

```
1. ET 後端以 document_id 呼叫 SRVDM002
2. DM 查詢 DM_DOCUMENT + DM_DOCUMENT_VERSION，取得：
   a. 該文件之最新發布版本（或廢止前最後版本）
   b. 該文件之當前狀態（有效 / 廢止）
3. DM 回傳檔案內容（URL 或 base64 串流）+ 文件元資料 + 廢止狀態
4. ET 端：
   - 學員端：呈現文件內容（PDF 預覽或下載連結）；廢止時顯示「此文件已廢止」標籤
   - 教師端 ET02：若文件廢止則顯示警告，發布前阻擋
```

---

## 請求

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| document_id | BIGINT | Y | DM 文件主鍵 |
| return_mode | VARCHAR(10) | N | `URL`（回傳預簽 URL，預設）/ `STREAM`（回傳 base64 串流）|

---

## 回應

| 欄位 | 型別 | 說明 |
|------|------|------|
| document_id | BIGINT | 回顯 |
| document_name | VARCHAR(200) | 文件名稱 |
| version | VARCHAR(20) | 當前提供之版本號（最新版或廢止前最後版本）|
| is_deprecated | BOOLEAN | 是否已廢止；true 時 ET 教師端阻擋發布、學員端顯示「此文件已廢止」標籤 |
| deprecated_at | TIMESTAMP | 廢止時間（is_deprecated = true 時填入）|
| file_type | VARCHAR(10) | 副檔名（pdf / docx / xlsx / pptx 等）|
| file_size_bytes | BIGINT | 檔案大小 |
| content_url | VARCHAR(500) | 預簽 URL（return_mode = URL 時填入；有時效，由 DM 控制）|
| content_base64 | TEXT | base64 編碼之檔案內容（return_mode = STREAM 時填入）|

---

## 業務規則

- 已廢止文件**仍可閱讀**最後版本（per 跨模組共用規則）；但教師端 ET02 顯示警告、阻擋發布
- 預簽 URL 之有效期由 DM 端控制（建議 ≤ 30 分鐘）；過期後 ET 重新呼叫 SRVDM002
- 文件版本更新後 ET 不需快取；學員下次開啟章節時即取得最新版

---

## 錯誤碼

| 代碼 | HTTP | 說明 |
|------|------|------|
| DOCUMENT_NOT_FOUND | 404 | document_id 不存在 |
| INVALID_PARAMS | 400 | 必填欄位缺漏或格式錯誤 |
| UNAUTHORIZED | 401 | 呼叫方未通過認證 |
| INTERNAL_ERROR | 500 | DM 內部錯誤 |

---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-06-09 | 0.1 | 初稿，暫編號 SRVDM002；待 DM 模組正式編碼時對齊 |
