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
| COMMON_503 | 503 | 系統忙碌中，請稍後再試 |

> **`COMMON_503`**：密碼運算（bcrypt）之併發閘負載卸除（#214）。同時進行中的運算達門檻時
> 立即拒絕，避免請求在等待期間持續佔用 DB 連線。屬**暫時性**錯誤，前端可提示稍後重試；
> 勿用於一般系統錯誤（那是 `COMMON_500`）。

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
| DP_USER_011 | 409 | 此 Email 已有待完成的帳號啟用程序，請至信箱收取信件完成啟用 |
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
| DP_ROLE_001 | 403 | 無權限維護此模組之角色指派 |
| DP_ROLE_002 | 403 | 無法取消自己的管理者角色 |
| DP_ROLE_003 | 404 | 查無此模組或尚未提供角色管理 |

---

## ET — 教育訓練模組

> 隨各 ET US task 增補。下列為 ET 提供予平台 DP 之回呼介面所需（2026-08-19 #181 定案，見 [`../specs/et/contracts/srv-et-dp-module-callbacks.md`](../specs/et/contracts/srv-et-dp-module-callbacks.md)）；ET 模組尚未實作，實作時依此登記使用。

| error_code | HTTP | error_message |
|------------|------|---------------|
| ET_AUTH_001 | 403 | 需要教育訓練模組權限 |
| ET_ROLE_001 | 403 | 無法停用自己之管理者角色 |
| ET_ROLE_002 | 422 | 指定之受訓單位標籤無效或未啟用 |
| ET_ROLE_003 | 422 | 指定之角色代碼無效 |
| ET_TAG_001 | 422 | 內建標籤不可停用或改名 |
| ET_TAG_002 | 409 | 受訓單位標籤名稱已存在 |
| ET_TAG_003 | 404 | 查無此受訓單位標籤或項目類別 |
| ET_TAG_004 | 422 | 受訓單位標籤名稱不合法 |
| ET_LOCK_001 | 409 | 資料已被其他使用者修改，請重新載入後再試 |

> `ET_ROLE_001`（US1 自我保護）：ET 之 `assign` 轉接層回呼（[`../specs/dp/contracts/module-callbacks.md`](../specs/dp/contracts/module-callbacks.md) §3 / SRVET003）於 operator 取消自己之管理者角色時 raise；DP 端統一映射為 `DP-MSG-DP06-001` 呈現（見 dp/spec_us7 FR-06），命名依 DP 之「以 `_ROLE_001` 結尾判別」約定。
>
> `ET_TAG_001` / `002` / `003`（SRVET004 受控主檔轉接層）：比照 DM 之 `DM_CATALOG_001~003`，依 HTTP 狀態碼拆為三支——`001` 業務保護（422，「全體」等內建標籤不可停用 / 改名，伺服器端拒絕；DP 後台之前端隱藏僅為 UX）、`002` 名稱重複（409）、`003` 查無（404）。**不得共用單一代碼**，否則 DP 端 UI 無法單靠 error_code 分辨情境、只能解析訊息文字。

---

## DM — 文件管理模組

> 隨各 DM US task 增補。

| error_code | HTTP | error_message |
|------------|------|---------------|
| DM_AUTH_001 | 403 | 需要文件管理模組權限 |
| DM_ROLE_001 | 403 | 無法停用自己之管理者角色 |
| DM_AUTH_002 | 403 | 需要文件編輯者權限 |
| DM_ROLE_002 | 422 | 指定之可見對象無效或未啟用 |
| DM_ROLE_003 | 422 | 指定之角色代碼無效 |
| DM_REVIEW_001 | 422 | 指定審核者不可為文件撰寫者本人 |
| DM_REVIEW_002 | 409 | 此文件已有進行中之送審，無法同時送出另一種送審 |
| DM_REVIEW_003 | 409 | 此送審已非待審核狀態，無法處理 |
| DM_REVIEW_004 | 422 | 請填寫退回原因（DM-MSG-DM04-004）|
| DM_REVIEW_005 | 403 | 非指定審核者，不可處理此送審 |
| DM_REVIEW_006 | 409 | （已停用）US8 起支援廢止類送審之簽核；原「暫未支援（待 US8）」封鎖已解除 |
| DM_CATALOG_001 | 409 | 受控項目代碼已存在 |
| DM_CATALOG_002 | 404 | 查無此受控項目 |
| DM_CATALOG_003 | 422 | 代碼格式不合法，僅允許英文與數字 |
| DM_FILE_001 | 422 | 檔案大小超過上限 |
| DM_FILE_002 | 422 | 不支援的檔案格式 |
| DM_DOC_001 | 404 | 查無此文件或無權存取 |
| DM_DOC_002 | 403 | 舊版本不可下載，請聯絡管理者 |
| DM_DOC_003 | 422 | 此檔案格式無法線上預覽，請下載原檔 |
| DM_DOC_004 | 422 | 必填欄位未填寫（DM-MSG-DM03-001）|
| DM_DOC_005 | 422 | 文件至少需掛 1 個可見對象（DM-MSG-DM03-008）|
| DM_DOC_006 | 422 | 版本號未填或與本文件既有版本重複（DM-MSG-DM03-009）|
| DM_DOC_007 | 409 | 此關聯作業項目已有對應之已發布手冊（DM-MSG-DM03-003）|
| DM_DOC_008 | 409 | 此文件廢止待簽核，無法上傳新版本（DM-MSG-DM03-004）|
| DM_DOC_009 | 409 | 您已有此文件之未送簽草稿版本，請續編既有草稿（每人每文件一份草稿）|
| DM_DOC_010 | 422 | 受控選項無效或已停用（分類 / 作業項目 / 標籤）|
| DM_DOC_011 | 500 | 文件編號配號失敗，請重試 |
| DM_DOC_012 | 409 | 您對此文件已有審核中的版本，請待審核結果後再編輯（每人每文件一份進行中版本）|
| DM_DOC_013 | 409 | 文件尚無已發布版本（US12 SRVDM001；ET 引用取當前發布版時遇草稿/送審中）|
| DM_DOC_014 | 422 | 請填寫廢止原因（DM-MSG-DM02-011）|
| DM_DOC_015 | 422 | 請選擇指定審核者（DM-MSG-DM02-014）|
| DM_DOC_016 | 409 | 僅能對已發布文件發起廢止（US8）|

> `DM_ROLE_001`（US1 自我保護）：DM 之 `assign_roles_audiences` 轉接層回呼（`../specs/dp/contracts/module-callbacks.md` §3）於 operator 取消自己之管理者角色時 raise；DP 端統一映射為 `DP-MSG-DP06-001` 呈現（見 spec_us7 FR-06）。
