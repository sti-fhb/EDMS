---
description: API Error Code 命名與新增規範，寫後端或登記新錯誤碼時載入
paths:
  - "backend/app/**/*.py"
  - "docs/ref/error-codes.md"
---

# API Error Code 規範

## 命名格式

`{頂層模組}_{子功能}_{流水號}`

- 頂層模組：`DP` / `BC` / `CP` / `TL` / `BS` / `MA` / `COMMON`
- 子功能：全大寫英文（如 `AUTH` / `USER` / `SITE` / `APIKEY`）
- 流水號：三位數字 `001`~`999`，由 001 起連續編號

框架層 HTTP 錯誤用 `HTTP_{status_code}`（如 `HTTP_404`）。

## 新增流程

1. 於 `docs/ref/error-codes.md` 對應模組表格加新列
2. 流水號取該子功能區塊最大號 +1
3. 實作處用 `raise AppError(status_code=..., detail=..., error_code="DP_XXX_001")`

## 禁止

- 頂層模組不在清單內（如 `EXT_`、`API_`）
- 流水號跳號（`DP_AUTH_001` 之後直接跳 `004`）
- 自訂 Exception class
- error_message 嵌入動態值或欄位名稱（防 Log Injection、不洩露 schema）

## 回應格式

```json
{ "error_code": "DP_AUTH_001", "error_message": "帳號或密碼錯誤" }
```

由 `core/exceptions.py` 的 `AppError` + `main.py` 的 `app_error_handler` 統一處理。
