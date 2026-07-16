# API Error Code 對照表

> **骨架（2026-07-09 建立）**：本檔隨各實作 task 增補——每張 issue 新增自己用到的錯誤碼，不一次寫全。
> 命名規範見 [`.claude/rules/sti-error-codes.md`](../../.claude/rules/sti-error-codes.md)。

## 格式說明

- **命名規則**：`{頂層模組}_{子功能}_{流水號}`
- **頂層模組（EDMS）**：`DP`（平台）/ `ET`（教育訓練）/ `DM`（文件管理）/ `COMMON`（跨模組通用）
- **子功能**：全大寫英文（如 `AUTH` / `USER` / `PARAM` / `MAIL`）
- **流水號**：三位數字 `001`~`999`，由 001 起**連續**編號（不跳號）
- **框架層 HTTP 錯誤**：`HTTP_{status_code}`（如 `HTTP_404`、`HTTP_405`）
- **回應格式**：

```json
{ "error_code": "DP_AUTH_001", "error_message": "帳號或密碼錯誤" }
```

由 `core/exceptions.py` 的 `AppError` + `main.py` 的 `app_error_handler` 統一處理。

### 新增流程

1. 於本檔對應模組表格加新列（流水號取該子功能區塊最大號 +1）
2. 實作處 `raise AppError(status_code=..., detail=..., error_code="DP_XXX_001")`

### 設計原則（安全）

- `error_message` 固定為**靜態字串**，**不嵌入動態值 / 欄位名稱**（防 Log Injection、不洩漏 schema）
- Pydantic 驗證失敗（`COMMON_422`）**不回傳欄位名稱或驗證細節**；完整錯誤只寫伺服器端 debug log

> **註**：`sti-error-codes.md` 規則檔的模組清單為 TBMS 沿用（含 BC/CP/TL/BS/MA），EDMS 實際只有 **DP / ET / DM / COMMON**；規則檔模組清單待另行對齊（follow-up）。

---

## COMMON — 跨模組通用

| error_code | HTTP | error_message |
|------------|------|---------------|
| COMMON_001 | 422 | 未提供任何更新欄位 |
| COMMON_002 | 422 | page 必須 >= 1 |
| COMMON_003 | 422 | limit 必須 >= 1 |
| COMMON_004 | 422 | limit 不得超過 100 |
| COMMON_005 | 400 | 不允許更新的欄位 |
| COMMON_422 | 422 | 請求格式驗證失敗 |
| COMMON_500 | 500 | Internal Server Error |

> **框架層 HTTP 錯誤**（非 AppError，如路由不存在 / Method Not Allowed）：error_code 為 `HTTP_{status_code}`（如 `HTTP_404`、`HTTP_405`）。

---

## DP — 平台模組

> 隨 Foundation / 各 DP US task 增補。子功能規劃：`AUTH`（登入 / JWT / 換發）、`USER`（帳號管理）、`PWD`（密碼策略 / 重設）、`PARAM`（系統參數）、`ROLE`（權限指派轉接）、`TEMPLATE`（通知範本）、`AUDIT`（稽核查詢）、`MAIL`（發信）、`SCHEDULE`（排程）。

| error_code | HTTP | error_message |
|------------|------|---------------|
| DP_AUTH_001 | 401 | 帳號或密碼錯誤 |
| DP_AUTH_002 | 401 | 登入憑證無效或已逾時，請重新登入 |
| DP_AUTH_003 | 401 | 已達單次登入時數上限，請重新登入 |
| DP_AUTH_004 | 403 | 帳號已停用 |
| DP_AUTH_005 | 403 | 帳號已鎖定 |

---

## ET — 教育訓練模組

> 隨各 ET US task 增補。

| error_code | HTTP | error_message |
|------------|------|---------------|
| _(待各 ET task 增補)_ | | |

---

## DM — 文件管理模組

> 隨各 DM US task 增補。

| error_code | HTTP | error_message |
|------------|------|---------------|
| _(待各 DM task 增補)_ | | |
