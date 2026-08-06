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
| COMMON_429 | 429 | 操作過於頻繁，請稍後再試 |
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
| DP_AUTH_006 | 403 | 需要模組管理者權限 |
| DP_AUTH_007 | 401 | 查無此帳號，請先註冊 |
| DP_AUTH_008 | 401 | 密碼錯誤 |
| DP_AUTH_009 | 403 | 請先變更密碼後再繼續 |
| DP_AUTH_010 | 401 | 此帳號尚未完成 Email 驗證，請至信箱點驗證連結或重新寄送 |
| DP_PWD_001 | 422 | 密碼長度不足 |
| DP_PWD_002 | 422 | 密碼複雜度不足 |
| DP_PWD_003 | 422 | 不可使用近期用過的密碼 |
| DP_PWD_004 | 422 | 密碼長度超過上限 |
| DP_PWD_005 | 400 | 連結已失效，請重新申請 |
| DP_PWD_006 | 422 | 舊密碼不正確 |
| DP_USER_001 | 409 | 此 Email 已被註冊，請直接登入或使用忘記密碼 |
| DP_USER_002 | 422 | 兩次輸入之密碼不一致 |
| DP_USER_003 | 400 | 驗證連結無效 |
| DP_USER_004 | 400 | 驗證連結已失效，請重新申請 |
| DP_USER_005 | 409 | 此 Email 註冊處理中，請稍後再試或直接登入 |
| DP_USER_006 | 403 | 無法停用或鎖定自己的帳號 |
| DP_USER_007 | 409 | 此 Email 已被使用 |
| DP_USER_008 | 404 | 查無此帳號 |
| DP_USER_009 | 404 | 查無此邀請 |
| DP_USER_010 | 409 | 此 Email 已有待啟用邀請，請改用重寄 |
| DP_MAIL_001 | 404 | 通知範本不存在 |
| DP_MAIL_002 | 422 | 收件人數超過單次上限 |
| DP_MAIL_003 | 403 | 系統信不可停用或刪除（主旨與內文可編輯）|
| DP_MAIL_004 | 409 | 內容已被他人修改，請重新載入後再儲存 |
| DP_MAIL_005 | 403 | 無權限維護此模組之範本 |
| DP_PARAM_001 | 422 | 參數值不合法，請確認格式與值域 |
| DP_PARAM_002 | 403 | 此代碼已鎖定，不可修改代碼值 |
| DP_PARAM_003 | 403 | 無權限維護此模組之參數 |
| DP_PARAM_004 | 404 | 查無此參數 |
| DP_PARAM_005 | 409 | 清單項代碼已存在 |
| DP_PARAM_006 | 400 | 此參數不支援清單項維護 |
| DP_SCHED_001 | 404 | 排程作業不存在 |
| DP_SCHED_002 | 422 | cron 表達式不合法 |

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
| DM_ROLE_001 | 403 | 無法停用自己之管理者角色 |
| DM_REVIEW_001 | 422 | 指定審核者不可為文件撰寫者本人 |

> `DM_ROLE_001`（US1 自我保護）：DM 之 `assign_roles_audiences` 轉接層回呼（`../specs/dp/contracts/module-callbacks.md` §3）於 operator 取消自己之管理者角色時 raise；DP 端統一映射為 `DP-MSG-ROLES-001` 呈現（見 spec_us7 FR-06）。
