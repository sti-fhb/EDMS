# 開發任務清單：平台模組（Platform）

**模組代碼**: DP | **日期**: 2026-07-09
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md) | **資料模型**: [data-model.md](data-model.md) | **研究**: [research.md](research.md) | **契約**: [contracts/](contracts/)

> DP 為 EDMS **共用基礎層 + 統一管理後台**，是 ET / DM 之開發前置：兩模組依賴 DP 之認證、SRVDP001 參數 / SRVDP002 發信 / SRVDP003 稽核與排程引擎。自身 10 張平台表 + 平台排程 `SCHDP001`。後端骨架自 TBMS 遷移（[EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §3 / §4），惟**須依 research §1 裁剪**：不建 `DP_SESSION`（無 Refresh Token，改短 TTL + 活動換發）、不帶 roles / menus（無全域 RBAC）、無帳號開通信、Email 不加密。DP 反向依賴之模組介面（`is_module_admin` / `grant_default_student_role` / `assign_roles_*` / job handler，見 [contracts/module-callbacks.md](contracts/module-callbacks.md)）於模組未就緒前**以 stub 先行**、模組實作跟進後替換。

---

## Phase 1: 專案設定

- [ ] T001 建立後端骨架（EDMS-MIGRATION §3）：`backend/pyproject.toml` 依賴（SQLAlchemy async / asyncpg / Alembic / PyJWT / passlib[bcrypt] / fastapi-mail / APScheduler）、core 帶入（db / base_model / pagination / exceptions / config——config 刪 TBMS 業務項、補 JWT / SMTP 設定）、Alembic 骨架（**versions 清空重建**、target_metadata 指向 EDMS Base）、測試 DB 骨架（test_edms）
- [ ] T002 [P] 建立資料庫 Migration：`DP_USER`（USER_ID PK、EMAIL UNIQUE **不加密**、PWD_HASH、STATUS、LOGIN_FAIL_COUNT、LOCKED_UNTIL、LAST_LOGIN_DATE、PENDING_EMAIL、PWD_CHANGED_DATE、MUST_CHANGE_PWD），參照 data-model.md；**不建 `DP_SESSION`**（research §1）
- [ ] T003 [P] 建立資料庫 Migration：`DP_PWD_RESET`（TOKEN_HASH PK、TOKEN_TYPE＝PWD_RESET / EMAIL_CHANGE、NEW_EMAIL、EXPIRES / USED_DATE）與 `DP_PWD_HIST`（USER_ID + SEQ_NO，append-only），參照 data-model.md、research §5
- [ ] T004 [P] 建立資料庫 Migration：`DP_AUDIT_LOG`（append-only；BEFORE / AFTER_VALUE **TEXT 存 JSON**、ROW_HASH、索引×3）+ 應用 DB 帳號對本表僅 GRANT INSERT / SELECT，參照 data-model.md、research §6
- [ ] T005 [P] 建立資料庫 Migration：`DP_PARAM_M`（PARAM_TYPE VALUE / LIST、DETAIL_LOCK）+ `DP_PARAM_D`（PARAM_ID + PARAM_KEY、IS_ENABLED），參照 data-model.md、research §7
- [ ] T006 [P] 建立資料庫 Migration：`DP_NOTIFY_TEMPLATE`（MODULE + TEMPLATE_CODE 複合 PK、CHANNEL、IS_ENABLED、IS_SYSTEM、VERSION 樂觀鎖），參照 data-model.md
- [ ] T007 [P] 建立資料庫 Migration：`DP_EMAIL_LOG`（outbox；渲染快照 SUBJECT / BODY、STATUS / RETRY_COUNT / ERROR_MSG / SENT_DATE、CALLER_MODULE、索引 (STATUS, CREATED_DATE)），參照 data-model.md
- [ ] T008 [P] 建立資料庫 Migration：`DP_SCHEDULE`（JOB_ID PK、CRON_EXPR、HANDLER_REF、IS_ENABLED、LAST_RUN_*）與 `DP_SCHEDULE_LOG`（append-only），參照 data-model.md
- [ ] T009 建立種子資料：平台級參數（`JWT`：ACCESS_TTL_MIN=15 / RENEW_MAX_HOURS=8；`PWD_POLICY`：MIN_LEN=8 / ADMIN_MIN_LEN=12 / CHAR_TYPES=3 / HISTORY_COUNT=3 / EXPIRY_DAYS=90 / EXPIRY_REMIND_DAYS=7；`LOGIN`：FAIL_LOCK_COUNT=5 / LOCK_MINUTES=30 / RESET_TOKEN_TTL_MIN=30 / EMAIL_CHANGE_TTL_MIN=30 / IDLE_DISABLE_DAYS=90；`MAIL`；`ACTION_TYPE` 清單）、DP 系統信 3 支（`PWD_RESET` / `EMAIL_CHANGE_VERIFY` / `PWD_EXPIRY_REMIND`，IS_SYSTEM=true）、排程 job（SCHDP001 + SCHET001 / 002 / SCHDM001 預留列），參照 data-model.md §種子資料；**模組級參數種子由各模組 migration 補**
- [ ] T010 建立前端骨架：Vite + React 19 + MUI 7 + React Router v7 + TanStack Query v5（一律 TypeScript）、DP 後台 layout（sidebar 對齊 wireframe：dp-users / dp-params / dp-templates / dp-roles / dp-audit / dp-schedule + 右上個資選單）、登入 overlay 骨架

---

## Phase 2: 基礎共用元件

> 為所有 User Story 之阻斷性前置（稽核、參數、JWT、認證 middleware、速率限制、密碼策略、管理者判定）。

- [ ] T011 [P] 實作稽核服務 **SRVDP003** dp/audit：`log_action()`（TEXT 序列化 JSON、鏈式 ROW_HASH 計算）；無 UPDATE / DELETE 方法，參照 [contracts/platform-services.md](contracts/platform-services.md)、research §6
- [ ] T012 [P] 實作參數唯讀服務 **SRVDP001** dp/param：`get_param_value` / `get_param_list`（**不快取**、每次讀 DB；PARAM_ID 不存在回空），參照 contracts、research §7
- [ ] T013 [P] 實作 JWT 基礎 core/auth：簽發（含 `auth_time` claim、TTL 讀 `JWT.ACCESS_TTL_MIN`）、decode、換發驗證（現行 token 有效 + `auth_time` 距今 < RENEW_MAX_HOURS）；起手包 `auth.py` 改造（**刪 refresh / MFA 分支**），參照 research §2
- [ ] T014 [P] 實作認證 middleware：Bearer 驗證 + **每請求查 `DP_USER` 狀態**（DISABLED / LOCKED / DELETED 即拒）+ `request_context`（來源 IP）/ `operator`（起手包帶入），對應 spec_us1 FR-DP-US1-11、research §3
- [ ] T015 [P] 實作速率限制 middleware：行程內滑動視窗（來源 IP + 帳號），供登入 / 忘記密碼 / 密碼變更端點掛載，超限回 429，參照 research §10
- [ ] T016 [P] 實作密碼策略工具 dp/password_policy：複雜度檢核（讀 `PWD_POLICY`；特權 12 字元於變更當下依 T017 判定）、重複性檢核（`DP_PWD_HIST` 最近 N 筆 bcrypt 比對）、雜湊 / 追加歷程，參照 research §11
- [ ] T017 [P] 實作模組管理者判定閘 dp/authz：聚合呼叫 ET / DM `is_module_admin(user_id)`（**模組未就緒前 stub**）供後台端點之共用項 / 模組項過濾，參照 [contracts/module-callbacks.md](contracts/module-callbacks.md) §1、research §4

---

## Phase 3: US6 — 通知發送服務（P1，無畫面）

> **Story 目標**: 平台唯一發信入口 + outbox 非同步寄送
> **獨立測試**: 呼叫 `send_email` 立即返回且 outbox 出現 PENDING；worker 寄出轉 SENT；SMTP 失敗重試逾上限轉 FAILED 留錯誤；停用範本 skip 不影響呼叫方
> **對應 FR**: spec_us6 FR-DP-US6-01~06

- [ ] T018 [US6] 實作 **SRVDP002** `send_email` dp/mail：範本查詢（MODULE + TEMPLATE_CODE；不存在 raise AppError、停用回 skipped）、變數渲染、**逐收件人**寫 `DP_EMAIL_LOG`（PENDING、渲染快照、CALLER_MODULE）即返回，對應 FR-01~04
- [ ] T019 [US6] 實作常駐寄送 worker（FastAPI lifespan asyncio task，**不入排程表**）：輪詢 PENDING、依 `MAIL` 參數限速 / 重試 / 間隔、SMTP 寄送更新 SENT / FAILED（單筆失敗不影響同批）；變數缺漏該列 FAILED，對應 FR-02/05/06、research §8
- [ ] T020 [US6] SMTP 介接設定：`.env.example` 補 `SMTP_HOST / PORT / USER / PASSWORD / MAIL_FROM`；SMTP 不可用時信件停留 outbox 恢復續寄，參照 [contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)

---

## Phase 4: US1 — 使用者登入 / 登出（P1）

> **Story 目標**: 帳密登入核發 JWT、鎖定、閒置換發、導向、登出
> **獨立測試**: 正確帳密登入取得 token；錯 5 次鎖定、30 分自動解鎖；閒置 15 分失效；換發逾 8 小時拒絕；登出寫稽核
> **對應 FR**: spec_us1 FR-DP-US1-01~11
> **前置**: Phase 2（T013 JWT、T014 middleware、T015 限流、T016 密碼）

- [ ] T021 [US1] 實作登入端點 dp/user：帳密驗證（錯誤分流 LOGIN-001/002、bcrypt 比對）、鎖定判定（LOCKED_UNTIL 逾時視為已解鎖）、失敗計數 / 達 `FAIL_LOCK_COUNT` 自動鎖定、成功歸零計數 + 更新 LAST_LOGIN + 核發 JWT + LOGIN 稽核（含 FAIL 事件），對應 FR-02/04/05/08
- [ ] T022 [US1] 實作換發端點 `renew`（T013 驗證邏輯 + 帳號狀態檢核）與登出端點（LOGOUT 稽核；前端丟棄 token），對應 FR-03/10
- [ ] T023 [US1] 實作強制變更密碼閘：登入時檢核 `MUST_CHANGE_PWD` / `PWD_CHANGED_DATE` 逾效期 → 回應強制變更旗標；未完成變更前其他端點拒絕（middleware 檢核），對應 FR-06、spec_us8 FR-DP-US8-08
- [ ] T024 [US1] 實作登入頁前端：帳密遮蔽、錯誤訊息（DP-MSG-LOGIN-001~007）、redirect 白名單返回原模組、前端閒置換發計時器（到期前有操作即呼叫 renew）、掛速率限制（T015），對應 FR-01/07/09、research §12
- [ ] T025 [US1] 實作模組入口頁：後端「我的模組角色摘要」端點（聚合模組 `has_any_role`，stub 先行）+ 前端入口頁（ET 恆顯、DM 具任一角色才顯、個資恆顯、**不顯後台入口**），對應 FR-07、contracts/module-callbacks §4

---

## Phase 5: US2 — 使用者自助註冊（P1）

> **Story 目標**: 註冊即用、帳號建立時授予 ET 學員（唯一預設角色）
> **獨立測試**: 未註冊 Email 完成註冊即可登入且僅具 ET 學員；重複 Email / 不合規密碼被擋
> **對應 FR**: spec_us2 FR-DP-US2-01~06
> **前置**: Phase 2（T016 密碼）、ET `grant_default_student_role`（stub 可）

- [ ] T026 [US2] 實作註冊端點：Email 唯一 / 複雜度 / 兩次一致（伺服器端）、建 `DP_USER`（雜湊、ACTIVE）+ `DP_PWD_HIST` 首筆 + 呼叫 ET `grant_default_student_role`（**不授予任何 DM 角色**）+ CREATE 稽核，對應 FR-02/03/05/06
- [ ] T027 [US2] 實作註冊前端頁籤：欄位與訊息（DP-MSG-REGISTER-001~004）、成功跳回登入頁預填 Email，對應 FR-01/04

---

## Phase 6: US3 — 忘記密碼（P1）

> **Story 目標**: 一次性時效重設連結、防帳號列舉
> **獨立測試**: 申請後 30 分內重設成功並以新密碼登入；未註冊 Email 得相同訊息；逾時 / 已用連結被拒；重複申請舊 token 失效
> **對應 FR**: spec_us3 FR-DP-US3-01~08
> **前置**: Phase 3（US6 發信）、Phase 2（T015 / T016）

- [ ] T028 [US3] 實作申請端點：防列舉統一回覆（DP-MSG-FORGOT-001）、token 產生（明文入信、SHA-256 入 `DP_PWD_RESET`、同人同型舊 token 作廢）、經 SRVDP002 寄 `PWD_RESET` 範本、掛速率限制，對應 FR-01~04/08
- [ ] T029 [US3] 實作重設端點與頁面：token 驗證（逾時 / 已用 FORGOT-002）、新密碼複雜度 + 重複性（T016）、更新 + `DP_PWD_HIST` + 密碼重置稽核 + token 作廢；**不解除鎖定 / 停用**，對應 FR-05~07

---

## Phase 7: US4 — 使用者管理（P1，共用項）

> **Story 目標**: 管理者建立 / 停用 / 啟用 / 解鎖帳號、維護基本資料
> **獨立測試**: 代建帳號首登強制變更；停用後 ET / DM 下次請求即拒；解鎖後可登入；停用自己被擋
> **對應 FR**: spec_us4 FR-DP-US4-01~09
> **前置**: Phase 2（T016 / T017）、Phase 5（授予學員共用邏輯）

- [ ] T030 [US4] 實作使用者查詢端點 + dp-users 前端清單：Email / 姓名 / 狀態條件、後端分頁、共用項（兩模組管理者可用、一般使用者擋），對應 FR-01/02
- [ ] T031 [US4] 實作建立帳號：管理者設初始密碼（複雜度檢核）+ `MUST_CHANGE_PWD`=true + ET 學員授予（同 T026 邏輯）+ 稽核，訊息 DP-MSG-USERS-003/005，對應 FR-03/07
- [ ] T032 [US4] 實作停用 / 啟用 / 解鎖 / 基本資料維護：停用二次確認（USERS-002）、**自我保護**（不可停用 / 鎖定自己，USERS-001）、解鎖歸零計數（USERS-004）、管理者代改姓名 / Email（直接生效、Email 唯一檢核）、全數寫稽核（含前後值），對應 FR-04~06/08

---

## Phase 8: US5 — 系統參數與清單維護（P1）

> **Story 目標**: 平台級 + 模組級參數與清單之單一維護入口
> **獨立測試**: ET 管理者不見 `DM_` 項且 API 直呼被拒；改參數即時生效；`DETAIL_LOCK` 碼值不可改；清單無刪除功能
> **對應 FR**: spec_us5 FR-DP-US5-01~07
> **前置**: Phase 2（T012 / T017）

- [ ] T033 [US5] 實作參數 / 清單維護端點：前綴過濾**伺服器端 enforce**（T017：模組項互不可見、平台級共用；越權 403＝PARAMS-003）、值合法性驗證（型別 / 值域，PARAMS-001）、清單項新增 / 改名 / 啟停（**不開放刪除**）、`DETAIL_LOCK` 擋碼值修改（PARAMS-002）、異動稽核（前後值），對應 FR-01~04/06
- [ ] T034 [US5] 實作 dp-params 前端：平台級 / 模組級分區、平台級編輯警告（PARAMS-005）、清單型 key / value / 排序 / 啟停編輯、儲存即生效提示（PARAMS-004），對應 FR-02/07

---

## Phase 9: US7 — 權限管理（P1）

> **Story 目標**: 同一頁指派模組角色 + 標籤 / 可見對象（資料寫模組表）
> **獨立測試**: ET 管理者指派角色+標籤即時生效寫 `ET_USER_ROLE` / `ET_USER_TAG`；取消自己管理者被模組擋下；ET 看不到 DM 區
> **對應 FR**: spec_us7 FR-DP-US7-01~07
> **前置**: Phase 2（T017）、模組 `get_user_roles_*` / `assign_roles_*`（stub 先行）

- [ ] T035 [US7] 實作權限管理轉接端點：查使用者 + 現況（呼叫模組 `get_user_roles_tags` / `get_user_roles_audiences`）、儲存（呼叫 `assign_roles_*`，模組 AppError 透傳為 ROLES-001）、模組過濾 enforce（越權 403＝ROLES-003）；標籤可選清單讀 `DP_PARAM` 啟用中項（T012）；指派異動之稽核由**模組側**於同交易呼叫 SRVDP003 寫入（FR-07，per contracts §3），對應 FR-01~03/05~07、contracts/module-callbacks §3
- [ ] T036 [US7] 實作 dp-roles 前端：同列「角色核取 + 標籤 / 可見對象多選」雙維度、按模組分區（兼具者雙區）、即時生效提示（ROLES-002）、固定 enum 無新增角色入口，對應 FR-02/04

---

## Phase 10: US8 — 個人資料維護（P2）

> **Story 目標**: 姓名 / Email 驗證切換 / 密碼變更 + 強制變更頁
> **獨立測試**: 改姓名兩端同步；Email 變更驗證後切換、逾時作廢、期間舊 Email 可登入；密碼變更驗舊 + 策略；管理者變更需 12 字元
> **對應 FR**: spec_us8 FR-DP-US8-01~08
> **前置**: Phase 3（US6 發信）、Phase 2（T015 / T016 / T017）

- [ ] T037 [US8] 實作姓名 / 密碼變更端點：姓名直接存 + 稽核；密碼驗舊（PROFILE-001）+ 複雜度（特權 12 字元，PROFILE-003）+ 重複性（PROFILE-004）+ `DP_PWD_HIST` + 稽核 + 清 `MUST_CHANGE_PWD`、掛速率限制，對應 FR-01/02/04~07
- [ ] T038 [US8] 實作 Email 變更流程：新 Email 唯一檢核（PROFILE-006）、`EMAIL_CHANGE` token（`NEW_EMAIL` + `PENDING_EMAIL`）、經 SRVDP002 寄 `EMAIL_CHANGE_VERIFY` 至**新信箱**（PROFILE-005）、驗證端點切換（舊失效）/ 逾時作廢（PROFILE-008）、稽核，對應 FR-03
- [ ] T039 [US8] 實作 dp-profile 前端 + **強制變更密碼頁**（US1 T023 導入點；未完成不得離開，訊息 DP-MSG-LOGIN-005 / PROFILE-007），對應 FR-08

---

## Phase 11: US9 — 通知範本維護（P2）

> **Story 目標**: 按 MODULE 過濾之範本編輯（系統信保護 + 樂觀鎖）
> **獨立測試**: ET 管理者僅見 ET + DP 範本；編輯後 US6 以新內容渲染；DP 系統信停用被擋；並行編輯觸發衝突
> **對應 FR**: spec_us9 FR-DP-US9-01~07
> **前置**: Phase 2（T017）、Phase 3（渲染驗證）

- [ ] T040 [US9] 實作範本查詢 / 編輯端點：MODULE 過濾 enforce（越權 403＝TEMPLATES-004；`MODULE=DP` 兩者可編）、`IS_SYSTEM` 擋停用 / 刪除（TEMPLATES-001）、VERSION 樂觀鎖（衝突 409＝TEMPLATES-002）、無新增 / 刪除範本端點、異動稽核，對應 FR-01~06
- [ ] T041 [US9] 實作 dp-templates 前端：清單 + 編輯（主旨 / 內文 / 管道 / 啟停、變數說明顯示）、衝突提示重載、儲存成功（TEMPLATES-003）；管道欄註記「站內由模組自理」，對應 FR-07

---

## Phase 12: US10 — 操作記錄查詢（P2，共用項）

> **Story 目標**: 稽核多條件查詢、明細前後值、CSV 匯出
> **獨立測試**: 條件查得紀錄並展開 JSON 前後值；CSV 與查詢一致；一般使用者被擋；介面無刪改功能
> **對應 FR**: spec_us10 FR-DP-US10-01~06
> **前置**: Phase 2（T011 寫入已就緒、T017）

- [ ] T042 [US10] 實作稽核查詢端點：多條件（操作者 / 期間起訖 / 模組 / 操作類別）+ 後端分頁（時間倒序）+ 明細（JSON 前後值）+ 僅管理者（AUDIT-002）；**不提供任何刪改端點**，對應 FR-01/02/04/05
- [ ] T043 [US10] 實作 CSV 匯出（依查詢條件全量）+ dp-audit 前端（查詢列 / 明細展開 / 空狀態 AUDIT-001），對應 FR-02/03

---

## Phase 13: US11 — 排程作業執行與總覽（P2）

> **Story 目標**: 排程引擎 + `SCHDP001` + 唯讀總覽
> **獨立測試**: job 依 cron 觸發留起訖與結果；失敗隔離；重疊跳過記 SKIPPED；SCHDP001 禁用閒置帳號並寄到期提醒；總覽唯讀無操作鈕
> **對應 FR**: spec_us11 FR-DP-US11-01~07
> **前置**: Phase 3（US6 發信）、Phase 1（T008 / T009）

- [ ] T044 [US11] 實作排程引擎 core/scheduler：APScheduler 啟動載入 `DP_SCHEDULE` 啟用中 job（`HANDLER_REF` 動態 import）、`max_instances=1` + 跳過記 SKIPPED、執行寫 `DP_SCHEDULE_LOG` 與 LAST_RUN_*、失敗隔離；多實例 leader 選舉（起手包 `scheduler_leader.py`，單實例直跑），對應 FR-01~04、research §9
- [ ] T045 [US11] 實作 `SCHDP001` handler（每日）：① `LAST_LOGIN_DATE` 逾 `IDLE_DISABLE_DAYS` → STATUS=DISABLED + 稽核；② `PWD_CHANGED_DATE` 距效期 ≤ `EXPIRY_REMIND_DAYS` → 經 SRVDP002 寄 `PWD_EXPIRY_REMIND`，對應 FR-05
- [ ] T046 [US11] 實作排程總覽端點 + dp-schedule 前端：唯讀 job 清單（JOB_ID / 說明 / cron / 啟停 / 上次結果）+ 歷程展開 + 空狀態（SCHEDULE-001）；**無啟停 / 補跑操作**、共用項（兩管理者可檢視），對應 FR-06/07

---

## Phase 14: 整合與收尾

- [ ] T047 整合測試：認證鏈端到端（註冊→登入→操作換發→閒置 15 分失效→忘記密碼→重設→新密碼登入；代建帳號→初始密碼首登→強制變更→正常使用），對應 SC-001/003/004/005
- [ ] T048 整合測試：鎖定與失效（錯 5 次自動鎖定→30 分自動解鎖 / 管理者解鎖；停用帳號下次請求即拒、兩模組同步；換發逾單日 8 小時上限拒絕），對應 SC-002/005/006
- [ ] T049 模組過濾越權驗證：ET 管理者經 UI 與**直呼 API** 存取 `DM_` 參數 / `MODULE=DM` 範本 / DM 角色指派一律 403；共用項（帳號 / 平台級參數 / 稽核 / 排程總覽）兩管理者皆可，對應 SC-007
- [ ] T050 發信引擎驗證：`send_email` 不阻塞呼叫方（大量收件人）、重試逾上限 FAILED 留錯誤、停用範本 skip 事件照常、範本修改後新信以新內容渲染、快照不受事後改範本影響，對應 SC-009
- [ ] T051 排程驗證：cron 準時觸發（單 / 多實例僅一次）、單 job 失敗不影響其他、重疊跳過、SCHDP001 兩職責（閒置禁用 + 到期提醒）、`DP_SCHEDULE_LOG` 完整，對應 SC-011
- [ ] T052 稽核驗證：各 US 事件齊備（登入成敗 / 登出 / 帳號 / 角色 / 密碼重置 / 參數範本異動含前後值）、append-only（無刪改途徑 + DB 權限）、ROW_HASH 鏈驗證工具、查詢 / CSV 正確，對應 SC-010
- [ ] T053 安全性檢查：速率限制生效（登入 / 忘記密碼 / 密碼變更）、防帳號列舉回覆一致、token 一次性與雜湊儲存、密碼策略 / 歷程、HTTPS / 密碼遮蔽、系統錯誤僅簡短訊息與代碼、輸入驗證皆伺服器端
- [ ] T054 參數即時性驗證：US5 儲存後 SRVDP001 讀取 / 業務下拉即時反映（無快取延遲）、`DETAIL_LOCK` 碼建立後不可改，對應 SC-008

---

## 依賴關係

```
Phase 1 (設定) → Phase 2 (共用元件)
    ↓
Phase 3 (US6 發信) ── P1 ── US3 / US8 / SCHDP001 之寄信前置
    ↓
Phase 4 (US1 登入) → Phase 5 (US2 註冊) → Phase 6 (US3 忘記密碼) ── P1 認證鏈
    ↓
Phase 7 (US4 使用者管理) / Phase 8 (US5 參數維護) ── P1（可平行）
    ↓
Phase 9 (US7 權限管理) ── P1（依模組 assign service，stub 先行）
    ↓
Phase 10 (US8 個資) / Phase 11 (US9 範本) / Phase 12 (US10 稽核查詢) / Phase 13 (US11 排程) ── P2（多可平行）
    ↓
Phase 14 (整合收尾)
```

> **與 ET / DM 之時序**：Phase 2 完成後 SRVDP001–003 即可供模組開發引用；US2 / US4 / US7 / 入口頁之**完整**驗收需模組 service 就緒——先以 [contracts/module-callbacks.md](contracts/module-callbacks.md) 簽章 stub 通過單元測試，模組實作跟進後於 T047 / T049 回歸。

**可平行開發的機會**：
- Phase 1 內 T002~T008 可平行（不同 Table）
- Phase 2 內 T011~T017 可平行（獨立服務 / middleware / 工具）
- Phase 7（US4）與 Phase 8（US5）可平行；P2 之 Phase 10~13 多可平行（不同畫面 / 引擎）
- 各 Phase 內標記 [P] 的任務可平行執行

---

## 實作策略

**MVP 範圍**: Phase 1–6（Foundation + US6 發信 + US1–US3 認證鏈）——全系統可登入 / 註冊 / 自救密碼，SRVDP001–003 可供 ET / DM 開工，即構成平台最小可用核心；US4 / US5 緊接補足帳號與參數維護。

**增量交付**:
1. Sprint 1: Phase 1–2（起手包裁剪 + 10 表 migration + 種子 + 稽核 / 參數 / JWT / middleware 共用件）
2. Sprint 2: Phase 3–6（US6 發信 → US1 登入 → US2 註冊 → US3 忘記密碼）→ 認證鏈 MVP 成形
3. Sprint 3: Phase 7–9（US4 使用者管理 + US5 參數維護 + US7 權限管理）→ DP 後台 P1 齊備
4. Sprint 4: Phase 10–13（US8 個資 + US9 範本 + US10 稽核查詢 + US11 排程引擎 / SCHDP001 / 總覽）
5. Sprint 5: Phase 14（整合收尾 + 模組 stub 替換回歸）→ 平台全功能交付

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總任務數 | 54 |
| Phase 1 設定 | 10（骨架 1 + migration 7 + 種子 1 + 前端骨架 1）|
| Phase 2 共用 | 7（稽核 / 參數 / JWT / 認證 / 限流 / 密碼 / 管理者判定）|
| US6 通知發送服務 | 3 |
| US1 登入 / 登出 | 5 |
| US2 自助註冊 | 2 |
| US3 忘記密碼 | 2 |
| US4 使用者管理 | 3 |
| US5 參數與清單維護 | 2 |
| US7 權限管理 | 2 |
| US8 個人資料維護 | 3 |
| US9 通知範本維護 | 2 |
| US10 操作記錄查詢 | 2 |
| US11 排程執行與總覽 | 3 |
| 整合收尾 | 8 |
| 可平行機會 | Phase 1（7 組）、Phase 2（7 組）、US4+US5、P2 四線 |
