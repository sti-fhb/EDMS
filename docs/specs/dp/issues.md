# 開發 Issues 清單：平台模組（Platform）

**模組代碼**: DP | **日期**: 2026-07-09
**來源**: [plan.md](plan.md) §功能分群與開發順序 | [tasks.md](tasks.md) | [spec.md](spec.md)

> 每張 Issue 為一個**功能之垂直切割**（DB + API + UI + 驗收條件），可獨立開發、測試與交付。Issue #0 為基礎建設，其餘依 plan.md 之 P1 / P2 階段排序。
>
> **增量模式（2026-07-09）**：採「產一張 → 實作 → 驗證 OK → 再補下一張」流程；目前僅 Issue #0 完整撰寫，#1 起之完整 body 待 #0 實作驗證後逐張補入（總覽表先列全貌）。
>
> **Issue 開立規則（2026-07-09）**：
> 1. 標題格式：`[{階段}] {模組代碼} — {功能名稱}`（如 `[Foundation] DP — 專案建置與平台基礎建設`、`[P1-核心] DP — 通知發送服務`）
> 2. Labels：`{階段標籤}`（Foundation 用 `priority:P0`；其餘 `P1-核心` / `P2-延伸` / `收尾`）+ `DP-平台` + `{US 標籤}`（如 `US6`；無對應 US 者免）
> 3. **依序開立**，於 body「依賴」段標註相依之 **GitHub Issue 編號**（模組內序號 #0–#12 僅為規劃用，實際編號以 GitHub 為準、回填總覽表）

---

## Issue 總覽

| # | 標題 | 對應 | 階段 | 涵蓋 Tasks | 主要前置 | GitHub # | 狀態 |
|---|------|------|------|-----------|---------|----------|------|
| 0 | 專案建置與平台基礎建設 | — | Setup + Foundational | T001 ~ T017（17 任務）| 無 | [#16](https://github.com/sti-fhb/EDMS/issues/16) | ✅ 已開立 |
| 1 | 通知發送服務（發信引擎 + outbox）| US6 / UCDP009 | P1-核心 | T018 ~ T020（3 任務）| #0 | [#27](https://github.com/sti-fhb/EDMS/issues/27) | ✅ 已合併（PR #29）|
| 2 | 登入 / 登出與模組入口頁 | US1 / UCDP001 | P1-核心 | T021 ~ T025（5 任務）| #0 | [#31](https://github.com/sti-fhb/EDMS/issues/31) | ✅ 已開立 |
| 3 | 使用者自助註冊 | US2 / UCDP002 | P1-核心 | T026 ~ T027（2 任務）| #2 | [#39](https://github.com/sti-fhb/EDMS/issues/39) | ✅ 已開立 |
| 4 | 忘記密碼 | US3 / UCDP003 | P1-核心 | T028 ~ T029（2 任務）| #1, #2 | [#47](https://github.com/sti-fhb/EDMS/issues/47) | ✅ 已開立 |
| 5 | 使用者管理（dp-users）| US4 / UCDP005 | P1-核心 | T030 ~ T032（3 任務）| #2, #3 | [#61](https://github.com/sti-fhb/EDMS/issues/61) | ✅ 已開立 |
| 6 | 系統參數與清單維護（dp-params）| US5 / UCDP006 | P1-核心 | T033 ~ T034（2 任務）| #0, #2, #5 | [#68](https://github.com/sti-fhb/EDMS/issues/68) | ✅ 已合併（PR #73）|
| 7 | 權限管理（dp-roles）| US7 / UCDP010 | P1-核心 | T035 ~ T036（2 任務）| #2, #6（DP_PARAM 標籤清單）；DM provider（US1 #133 已交付）/ ET fail-closed | [#140](https://github.com/sti-fhb/EDMS/issues/140) | 🚀 已開立 [#140](https://github.com/sti-fhb/EDMS/issues/140) |
| 8 | 個人資料維護 + 強制變更密碼（dp-profile）| US8 / UCDP004 | P2-延伸 | T037 ~ T039（3 任務）| #0, #1, #2 | — | 🚀 已開立 [#83](https://github.com/sti-fhb/EDMS/issues/83) |
| 9 | 通知範本維護（dp-templates）| US9 / UCDP011 | P2-延伸 | T040 ~ T041（2 任務）| #1, #2 | — | 🚀 已開立 [#92](https://github.com/sti-fhb/EDMS/issues/92) |
| 10 | 操作記錄查詢（dp-audit）| US10 / UCDP007 | P2-延伸 | T042 ~ T043（2 任務）| #0, #2 | [#97](https://github.com/sti-fhb/EDMS/issues/97) | ✅ 已合併（PR [#100](https://github.com/sti-fhb/EDMS/pull/100)）|
| 11 | 排程引擎與總覽 + SCHDP001（dp-schedule）| US11 / UCDP008 | P2-延伸 | T044 ~ T046（3 任務）| #0, #1 | [#106](https://github.com/sti-fhb/EDMS/issues/106) | ✅ 已合併（PR [#108](https://github.com/sti-fhb/EDMS/pull/108)）|
| 12 | 整合測試 + 稽核驗鏈工具 + 安全驗收（不含 T049 / ET-DM 回歸）| — | 收尾 | T047 ~ T048, T050 ~ T054（T049 → follow-up）| 全部 | [#114](https://github.com/sti-fhb/EDMS/issues/114) | ✅ 已合併（PR [#116](https://github.com/sti-fhb/EDMS/pull/116)）|
| 12-F | 真授權閘掛 router + ET/DM 回歸（T049 follow-up）| — | 收尾 | T049 | #114；ET / DM 模組 | [#113](https://github.com/sti-fhb/EDMS/issues/113) | ⏸️ 已開立（待 ET/DM 落地）|
| F1 | 開發流程 CI 基礎建設（local-ci / ci.yml 預備 / PR 模板 / error-codes 骨架）| — | Foundation-infra | —（不對應 tasks.md 業務 task）| 無 | [#18](https://github.com/sti-fhb/EDMS/issues/18) | 🔨 開發中 |

> **F 系列＝Foundation-infra**（開發流程 / CI/CD，非業務 task）。F1 只做 repo 側、不依賴 runner；runner 註冊 + CD + branch protection 於未來 GCP 環境就緒後處理（EDMS 自有 ci/cd，不共用 TBMS）。

---

## Issue #0：[Foundation] DP — 專案建置與平台基礎建設（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）

**對應規格**：[plan.md](plan.md) §技術背景、§第零階段；[data-model.md](data-model.md)；[research.md](research.md) §1–§11；[contracts/platform-services.md](contracts/platform-services.md)
**階段**：Setup + Foundational（為所有 Issue 之前置；亦為 ET / DM 兩模組開發之前置）
**前置條件**：
- PostgreSQL 17 已建置；TBMS 原始碼（`../TBMS`）可供遷移參照
- `backend/.env`、`frontend/.env` 依 `.env.example` 建立

### 任務說明

建立 EDMS 後端 / 前端骨架（自 TBMS 遷移起手包，依 [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §3 / §4），完成 DP 10 張平台表 migration 與種子資料，並實作平台共用元件：稽核服務（SRVDP003）、參數唯讀服務（SRVDP001）、JWT 基礎（短 TTL + 活動換發）、認證 middleware、速率限制、密碼策略工具、模組管理者判定閘。本 Issue 完成後，SRVDP001–003 即可供 ET / DM 模組開發引用。

> ⚠️ **遷移裁剪（research §1，最容易踩雷處）**：起手包複製後 MUST 裁剪——不建 `DP_SESSION`（無 Refresh Token，改 `auth_time` 換發）、不帶 `app/dp/roles` / `menus`（無全域 RBAC）、無 `ACCOUNT_CONFIRM` 開通信、`EMAIL` 不加密、刪 MFA。勿照 EDMS-MIGRATION 舊清單全帶。

### 範圍

**後端**：
- T001 調整既有骨架（`fa9b398` 已建最小骨架，改為補缺口）：**首步修 `core/base_model.py` 移除 `CREATED_SITE` / `UPDATED_SITE`（四基底類別，TBMS 殘留）**、pyproject 補 PyJWT / passlib[bcrypt] / fastapi-mail / APScheduler、config 與 `.env.example` 補 JWT / SMTP 設定；db / pagination / exceptions / conftest 沿用
- T002~T008 Migration：`DP_USER`（無 DP_SESSION）、`DP_PWD_RESET` + `DP_PWD_HIST`、`DP_AUDIT_LOG`（TEXT 存 JSON + ROW_HASH + DB 帳號僅 INSERT/SELECT）、`DP_PARAM_M/D`、`DP_NOTIFY_TEMPLATE`、`DP_EMAIL_LOG`、`DP_SCHEDULE` + `DP_SCHEDULE_LOG`
- T009 種子：平台級參數（`JWT` / `PWD_POLICY` / `LOGIN` / `MAIL` / `ACTION_TYPE` 全預設值，見 data-model §種子）、DP 系統信 3 支（`PWD_RESET` / `EMAIL_CHANGE_VERIFY` / `PWD_EXPIRY_REMIND`，IS_SYSTEM=true）、排程 job 4 筆
- T011 SRVDP003 稽核服務（鏈式 ROW_HASH）
- T012 SRVDP001 參數唯讀服務（不快取）
- T013 JWT 基礎（`auth_time` claim、15 分 TTL、換發驗證 8 小時上限）
- T014 認證 middleware（每請求查 `DP_USER` 狀態）+ request_context / operator
- T015 速率限制 middleware（IP + 帳號滑動視窗）
- T016 密碼策略工具（複雜度 / 重複性 / bcrypt / 歷程追加）
- T017 模組管理者判定閘（`is_module_admin` 聚合，**stub 可注入**）

**前端**：
- T010 骨架：Vite + React 19 + MUI 7 + React Router v7 + TanStack Query v5（一律 TypeScript）、DP 後台 layout（sidebar 對齊 [wireframe](../../wireframes/dp/index.html)）、登入 overlay 骨架

**測試**：
- 測試 DB 骨架（`test_edms`、xdist）；各共用元件單元測試；migration 可升可測

### 驗收條件

- [ ] `uv run alembic upgrade head` 成功建立 10 張 DP 表；標準欄位齊備（CREATED/UPDATED_USER/DATE、DELETED，**無 SITE 欄位**；`RES_ID` 已於 #158 移除）；**不存在** `DP_SESSION` / `DP_ROLE` / `DP_MENU` 表
- [ ] 種子載入成功：平台級參數（含 `ACCESS_TTL_MIN`=15、`RENEW_MAX_HOURS`=8、`FAIL_LOCK_COUNT`=5、`LOCK_MINUTES`=30、`MIN_LEN`=8 / `ADMIN_MIN_LEN`=12、`HISTORY_COUNT`=3、`EXPIRY_DAYS`=90、`RETRY_MAX`=5 / `RATE_PER_MIN`=60 / `RETRY_INTERVAL_MIN`=2）、DP 系統信 3 支（IS_SYSTEM=true）、排程 job 4 筆（SCHDP001 / SCHET001 / SCHET002 / SCHDM001）
- [ ] SRVDP003 `log_action` 寫入 `DP_AUDIT_LOG` 含鏈式 ROW_HASH（驗證工具可證前列被改即斷鏈）；應用 DB 帳號對本表僅可 INSERT / SELECT
- [ ] SRVDP001 `get_param_value` / `get_param_list` 讀取種子正確；停用清單項於 enabled_only 過濾；PARAM_ID 不存在回空非例外
- [ ] JWT 簽發含 `auth_time`；換發於「token 有效 + 未逾 8 小時」通過、逾 15 分未換發自然失效、逾 8 小時上限拒絕（單元測試覆蓋）
- [ ] 認證 middleware：未帶 token 401；停用 / 鎖定帳號之有效 token 下次請求被拒（每請求查 DP_USER）
- [ ] 速率限制以「IP + 帳號」維度超限回 429
- [ ] 密碼策略：8 / 12 字元與 3 種字元組合檢核、與最近 3 次重複拒絕（查 `DP_PWD_HIST`）、bcrypt 雜湊（單元測試覆蓋）
- [ ] `is_module_admin` 判定閘可以 stub 注入替換（依 [contracts/module-callbacks.md](contracts/module-callbacks.md) 簽章）
- [ ] 前端骨架可啟動；DP 後台 layout sidebar 六畫面連結對齊 wireframe；無任何 `.js` / `.jsx` 檔
- [ ] `uv run pytest -q` 全綠；ruff / ESLint 通過（CI 合規門檻）

### 依賴

無，可獨立開發（本 Issue 為全部 Issue 與 ET / DM 模組開發之前置）。

### 注意事項

- **遷移裁剪清單**（research §1）為本 Issue 最高風險點——照舊清單誤帶 `DP_SESSION` / RBAC / MFA / 開通信會與 spec 直接矛盾
- **既有骨架的 `base_model.py` 含 SITE 欄位**（TBMS 原封帶殘留，`CREATED_SITE` 還是必填）——T001 首步移除，否則 10 張 DP 表全會多兩個無資料來源的欄位（2026-07-09 現況盤點）
- 稽核前後值以 **TEXT 存 JSON**（型別規範不用 JSONB，research §6）
- 表 / 欄位命名 UPPER_SNAKE_CASE、型別限用集合，依 `sti-naming-conventions` 與 data-model DD
- Alembic 依 `sti-alembic-rules`；後端分層依 `sti-backend-modules` / `sti-backend-boundaries`（ET / DM 僅可經 SRVDP 介面使用平台能力）
- 啟動方式一律照 `README.md`「啟動開發環境」章節

### 相關文件

- [spec.md](spec.md)（模組總覽）、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[tasks.md](tasks.md) Phase 1–2
- [contracts/platform-services.md](contracts/platform-services.md)、[contracts/module-callbacks.md](contracts/module-callbacks.md)
- [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §3 / §4（遷移來源）

**Labels**：`priority:P0`, `DP-平台`（Foundation 無對應 US，免 US 標籤）

---

## Issue #1：[P1-核心] DP — 通知發送服務（發信引擎 + outbox）

**對應規格**：[spec_us6.md](spec_us6.md)（US6 / UCDP009，FR-DP-US6-01~06）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002）；[contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)；[research.md](research.md) §8；[data-model.md](data-model.md)（`DP_NOTIFY_TEMPLATE` / `DP_EMAIL_LOG`）
**階段**：P1-核心（`SRVDP002` 為 US3 密碼重設信、US8 帳號變更驗證信、SCHDP001 密碼到期提醒及各模組業務通知之前置；plan.md 開發順序 Foundation → **US6** → US1–US3）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_NOTIFY_TEMPLATE` / `DP_EMAIL_LOG` 表與 `MAIL` 平台參數種子、`SRVDP001` 參數服務、`app/services/__init__.py` 出口皆就緒
- 外部 SMTP 主機資訊可設定於 `backend/.env`

### 任務說明

實作全 EDMS 唯一發信服務 **SRVDP002 `send_email`** 與其非同步寄送管線：服務僅「渲染範本 + 逐收件人寫入 outbox（`DP_EMAIL_LOG` PENDING）」即返回，不阻塞呼叫方交易；實際寄送由 **FastAPI lifespan 常駐 asyncio worker**（非排程 job）依平台級 `MAIL` 參數輪詢 outbox、經外部 SMTP 寄送並更新 SENT / FAILED。完成後 ET / DM 及 DP 自身（US3 / US8 / SCHDP001）一律經此服務寄信，模組不自持範本、不自建佇列、不直連 SMTP。

> ℹ️ 本 US 為**背景服務、無使用者介面**（範本維護 UI 屬 US9 / Issue #9）；垂直切割在此為「服務 + outbox + worker + SMTP 介接」，無前端。

### 範圍

**後端**：
- **T018 [US6] SRVDP002 `send_email`**（`app/dp/notify/`，經 `app/services/__init__.py` 出口暴露）：依 `module` + `template_code` 查 `DP_NOTIFY_TEMPLATE` 啟用中範本（不存在 → raise `AppError`；停用 → `skipped_reason="TEMPLATE_DISABLED"`、`CHANNEL` 不含 Email → `skipped_reason="CHANNEL_NOT_EMAIL"`，皆不寄不報錯）、以 `params` 渲染主旨 / 內文、**逐收件人**寫 `DP_EMAIL_LOG`（PENDING、渲染快照 SUBJECT/BODY、`CALLER_MODULE`）即返回；對應 FR-01~04
- **T019 [US6] 常駐寄送 worker**（FastAPI lifespan 啟動之 asyncio task，**不入 `DP_SCHEDULE`**）：輪詢 PENDING，依平台級 `MAIL` 參數（`RATE_PER_MIN` / `RETRY_MAX` / `RETRY_INTERVAL_MIN`）限速 / 重試 / 間隔，經 SMTP 寄送更新 SENT / FAILED（單筆失敗不影響同批；變數缺漏該列標 FAILED 留錯誤訊息）；不內建告警（失敗率 / 積壓由 IT 監控）；對應 FR-02 / 05 / 06、research §8
- **T020 [US6] SMTP 介接**：`.env.example` 補 SMTP 連線設定、以渲染快照寄送；SMTP 不可用時信件停留 outbox、恢復後續寄不遺失；參照 [contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)

**前端**：無（純服務、無畫面）。

**測試**：
- 單元：範本渲染（變數代入 / 缺漏）、範本不存在 raise / 停用 skipped、渲染快照正確
- 整合（真實 DB）：`send_email` 逐收件人寫 PENDING 即返回（呼叫方交易未被阻塞）；worker 將 PENDING → SENT（SMTP 以測試替身 / mock 攔截）、失敗重試至上限標 FAILED；單筆失敗不影響同批；大量收件人全進 outbox

### 驗收條件

- [ ] `send_email(recipients, template_code, module, params, caller_module)` 對存在且啟用之範本，逐收件人寫 `DP_EMAIL_LOG`（PENDING、渲染快照、`CALLER_MODULE`）後**立即返回**，不同步寄送、不阻塞呼叫方交易
- [ ] `template_code` 不存在 → raise `AppError`（error_code 依 `sti-error-codes`）；範本停用 → 回 `skipped_reason="TEMPLATE_DISABLED"`、範本 `CHANNEL` 不含 Email（`MSG`）→ 回 `skipped_reason="CHANNEL_NOT_EMAIL"`，兩者皆不寫 outbox、不寄、呼叫方流程照常
- [ ] 常駐 worker（lifespan asyncio task，**不在 `DP_SCHEDULE`**）輪詢 PENDING，依 `MAIL` 參數限速 / 重試 / 間隔寄送，成功更新 SENT（記寄出時間）
- [ ] SMTP 失敗未達 `RETRY_MAX` 依 `RETRY_INTERVAL_MIN` 延遲重試（累計次數）；逾上限標 FAILED 並保留錯誤訊息
- [ ] 單筆收件人 / 變數缺漏失敗，同批其他收件人不受影響（該列 FAILED、其餘照寄）
- [ ] SMTP 長時間不可用時 PENDING 信件停留 outbox，SMTP 恢復後續寄、不遺失
- [ ] `uv run pytest -q` 全綠；ruff / ESLint 通過（CI 合規門檻）

### 依賴

- **Issue #0（GitHub #16）**：`DP_NOTIFY_TEMPLATE` / `DP_EMAIL_LOG` 表、`MAIL` 參數種子、`SRVDP001`、`AppError`、`app/services` 出口
- 外部 SMTP 郵件伺服器（跨系統介接，[contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)）

### 注意事項

- ✅ **環境變數命名已收斂**（2026-07-16）：統一為 fastapi-mail 慣例 `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_FROM` / `MAIL_STARTTLS`——`config.py` 之 `MAIL_HOST` 已更名 `MAIL_SERVER`，ext 契約 / tasks T020 之 `SMTP_*` 已同步改為 `MAIL_*`。`MAIL_SSL_TLS`（SSL 埠 465）/ `MAIL_SUPPRESS_SEND`（測試抑制送信）等 fastapi-mail 額外鍵，待 T020 實作接 fastapi-mail 時依需要再補。
- worker 為**常駐 asyncio task 非排程 job**（research §8）：秒級輪詢與 cron 語意不合，MUST NOT 登錄 `DP_SCHEDULE`；亦不引入 Celery / MQ（過度設計）。
- `DP_EMAIL_LOG` 允許狀態欄更新（含 `UPDATED_*`）、**不刪除**（outbox 歷程保留，data-model §標準欄位）；渲染以快照存 outbox，事後改範本不影響已排隊信件。
- 呼叫方 MUST 於自身交易 **commit 後**呼叫 `send_email`（避免業務回滾但信已排隊，contracts SRVDP002 規則）。
- 渲染變數來源為呼叫方 `params`，範本變數以定義為準；避免將未跳脫的使用者輸入直接注入 HTML 主旨 / 內文（安全，交由 Security Review 於實作把關）。
- SMTP 帳密走 `config` / `.env`，禁硬編碼；`PWD_HASH` / SMTP 密碼 / 收件人完整個資之寫 log 規範依 `sti-backend-logging`。

### 相關文件

- [spec_us6.md](spec_us6.md)、[spec.md](spec.md) §通知範本與發信引擎、[plan.md](plan.md)、[research.md](research.md) §8、[data-model.md](data-model.md)（`DP_NOTIFY_TEMPLATE` / `DP_EMAIL_LOG`）、[tasks.md](tasks.md) Phase 3（T018~T020）
- [contracts/platform-services.md](contracts/platform-services.md)（SRVDP002）、[contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md)
- 需求：[RQDP.md](../../requirements/RQDP.md) §通知範本與發信引擎；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP009

**Labels**：`P1-核心`, `DP-平台`, `US6`

---

## Issue #2：[P1-核心] DP — 登入 / 登出與模組入口頁

**對應規格**：[spec_us1.md](spec_us1.md)（US1 / UCDP001，FR-DP-US1-01~11、AC 1~12、DP-MSG-DP01-001~008）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §1（is_module_admin）/ §4（has_any_role）；[research.md](research.md) §2（短 TTL + 活動換發）/ §3（每請求查 DP_USER）/ §12（redirect + 入口頁）；[data-model.md](data-model.md)（`DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁 + 模組入口頁）
**階段**：P1-核心（全系統存取基礎；認證鏈 US1 → US2 → US3 起點）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：JWT 基礎（T013）、認證閘 `get_jwt_payload`（T014）、速率限制（T015）、密碼策略（T016）、模組管理者判定閘（T017）、`SRVDP001`、`DP_USER` 表皆就緒
- 帳號來源：US2 自助註冊 / US4 代建（測試期可直接建 `DP_USER`）

### 任務說明

實作帳密登入核發 JWT、活動換發 / 登出、帳號鎖定與強制變更密碼閘、以及登入後的模組入口頁。登入驗 `DP_USER`（bcrypt 比對）、區分帳號不存在 / 密碼錯誤、失敗計數達上限自動鎖定、成功歸零計數 + 更新 `LAST_LOGIN` + 核發 JWT（`auth_time` + 15 分 TTL）+ 寫登入稽核；換發沿用 T013 邏輯 + 帳號狀態檢核；登出寫稽核（前端丟棄 token）。前端登入頁掛速率限制 + redirect 白名單返回原頁 + 閒置換發計時器；入口頁 ET 恆顯、DM 卡雙狀態（未開通鎖定卡）、不顯後台入口、首次登入歡迎橫幅一次。

> ℹ️ 全端 issue：後端登入 / 換發 / 登出 / 強制變更閘 / 模組角色摘要端點 + 前端登入頁 / 入口頁。跨模組 `is_module_admin` / `has_any_role` 以 **stub 先行**（ET/DM 未實作，經 T017 判定閘注入）。

### 範圍

**後端**：
- **T021 登入端點**（`dp/user`）：帳密驗證（bcrypt）、錯誤分流（帳號不存在 / 密碼錯誤）、鎖定判定（`LOCKED_UNTIL` 逾時視為已解鎖）、失敗計數 / 達 `FAIL_LOCK_COUNT` 自動鎖定、成功歸零 + 更新 `LAST_LOGIN` + 核發 JWT + LOGIN 稽核（含 FAIL 事件、來源 IP）；對應 FR-02/04/05/08
- **T022 換發 `renew` + 登出端點**：renew 走 T013 `renew_access_token`（驗現行 token + 8h 上限）+ 帳號狀態檢核；登出寫 LOGOUT 稽核（前端丟 token）；對應 FR-03/10
- **T023 強制變更密碼閘**：登入 / 每請求檢核 `MUST_CHANGE_PWD` 或 `PWD_CHANGED_DATE` 逾效期 → 回強制變更旗標；未完成變更前其他端點拒絕；對應 FR-06、spec_us8 FR-DP-US8-08
- **T025 後端「我的模組角色摘要」端點**：聚合各模組 `has_any_role`（經 T017 閘 / stub）決定入口頁 DM 卡狀態；對應 FR-07、module-callbacks §4

**前端**：
- **T024 登入頁**：帳密欄（密碼遮蔽）、錯誤訊息（DP-MSG-DP01-001~008）、redirect 白名單返回原目標頁（通知信連結 / 書籤 / 逾時重登）、閒置換發計時器（到期前有操作即 renew）、掛速率限制回應（429 → LOGIN-007）；對應 FR-01/07/09
- **T025 模組入口頁**：ET 入口恆顯、**DM 卡雙狀態**（無 DM 角色呈「未開通」鎖定卡 + 引導文字 DP-MSG-DP01-008、點擊不進入）、個資恆顯、**不顯 DP 後台入口**、首次登入歡迎橫幅一次（已顯示旗標儲存位置實作定）；對應 FR-07、research §12

**測試**：
- 後端：登入成功 / 帳號不存在 / 密碼錯誤 / 失敗計數→鎖定 / 鎖定逾時解鎖 / 停用拒絕 / 強制變更旗標 / 換發沿用 auth_time / 逾 8h 拒絕 / 登出稽核；速率限制 429；角色摘要端點（stub）
- 前端：登入流程（MSW）、錯誤訊息呈現、redirect 返回、入口頁 DM 卡雙狀態

### 驗收條件

- [ ] 正確帳密 → 核發 JWT（含 `auth_time`、TTL 15 分）、重設失敗計數、更新 `LAST_LOGIN`、寫 LOGIN 稽核
- [ ] 帳號不存在 / 密碼錯誤 → 分別回對應訊息（DP-MSG-DP01-001 / 002）；密碼錯誤累計失敗計數
- [ ] 連續失敗達 `FAIL_LOCK_COUNT`（預設 5）→ 自動鎖定 + 稽核；鎖定中 / 停用 / 閒置逾 90 日禁用 → 拒絕登入（LOGIN-003 / 004）；`LOCKED_UNTIL` 逾時自動解鎖
- [ ] 密碼逾效期 / 初始密碼（`MUST_CHANGE_PWD`）登入 → 導向強制變更、未完成前其他端點拒絕（LOGIN-005）
- [ ] 閒置逾 15 分 token 自然失效；有操作靜默換發；自登入起換發逾 8h 上限 → 拒絕需重登
- [ ] 登入端點以「IP + 帳號」速率限制超限回 429（LOGIN-007）
- [ ] 登出 → 前端丟 token + 寫 LOGOUT 稽核；停用帳號之未逾期 token 下次請求被拒（T014 閘）
- [ ] 登入後 redirect：被攔者返回原目標頁（白名單防 open redirect）；無目標 → 入口頁
- [ ] 入口頁：ET 恆顯、DM 卡無角色呈未開通鎖定卡（點擊 LOGIN-008 不進入）、不顯後台入口、首次登入歡迎橫幅一次
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：JWT / 認證閘 / 速率限制 / 密碼策略 / 模組管理者閘 / SRVDP001 / DP_USER
- **跨模組（stub 先行）**：ET / DM 之 `is_module_admin`、`has_any_role`（module-callbacks §1 / §4）——ET/DM 未實作，經 T017 判定閘注入 stub；入口頁 DM 卡完整狀態待 US7 + 模組 service 到位
- 帳號資料：US2 / US4（測試期可自建）

### 注意事項

- ✅ **帳號列舉：採明確訊息**（已於 `spec_us1` Clarification 2026-07-16 定案）：區分「帳號不存在（LOGIN-001）/ 密碼錯誤（LOGIN-002）」——內部系統易用性優先；列舉風險以**帳號維度速率限制**緩解（先 hit 帳號限流、後查存在性，避免以 429 反推；#23）。error code 採分離碼（帳號不存在 / 密碼錯誤各一，非合併的 `DP_AUTH_001`）；`DP_AUTH_004`（停用）/ `DP_AUTH_005`（鎖定）/ `COMMON_429`（速率）已就緒。強制變更為回應旗標、非 error。
- ✅ **強制變更密碼範圍**（已於 `spec_us1` Clarification 定案）：US1 做**閘 + 導向 + 頁面殼**（檢核 `MUST_CHANGE_PWD` / 逾效期 → 擋下其他端點 + 導向）；**實際變更提交端點與檢核屬 US8**。US8 未就緒時以最小提交 / stub 先行，US1 驗收以「閘正確擋下 + 導向」為準。
- **換發端點狀態閘**（Foundation #16 Security L-1 前瞻）：`renew` MUST 先過 DP_USER 狀態檢核，否則停用 / 鎖定帳號可持有效 token 自我續票。
- **登入速率限制帳號維度防列舉**（#23 相關）：登入須「先 hit 帳號限流、後查帳號存在性」，避免以 429 觸發與否探測帳號存在。
- 稽核：登入 / 登出 / 鎖定 / 解鎖經 `SRVDP003.log_action`（含來源 IP，走 request_context）。
- 密碼 / token 不入 log（sti-backend-logging）；HTTPS 傳輸、redirect open-redirect 白名單。

### 相關文件

- [spec_us1.md](spec_us1.md)、[spec.md](spec.md) §認證機制、[research.md](research.md) §2/§3/§12、[data-model.md](data-model.md)（DP_USER）、[tasks.md](tasks.md) Phase 4（T021~T025）
- [contracts/module-callbacks.md](contracts/module-callbacks.md)（is_module_admin / has_any_role）
- 需求：[RQDP.md](../../requirements/RQDP.md) §登入認證 / §帳號鎖定；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP001

**Labels**：`P1-核心`, `DP-平台`, `US1`

---

## Issue #3：[P1-核心] DP — 使用者自助註冊

**對應規格**：[spec_us2.md](spec_us2.md)（US2 / UCDP002，FR-DP-US2-01~06、DP-MSG-DP02-001~004）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §2（`grant_default_student_role`）；[data-model.md](data-model.md)（`DP_USER` / `DP_PWD_HIST`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁・註冊頁籤）
**階段**：P1-核心（帳號來源主路徑；認證鏈 US1 登入 → **US2 註冊** → US3 忘記密碼）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：密碼策略工具（T016，複雜度 / bcrypt / `DP_PWD_HIST` 歷程）、`SRVDP003` 稽核、`DP_USER` / `DP_PWD_HIST` 表、`SRVDP001` 平台參數皆就緒
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：登入頁 overlay（「註冊」為其頁籤）、前端 `authService` / `http` client 結構
- 跨模組 ET `grant_default_student_role`（module-callbacks §2）——ET 未實作，以 **stub 先行**

### 任務說明

實作登入頁「註冊」頁籤之自助註冊：伺服器端檢核 Email 未被註冊（`DP_USER` 唯一）、密碼符合複雜度、兩次輸入一致；通過後建立 `DP_USER`（bcrypt 雜湊、狀態 ACTIVE）、寫入 `DP_PWD_HIST` 首筆（作為後續密碼重複性檢核基準）、於**帳號建立當下**透過 ET service 授予「學員」（唯一預設角色，受訓單位標籤預設「未指派」）、寫 CREATE 稽核；成功後跳回登入頁預填 Email（**註冊即用，不寄帳號開通確認信**）。

> ℹ️ 全端 issue：後端註冊端點 + 前端註冊頁籤。跨模組 ET `grant_default_student_role` 以 **stub 先行**（ET 未實作，依 module-callbacks §2 簽章注入；模組實作跟進後於 T047 回歸）；**MUST NOT 授予任何 DM 角色或 ET 教師 / 管理者角色**（DM 存取一律由管理者於 US7 開通）。

### 範圍

**後端**：
- **T026 註冊端點**（`dp/user`）：伺服器端檢核 Email 唯一（`DP_USER`）/ 密碼複雜度（一般使用者，`SRVDP001` 讀 `MIN_LEN`=8 / `CHAR_TYPES`=3，**不套** `ADMIN_MIN_LEN`）/ 兩次一致；通過建 `DP_USER`（bcrypt 雜湊、`STATUS`=ACTIVE）+ `DP_PWD_HIST` 首筆 + 呼叫 ET `grant_default_student_role`（stub）+ CREATE 稽核（帳號建立 + 角色授予）；對應 FR-02/03/05/06
- **T027 前端註冊頁籤**：登入頁「註冊」頁籤欄位（Email 必填 + 格式、姓名必填、密碼 / 確認密碼遮蔽），Zod 前端驗證 + 錯誤訊息（DP-MSG-DP02-001~004），成功跳回登入頁預填 Email；對應 FR-01/04

**測試**：
- 後端：未註冊 Email + 合規密碼 → 建帳號（bcrypt 雜湊、ACTIVE）+ ET 學員授予（驗 stub 被呼叫）+ `DP_PWD_HIST` 首筆 + CREATE 稽核；Email 重複拒（REGISTER-001）；密碼不合規拒（REGISTER-002）；兩次不一致拒（REGISTER-003）；**不授予任何 DM 角色**
- 前端：註冊流程（MSW）、各錯誤訊息呈現、成功跳回登入頁且預填 Email

### 驗收條件

- [ ] 未註冊 Email + 密碼合規（複雜度 + 兩次一致）→ 建立 `DP_USER`（密碼 bcrypt 雜湊、`STATUS`=ACTIVE）、透過 ET service 授予 ET 學員（受訓單位標籤「未指派」）、寫 `DP_PWD_HIST` 首筆、寫 CREATE 稽核，回 REGISTER-004 並跳回登入頁預填 Email
- [ ] 註冊完成之新使用者僅具 ET 學員角色；**DM 四角色皆未授予**（不自動授予，DM 存取須管理者於 US7 開通）
- [ ] Email 已被註冊 → 阻擋並提示 REGISTER-001（引導改走登入 / 忘記密碼）
- [ ] 密碼不符複雜度（一般使用者至少 8 字元、至少 3 種字元組合）→ 阻擋並提示 REGISTER-002
- [ ] 兩次密碼輸入不一致 → 阻擋並提示 REGISTER-003
- [ ] 三項檢核（Email 唯一 / 複雜度 / 兩次一致）MUST 於**伺服器端**執行；**不寄帳號開通確認信**（註冊即用）
- [ ] 帳號建立與 ET 學員角色授予皆寫入 `DP_AUDIT_LOG`
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：密碼策略工具（T016）、`SRVDP001`（`PWD_POLICY` 參數）、`SRVDP003` 稽核、`DP_USER` / `DP_PWD_HIST` 表
- **Issue #2（GitHub #31）**：登入頁 overlay（註冊為其頁籤）、前端 `authService` / `http` client
- **跨模組（stub 先行）**：ET `grant_default_student_role`（module-callbacks §2）——ET 未實作以 stub（冪等，已存在不重複）注入，完整驗收待 ET service 就緒後於 T047 回歸；**DM 無對應介面**（DM 角色一律 US7 開通）

### 注意事項

- **預設角色僅 ET 學員、帳號建立當下授予**（`spec.md` Clarifications 釐清第 3 輪）：MUST NOT 授予 DM 或 ET 教師 / 管理者角色；ET service 未就緒前以 contracts §2 簽章 stub 先行、冪等。
- **角色授予稽核由 DP 端寫**（`spec_us2` Clarifications 2026-07-20）：DP 呼叫 `grant_default_student_role`（stub）後於**同交易**自行經 `SRVDP003` 寫「授予預設 ET 學員角色」稽核（`MODULE=DP`）→ stub 期即可驗 AC6；稽核 `operator_id` 填**新使用者本人 USER_ID**（自助註冊為本人行為）。
- **密碼複雜度為平台級參數**（`SRVDP001`）：一般使用者用 `MIN_LEN`=8 / `CHAR_TYPES`=3；註冊者非管理者，不套 `ADMIN_MIN_LEN`=12。
- **帳號建立 + 角色授予 + 首筆歷程 + 稽核同交易**：確保「建帳號但漏授角色 / 漏寫歷程」不發生；Email 唯一由 DB `UNIQUE` + 伺服器端檢核雙重把關。
- **Error codes**（實作 / `/sti-plan` 時對齊 `sti-error-codes`）：密碼複雜度可重用 `DP_PWD_001`（長度）/ `DP_PWD_002`（複雜度）；Email 重複新增碼（409，如 `DP_USER_*`）；兩次不一致以前端 Zod + 後端 422 把關。
- **前端表單驗證用 Zod**（`sti-zod-conventions`，`LoginRequest`→`RegisterRequestSchema` 命名對齊後端 Pydantic）；密碼 / token 不入 log（sti-backend-logging）。
- 稽核經 `SRVDP003.log_action`（`target_id` 必填、含來源 IP，走 request_context）。

### 相關文件

- [spec_us2.md](spec_us2.md)、[spec.md](spec.md) Clarifications 釐清第 3 輪、[data-model.md](data-model.md)（`DP_USER` / `DP_PWD_HIST`）、[tasks.md](tasks.md) Phase 5（T026~T027）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §2（`grant_default_student_role`）
- 需求：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP002

**Labels**：`P1-核心`, `DP-平台`, `US2`

---

## Issue #4：[P1-核心] DP — 忘記密碼

**對應規格**：[spec_us3.md](spec_us3.md)（US3 / UCDP003，FR-DP-US3-01~08、DP-MSG-DP03-001~006）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002 發信）；[research.md](research.md) §5（token 明文入信 / SHA-256 入庫）；[data-model.md](data-model.md)（`DP_PWD_RESET` / `DP_PWD_HIST` / `DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁・忘記密碼 + 重設密碼頁）
**階段**：P1-核心（帳號自救路徑；認證鏈 US1 登入 → US2 註冊 → **US3 忘記密碼**，補齊 P1 認證鏈 MVP）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_PWD_RESET` / `DP_PWD_HIST` 表、密碼策略工具（T016，複雜度 / 重複性 / bcrypt）、速率限制（T015）、`SRVDP001`（`LOGIN.RESET_TOKEN_TTL_MIN`=30 / `PWD_POLICY.HISTORY_COUNT`=3 參數）、`SRVDP003` 稽核
- Issue #1（GitHub [#27](https://github.com/sti-fhb/EDMS/issues/27)）已合併：`SRVDP002` 發信服務 + outbox + `DP` 密碼重設範本（`PWD_RESET`，變數 `user_name / reset_link / expiry_minutes`）——**非 stub、可直接呼叫**
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：登入 overlay（「忘記密碼」為其入口）

### 任務說明

實作忘記密碼自救：申請端點（輸入 Email → 防列舉統一回覆 → 存在帳號才產生一次性時效 token 並經 SRVDP002 寄重設信）與重設端點 / 頁面（驗 token → 檢核新密碼複雜度 + 重複性 → 更新 `DP_USER` + 追加 `DP_PWD_HIST` + 作廢 token + 寫密碼重置稽核）。token 明文僅入信中連結、DB 只存其 SHA-256（research §5）；同帳號重新申請舊 token 立即失效；**密碼重設 MUST NOT 解除鎖定 / 停用**。

> ℹ️ 全端 issue：後端申請 / 重設兩端點 + 前端忘記密碼表單 / 重設密碼頁。發信經 **SRVDP002（US6 已交付、非 stub）**；申請與重設端點皆掛速率限制（IP + 帳號）。

### 範圍

**後端**（`app/dp/user/`）：
- **T028 申請端點**：輸入 Email → **防列舉統一回覆**（DP-MSG-DP03-001，不論存在與否；帳號不存在不產 token / 不寄信）；存在帳號產生一次性時效 token（明文入信、SHA-256 入 `DP_PWD_RESET`，TOKEN_TYPE=`PWD_RESET`，EXPIRES_DATE=now+`RESET_TOKEN_TTL_MIN`）、**同帳號同型舊 token 立即作廢**、經 `SRVDP002` 寄 `PWD_RESET` 範本；掛速率限制（IP + 帳號，先限流後查存在性）；對應 FR-01~04/08
- **T029 重設端點**：驗 token（查 SHA-256、未逾時、未使用；否則 FORGOT-002）→ 新密碼複雜度（`validate_password_strength`）+ 重複性（`is_reused` 查最近 `HISTORY_COUNT` 筆 `DP_PWD_HIST`）→ 更新 `DP_USER.PWD_HASH` / `PWD_CHANGED_DATE`、追加 `DP_PWD_HIST`、作廢 token（設 USED_DATE）、寫密碼重置稽核；**不解除 `LOCKED_UNTIL` / `STATUS`**；對應 FR-05~07

**前端**（`frontend/src/auth/`）：
- **T028 前端** 忘記密碼表單：登入 overlay 內「忘記密碼」→ 輸入 Email → 送出後顯示統一提示（FORGOT-001，防列舉）
- **T029 前端** 重設密碼頁：信中連結落點（帶 token）→ 新密碼 / 確認密碼（Zod：複雜度 + 兩次一致）→ 送出；成功提示（FORGOT-005）跳回登入；token 失效顯示 FORGOT-002

**測試**：
- 後端 int：申請（存在→產 token + 寄信 + 舊 token 作廢；不存在→同訊息不產 token；限流 429）；重設（成功更新 + 歷程 + 稽核 + token 作廢；逾時 / 已用 token 拒；複雜度 / 重複性拒；鎖定 / 停用帳號重設成功但狀態不變）
- 前端：忘記密碼流程（MSW）統一提示；重設頁複雜度 / 兩次一致錯誤 / 成功跳回；token 失效態

### 驗收條件

- [ ] 申請忘記密碼：不論 Email 是否存在皆回相同訊息（FORGOT-001，防列舉）；存在帳號才產生一次性時效 token（TTL `RESET_TOKEN_TTL_MIN`，預設 30 分）寫入 `DP_PWD_RESET`（SHA-256）並經 SRVDP002 寄 `PWD_RESET` 範本
- [ ] token 明文僅存於信中連結，DB 僅存 SHA-256；同帳號重新申請 → 舊 token 立即失效（一次性）
- [ ] 效期內點連結、token 驗證通過 → 進重設頁；輸入新密碼通過複雜度 + 重複性（禁最近 `HISTORY_COUNT` 次）→ 更新 `DP_USER` + 追加 `DP_PWD_HIST` + 作廢 token + 寫密碼重置稽核，提示 FORGOT-005
- [ ] token 逾時 / 已使用 → 拒絕並提示 FORGOT-002
- [ ] 新密碼不符複雜度 / 與最近 N 次相同 → 阻擋並提示 FORGOT-003 / 004；檢核皆伺服器端
- [ ] 帳號鎖定 / 停用時仍回相同申請訊息；重設成功**不解除**鎖定 / 停用（`LOCKED_UNTIL` / `STATUS` 不變）
- [ ] 忘記密碼申請 / 重設端點以「IP + 帳號」速率限制超限回 429（FORGOT-006）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`DP_PWD_RESET` / `DP_PWD_HIST` 表、密碼策略（複雜度 / `is_reused`）、速率限制、`SRVDP001`（TTL / HISTORY_COUNT 參數）、`SRVDP003`
- **Issue #1（GitHub #27）**：`SRVDP002` 發信 + `PWD_RESET` 範本（**非 stub、直接呼叫**）
- **Issue #2（GitHub #31）**：登入 overlay（忘記密碼入口）
- 外部 SMTP 可用（US6 已介接）

### 注意事項

- **防帳號列舉**（FR-03）：申請一律回 FORGOT-001（成功語氣）、不因帳號存在與否改變回應或時序；帳號維度速率限制先 hit 後查存在性（同 US1，#23 相關）。不存在帳號**不產 token、不寄信**。
- **token 安全**（research §5）：明文 token 僅入信中連結，DB 存 SHA-256（`DP_PWD_RESET.TOKEN_HASH`）；一次性（USED_DATE）＋時效（EXPIRES_DATE）；同帳號重新申請作廢舊 token（作廢舊列 USED_DATE 或刪除，查 `(USER_ID, TOKEN_TYPE, USED_DATE)` 索引）。
- **重設不改帳號狀態**（FR-07）：即使帳號鎖定 / 停用，重設密碼成功也 MUST NOT 清 `LOCKED_UNTIL` / 改 `STATUS`（解鎖 / 啟用屬 US4 管理者）。
- **reset_link 組法**（spec_us3 Clarifications 2026-07-20）：後端組 `reset_link = {FRONTEND_BASE_URL}/reset-password?token=<明文>`；`FRONTEND_BASE_URL` 為**後端設定**（`config.py` + `.env`，dev 預設 `http://localhost:5173`），**不放 DP_PARAM**（base URL 因部署環境而異，性質同 DATABASE_URL / CORS_ORIGINS）。範本變數以種子為準：`user_name / reset_link / expiry_minutes`（單括號 `{var}`）。
- **重設密碼頁 UI**（spec_us3 Clarifications 2026-07-20）：沿用 US1 強制變更頁殼樣式（`login-force-change`：新密碼 + 確認 + 警告 Alert），為 token 落點獨立頁；token 失效顯 FORGOT-002、成功顯 FORGOT-005 後導回登入。
- **Error codes**（對齊 `sti-error-codes`）：token 逾時 / 已用新增碼（如 `DP_PWD_005`，400/410）；複雜度重用 `DP_PWD_001/002`、重複性重用 `DP_PWD_003`；限流 `COMMON_429`。FORGOT-001/005 為提示 / 成功、非 error。
- 密碼 / token 不入 log / 稽核（sti-backend-logging）；稽核經 `SRVDP003.log_action`（含來源 IP）。
- 前端表單用 Zod（`sti-zod-conventions`）；密碼欄遮蔽。

### 相關文件

- [spec_us3.md](spec_us3.md)、[research.md](research.md) §5、[data-model.md](data-model.md)（`DP_PWD_RESET`）、[tasks.md](tasks.md) Phase 6（T028~T029）
- [contracts/platform-services.md](contracts/platform-services.md)（SRVDP002）
- 需求：[RQDP.md](../../requirements/RQDP.md) §忘記密碼；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP003

**Labels**：`P1-核心`, `DP-平台`, `US3`

---

## Issue #5：[P1-核心] DP — 使用者管理（dp-users）

**對應規格**：[spec_us4.md](spec_us4.md)（US4 / UCDP005，FR-DP-US4-01~09、DP-MSG-DP05-001~005）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §1（`is_module_admin`）/ §2（`grant_default_student_role`）；[data-model.md](data-model.md)（`DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-users`）
**階段**：P1-核心（管理者日常必要作業：建帳號 / 停用 / 解鎖 / 維護；帳號為 ET / DM 共用項）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_USER` 表、密碼策略（複雜度 / bcrypt）、`SRVDP001`（PWD_POLICY）、`SRVDP003` 稽核、`paginate()`、模組管理者判定閘 `module_admin_gate`（T017，`is_module_admin`）
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：登入（管理者需登入操作）、後台 layout 骨架（`DpLayout` / `Sidebar` / `AppHeader`，T010）
- Issue #3（GitHub [#39](https://github.com/sti-fhb/EDMS/issues/39)）已合併：`module_provisioning` 授予閘 + `ids.generate_user_id` + 密碼歷程寫入（**US4 代建帳號沿用 US2 這套授學員邏輯**）

### 任務說明

DP 後台使用者管理頁（ET / DM 共用）：查詢（Email / 姓名 / 狀態，後端分頁）、建立帳號（管理者設初始密碼 + `MUST_CHANGE_PWD` + 授 ET 學員）、停用 / 啟用、解鎖、基本資料維護（姓名 / Email 直接生效、不走驗證信），全數寫稽核（含前後值）。**自我保護**：不可停用 / 鎖定自己；**不檢核**「至少保留 1 名管理者」。角色指派不在本頁（屬 US7）。

> ⚠️ **本 issue 是第一個 DP 後台 CRUD 頁，需一併 bootstrap 前後端 CRUD 共用基礎設施**（見範圍）——這批共用元件將被 US5 / US7 / US9 / US10 後續後台頁沿用，故投資一次、之後複用。

### 範圍

**後端**（`app/dp/users/` — 人員管理 CRUD，與 `dp/user` 認證模組分開；`DpUser` model 已在此）：
- **共用 bootstrap**：`app/core/operator.py`（**新**：`OperatorInfo` + `get_operator` Dependency，寫入型 API 填 `CREATED_*` / `UPDATED_*` 用，sti-backend-modules 規範；目前 core 尚無此檔）
- **T030 查詢端點**：`GET /api/dp/users`（Email / 姓名 / 狀態篩選 + `paginate()` 後端分頁）；回列表（Email、姓名、狀態、鎖定狀態、最後登入）；`router → service → repository`
- **T031 建立帳號**：`POST /api/dp/users`（管理者設初始密碼〔複雜度〕→ 建 `DP_USER`〔`MUST_CHANGE_PWD=true`〕+ 授 ET 學員〔`module_provisioning`，同 US2〕+ 首筆 `DP_PWD_HIST` + CREATE 稽核；Email 唯一 USERS-005，`operator`=管理者）
- **T032 停用 / 啟用 / 解鎖 / 基本資料**：停用（`STATUS=DISABLED`，**自我保護** USERS-001）/ 啟用 / 解鎖（`login_fail_count=0` + `locked_until=None`，USERS-004）/ 維護姓名 / Email（直接生效、Email 唯一、不走驗證信）；全寫稽核（**含 before / after value**）

**前端**（`frontend/src/dp/users/` + 共用）：
- **共用 bootstrap（第一個 CRUD 頁）**：依 [sti-frontend-modules](../../../.claude/rules/sti-frontend-modules.md) / [sti-ui-design](../../../.claude/rules/sti-ui-design.md) 建立 `CrudPageLayout`、`AppTable`、`Pagination`、`FormCard`、`CrudActions`、`useCrudForm`、`usePagedQuery`、`useNotification`（含確認對話框）、`columnFactories`（statusColumn）、`QUERY_KEYS.users`——目前皆尚未建立
- **T030 前端** 填實 `UsersPage`（現為 stub）：`CrudPageLayout` 清單 + 篩選（Email / 姓名 / 狀態）+ 後端分頁
- **T031 前端** 建立帳號表單（`FormCard`，Zod：Email / 姓名 / 初始密碼複雜度）
- **T032 前端** 停用二次確認（`useNotification.confirm`，USERS-002）、解鎖 / 啟用按鈕、編輯表單；成功 / 錯誤訊息（USERS-001~005）

**測試**：
- 後端 int：查詢（篩選 + 分頁）；建立（`MUST_CHANGE_PWD` + 授學員 + 首筆歷程 + Email 重複 409 + 稽核）；停用（+ 自我保護擋自己）；啟用；解鎖（計數歸零）；基本資料（Email 唯一、before/after 稽核）
- 前端：清單 / 篩選（MSW）、建立、停用確認、解鎖 / 啟用、編輯

### 驗收條件

- [ ] 查詢（Email / 姓名 / 狀態，後端分頁）列出使用者（Email、姓名、狀態、鎖定狀態、最後登入）；ET / DM 管理者所見相同
- [ ] 建立帳號：管理者設初始密碼（複雜度）→ 建 `DP_USER` + `MUST_CHANGE_PWD=true` + 依 US2 規則授 ET 學員 + 首筆 `DP_PWD_HIST`；Email 重複 → USERS-005；成功 → USERS-003；**不寄開通確認信**
- [ ] 停用：二次確認（USERS-002）→ `STATUS=DISABLED`，ET / DM 兩端同步失效（每請求查 DP_USER 狀態，T014）；寫稽核
- [ ] 啟用：停用（含閒置 90 日禁用）帳號恢復可登入；寫稽核
- [ ] 解鎖：`login_fail_count` 歸零 + 解除 `LOCKED_UNTIL` → USERS-004；寫稽核
- [ ] 基本資料：管理者代改姓名 / Email 直接生效（不走驗證信）；Email 重複擋（USERS-005）；寫稽核
- [ ] **自我保護**：不可停用 / 鎖定自己（USERS-001）
- [ ] **不檢核**「至少保留 1 名管理者」（0 名時允許，由 IT 經 DB 恢復）
- [ ] 建立 / 停用 / 啟用 / 解鎖 / 基本資料異動皆寫 `DP_AUDIT_LOG`（含異動前後值）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（#16）**：`DP_USER`、密碼策略、`SRVDP001` / `SRVDP003`、`paginate()`、`module_admin_gate`
- **Issue #2（#31）**：登入、後台 layout 骨架
- **Issue #3（#39）+ US2 #56**：`module_provisioning`（授學員）+ `ids.generate_user_id` + 密碼歷程寫入（代建沿用）。#56 已把「建帳號 + 啟用副作用」落地於 `AuthRepository`（`dp/user`），代建**重用勿重寫**：`create_user()`（建 `DP_USER` ACTIVE）、`add_pwd_history()`（首筆歷程）、`module_provisioning_gate.grant_default_role("ET", ...)`、雙稽核樣式（`verify_service._audit_register`）。
- **跨模組（stub 先行）**：ET `grant_default_student_role`（同 US2，stub）；`is_module_admin`（ET / DM checker stub，見注意事項）——完整 admin 驗收待模組 service 就緒於 T049 回歸

### 注意事項

- ⚠️ **admin 授權閘（開發前須釐清，列為 SA Q）**：FR-01 要求「ET / DM 管理者皆可、一般使用者不可」。`module_admin_gate`（T017）提供 `is_module_admin`，但 ET / DM checker 為 **stub（fail-closed False）** → 若直接掛「須 ET 或 DM 管理者」閘，現況無人可通過、頁面無法驗收。且 [sti-backend-modules 暫行授權規則](../../../.claude/rules/sti-backend-modules.md)明訂「全域授權機制未實作前，CUD 僅注入 `get_operator`、**不加** `require_admin`」。→ 二擇一待 `/sti-plan` 釐清：(a) 依暫行規則先以 `get_jwt_payload` 認證、admin 閘待模組 service（T049 回歸）；(b) 掛 `require_module_admin`（ET 或 DM）+ 測試注入 stub。
- ⚠️ **第一個 CRUD 頁 = 前後端 CRUD 基礎設施 bootstrap**：前端 CrudPageLayout / AppTable / Pagination / FormCard / CrudActions / useCrudForm / usePagedQuery / useNotification / columnFactories、後端 `core/operator.py`（`get_operator`/`OperatorInfo`）皆尚未建立；多由 TBMS 既有實作**移植**（API 已驗證，見 sti-frontend-modules / sti-backend-modules）；後續 US5 / US7 / US9 / US10 後台頁沿用。
  - **交付方式（決策 2026-07-21）**：於 **US4 同一分支拆兩支 PR**——**PR1** 移植 CRUD toolkit + `get_operator`（由 US4 當首個消費者驗證、只移植 US4 需要的最小集，不臆測擴充）；**PR2** US4 使用者管理功能（T030~T032）。不另開獨立 infra issue（避免無消費者的臆測抽象；對齊 US1 於功能內 bootstrap 資料層之先例）。`/sti-plan` 時據此排實作順序。
- **停用「ET / DM 同步失效」**非本 issue 新增機制：靠 `get_jwt_payload` 每請求查 `DP_USER.STATUS`（T014），停用即下次請求 403。
- **代建 operator = 管理者**（對照 US2 自助註冊 operator = 本人）；建帳號重用 #56 的 `create_user` + `module_provisioning` + `generate_user_id` + `add_pwd_history`，惟 `MUST_CHANGE_PWD=true`（初始密碼強制變更）。
  - ⚠️ **`create_user` 需加參數**：#56 的 `AuthRepository.create_user` 寫死 `must_change_pwd=False`（自助註冊者自設密碼、不強制變更，屬正確設計）。US4 代建須傳 `True` → 為 `create_user` 補一個 `must_change_pwd: bool = False` 參數（預設不變、不影響 US2），**勿另寫一份建帳號邏輯**。
  - **首登強制變更為分析文件明載需求**（來源：[spec.md](spec.md#L59) 釐清第 1 輪 2026-07-08、[data-model.md](data-model.md#L159) `MUST_CHANGE_PWD`、FR-DP-US4-03、FR-DP-US1-06、FR-DP-US8-08）。閘與頁殼 US1 已備（`core/password_gate.py` T023 → 403 `DP_AUTH_009`、前端 `ForceChangePasswordShell`）；US4 建的帳號一登入即被 gate 導向。實際變更提交端點屬 US8。
- **Email 唯一**：DB `UNIQUE` + 伺服器端檢核（建立同 US2；編輯時排除自己）。
- 稽核經 `SRVDP003.log_action`（`target_id`=USER_ID 必填、含 before/after value、來源 IP）；密碼不入 log。
- 角色指派 MUST NOT 於本頁（US7）；目錄 `dp/users`（CRUD）與 `dp/user`（認證）分開（sti-api-routes）。

### 相關文件

- [spec_us4.md](spec_us4.md)、[spec.md](spec.md) §模組過濾與共用項 / §帳號鎖定與閒置控管、[data-model.md](data-model.md)（`DP_USER`）、[tasks.md](tasks.md) Phase 7（T030~T032）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §1 / §2
- 需求：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理 / §帳號鎖定；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP005

**Labels**：`P1-核心`, `DP-平台`, `US4`

---

## Issue #6：[P1-核心] DP — 系統參數與清單維護（dp-params）

**對應規格**：[spec_us5.md](spec_us5.md)（US5 / UCDP006，FR-DP-US5-01~07、DP-MSG-DP07-001~005）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP001）；[research.md](research.md) §7（`DP_PARAM` M/D 二層 / 前綴歸屬 / `DETAIL_LOCK` / 唯讀不快取）；[data-model.md](data-model.md)（`DP_PARAM_M` / `DP_PARAM_D`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-params`）
**階段**：P1-核心（全平台參數與清單定義之單一維護入口；ET / DM 業務下拉 / 產碼 / 檢核之資料來源。**讀取服務 SRVDP001 已於 Foundation 就緒**，本 issue 補「維護 UI + 寫入端點」）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_PARAM_M` / `DP_PARAM_D` 表 + 平台級參數種子（`JWT` / `PWD_POLICY` / `LOGIN` / `MAIL` / `ACTION_TYPE`）、`SRVDP001` 唯讀查詢服務（`get_param_value` / `get_int_param` / `get_param_list`，**不快取**）、`SRVDP003` 稽核、`paginate()`、模組管理者判定閘 `module_admin_gate`（T017，`is_module_admin`）、`core/operator.py`（`get_operator`）
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：登入 + 後台 layout 骨架（`DpLayout` / `Sidebar` / `AppHeader`）；`dp-params` sidebar 連結已存在（現為 `StubPage`）
- Issue #5（GitHub [#61](https://github.com/sti-fhb/EDMS/issues/61)）已合併：前後端 CRUD 共用基礎設施已 bootstrap（`CrudPageLayout` / `AppTable` / `Pagination` / `FormCard` / `CrudActions` / `useCrudForm` / `usePagedQuery` / `useNotification` / `columnFactories` + `core/operator.py`）——**本 issue 直接沿用，不再 bootstrap**

### 任務說明

DP 後台系統參數與清單維護頁（`dp-params`，ET / DM 共用入口）：維護**平台級**（無前綴、共用）與**模組級**（`ET_` / `DM_` 前綴、按模組管理者身分過濾）之**參數**（VALUE 型單值）與**清單**（LIST 型，一個 `PARAM_ID` 下多筆 `PARAM_KEY`）。SRVDP001 唯讀查詢服務已於 Foundation 就緒且**不快取**，本 issue 只補「維護（寫入）」：參數值編輯（伺服器端型別 / 值域驗證）、清單項新增 / 改名 / 啟停（**不開放刪除**）、`DETAIL_LOCK` 鎖定碼擋碼值修改、模組過濾伺服器端 enforce、異動稽核（含前後值）。因 SRVDP001 不快取，**儲存即生效**。

> ℹ️ 全端 issue：後端維護端點（`params` router + 寫入 service / repository）+ 前端 `dp-params` 頁（填實現有 stub）。**SRVDP001 唯讀服務維持不動**（契約唯讀）；維護寫入與唯讀查詢分離。模組過濾依 T017 `module_admin_gate`；ET / DM checker 為 stub，見注意事項「admin 授權閘」。

### 範圍

**後端**（`app/dp/params/` — 已有 `models.py` / `repository.py` / `schemas.py` / `service.py`〔SRVDP001 唯讀〕，本 issue **新增 `router.py` + 寫入路徑**）：
- **T033 查詢端點**：`GET /api/dp/params`（列參數 / 清單主檔，依操作者模組身分**前綴過濾**——平台級共用 + 自己模組；明細隨主檔或 `GET /api/dp/params/{param_id}` 取清單項）；越權（直呼 `DM_` 前綴）伺服器端 403＝PARAMS-003
- **T033 參數值編輯**（VALUE 型）：`PUT` 更新 `PARAM_VALUE` → 伺服器端型別 / 值域 / 必填驗證（不合法 422/400＝PARAMS-001）→ 寫 `DP_PARAM_D` + 異動稽核（前後值）
- **T033 清單項維護**（LIST 型）：新增 / 改名 / 啟停 `PARAM_KEY`（`POST` / `PUT`）；主檔 `DETAIL_LOCK=true` 時擋碼值修改（僅可改 `PARAM_VALUE` 名稱 / `IS_ENABLED`，不可改 `PARAM_KEY`，409/403＝PARAMS-002）；**不開放刪除**（無 `DELETE` 端點，淘汰改 `IS_ENABLED=false`）
- **T033 模組過濾伺服器端 enforce**（T017）：模組級項互不可見 / 不可改、平台級共用；越權 403＝PARAMS-003
- 維護寫入 service / repository（與 SRVDP001 唯讀分離，唯讀契約不動）；所有異動經 `SRVDP003` 寫稽核（含 before / after）

**前端**（`frontend/src/dp/params/` — 現為 `StubPage`，沿用 #5 CRUD toolkit）：
- **T034 `dp-params` 頁**：`CrudPageLayout`；**平台（DP）/ ET / DM 三頁籤**（按操作者模組身分過濾顯示，對齊 wireframe）；VALUE 型參數值編輯；LIST 型 key / value / 排序 / 啟停編輯（`DETAIL_LOCK` 時碼值唯讀）
- **T034 平台級編輯警告**：進入平台級參數編輯先顯示「此為平台級參數，變更將影響全平台」（PARAMS-005）後才可儲存
- **T034** 儲存即生效提示（PARAMS-004）；錯誤訊息（PARAMS-001 / 002 / 003）；Zod 前端驗證（`sti-zod-conventions`）

**測試**：
- 後端 int：查詢（前綴過濾：ET 管理者見平台級 + `ET_`、不見 `DM_`）；參數值編輯（合法寫入 + 稽核；不合法 PARAMS-001）；清單項新增 / 改名 / 啟停；`DETAIL_LOCK` 擋碼值（PARAMS-002）；**無刪除端點**；越權直呼 `DM_` → 403（PARAMS-003）；儲存後 SRVDP001 即時讀到新值（不快取）
- 前端：平台 / ET / DM 三頁籤過濾（MSW）；VALUE 編輯；LIST key / value / 啟停；平台級警告（PARAMS-005）；`DETAIL_LOCK` 碼值唯讀

### 驗收條件

- [ ] 查詢：ET 管理者見平台級（無前綴）+ `ET_` 前綴項、**不見** `DM_`；DM 管理者反之；兼具兩模組管理者身分者兩者皆見（FR-02、AC1）
- [ ] VALUE 型參數編輯：伺服器端驗證合法（型別 / 值域 / 必填）→ 寫 `DP_PARAM_D` + 稽核（前後值）+ 即時生效；不合法 → 阻擋並提示 PARAMS-001（FR-03/06、AC2/6）
- [ ] LIST 型清單項：支援新增 / 改名 / 啟用 / 停用 → 儲存 + 稽核；**不開放刪除**（無 `DELETE` 端點，淘汰改停用）（FR-04、AC4）
- [ ] `DETAIL_LOCK` 標記之鎖定碼：碼值（`PARAM_KEY`）建立後不可改，僅可改名稱（`PARAM_VALUE`）或停用；嘗試改碼值 → 阻擋並提示 PARAMS-002（FR-04、AC5）
- [ ] 平台級參數編輯：進入編輯先顯示影響全平台警告 PARAMS-005 後才可儲存（FR-07、AC3）
- [ ] 模組過濾伺服器端 enforce：ET 管理者以**直呼 API** 存取 `DM_` 前綴項 → 403 PARAMS-003（非僅前端過濾）（FR-02、AC7）
- [ ] 所有參數 / 清單異動寫 `DP_AUDIT_LOG`（含前後值）；儲存後 SRVDP001 唯讀查詢**即時反映**（無快取延遲）、模組業務下拉即時更新（僅列啟用中項）（FR-06、AC8、SC-008）
- [ ] 成功儲存提示 PARAMS-004
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`DP_PARAM_M` / `DP_PARAM_D` 表 + 平台級參數種子、`SRVDP001`（`get_param_value` / `get_int_param` / `get_param_list`）、`SRVDP003`、`paginate()`、`module_admin_gate`（T017）、`core/operator.py`
- **Issue #2（GitHub #31）**：登入 + 後台 layout；`dp-params` sidebar 連結
- **Issue #5（GitHub #61）**：前後端 CRUD toolkit（`CrudPageLayout` / `AppTable` / `Pagination` / `FormCard` / `CrudActions` / `useCrudForm` / `usePagedQuery` / `useNotification` / `columnFactories`）+ `core/operator.py`——**直接沿用**
- **跨模組（stub 先行）**：`is_module_admin`（ET / DM checker stub，T017）——完整模組過濾驗收待模組 service 就緒於 T049 回歸

### 注意事項

- ⚠️ **admin 授權閘 + 模組過濾（開發前須釐清，列為 SA Q）**：US5 核心即「按模組管理者身分過濾參數」，依賴 T017 `is_module_admin`。但 ET / DM checker 為 **stub（fail-closed False）** → 若直接以 `is_module_admin` 決定可見前綴，現況只有平台級（無前綴）可見、模組級（`ET_` / `DM_`）無人可見 / 可改，頁面模組級部分無法驗收。且 [sti-backend-modules 暫行授權規則](../../../.claude/rules/sti-backend-modules.md)明訂「全域授權機制未實作前，CUD 僅注入 `get_operator`、**不加** `require_admin`」。→ **與 #5 同一議題**，待 `/sti-plan` 釐清一致策略：(a) 平台級先可維護、模組級過濾待模組 service（T049 回歸）；(b) 掛 `require_module_admin` + 測試注入 stub 驗證前綴過濾行為。此為 US5 最重要開工前決策（**模組過濾即本 US 主軸**）。
- **SRVDP001 唯讀契約不動**：維護（寫入）為 DP 後台自身功能，**不經 `app/services/__init__.py` 出口暴露**；寫入 service / repository 與 SRVDP001 唯讀（跨模組）分離，避免污染唯讀契約。「儲存即生效」正因 SRVDP001 不快取（research §7）、每次讀 DB——本 issue **MUST NOT** 為 SRVDP001 引入快取。
- **不開放刪除**（FR-04）：清單項淘汰改 `IS_ENABLED=false`；**MUST NOT** 提供 `DELETE` 端點（`DP_PARAM_D` 雖繼承 `BaseModel` 之軟刪除，但 UI / API 不暴露刪除操作，一律以停用表達淘汰）。
- **`DETAIL_LOCK`**（research §7）：主檔 `DETAIL_LOCK=true` 時，明細 `PARAM_KEY`（碼值）建立後不可改，僅可改 `PARAM_VALUE`（名稱）或 `IS_ENABLED`（停用）；如 `DM_DOC_CATEGORY` 分類碼（碼值嵌入 `DOC_ID`，改碼會斷既有引用）。VALUE 型：純單值參數 `PARAM_KEY='VALUE'`；多鍵參數組（`JWT` / `PWD_POLICY` / `LOGIN` / `MAIL`）一個 `PARAM_ID` 下多筆**具名** `PARAM_KEY`（PARAM_TYPE=VALUE 慣例延伸，data-model §種子）——兩者編輯皆只改 `PARAM_VALUE`、不改 `PARAM_KEY`。
- **值合法性驗證**（FR-03）：型別 / 值域規則見 [spec_us5.md §參數型別 / 值域驗證規則](spec_us5.md)（平台級參數逐項對照表 + 跨欄位一致性 `ADMIN_MIN_LEN ≥ MIN_LEN` / `EXPIRY_REMIND_DAYS < EXPIRY_DAYS`）；因主檔為種子固定集、UI 不新增主檔，規則以**程式碼側 registry 按 `PARAM_ID` + `PARAM_KEY` 維護**（非存 `DP_PARAM_M` 欄位）。伺服器端 Pydantic + service 檢核，**不在 route handler 手動驗證**；前端 Zod 對齊（`sti-zod-conventions`），最終以伺服器端為準。
- **分頁策略**：參數 / 清單為管理類小表（< 200 筆），依 [CLAUDE.md](../../../CLAUDE.md) 可用 `usePagination` client-side 分頁；若日後量大改後端 `paginate()`。
- **Error codes**（實作 / `/sti-plan` 時對齊 `sti-error-codes`）：新增 `DP_PARAM_*` 碼——值不合法（422/400）、`DETAIL_LOCK` 鎖定碼值（409/403）、模組越權（403）；PARAMS-004 / 005 為成功 / 警告提示、非 error。
- **前綴歸屬判定**：無前綴＝平台級（共用）、`ET_` / `DM_`＝模組級；過濾以 `PARAM_ID` 前綴 + 操作者模組管理者身分（research §4）於伺服器端 enforce（data-model §模組過濾）。
- **稽核與敏感值**：異動經 `SRVDP003.log_action`（`target_id` 必填、含 before / after value、來源 IP）；`PARAM_VALUE` 可能含機密（如通關密碼雜湊），**禁寫入應用 log**（`sti-backend-logging` 明列 `DP_PARAM_D.PARAM_VALUE`）；稽核前後值若涉機密性參數之遮罩策略，於 `/sti-plan` 或 Security Review 把關。
- 目錄 `app/dp/params`（SRVDP001 已在此）+ `frontend/src/dp/params`（現 stub）；角色 / 標籤指派 MUST NOT 於本頁（屬 US7）。

### 相關文件

- [spec_us5.md](spec_us5.md)、[spec.md](spec.md) §模組過濾與共用項 / §定義 vs 關聯分層、[research.md](research.md) §7、[data-model.md](data-model.md)（`DP_PARAM_M` / `DP_PARAM_D`）、[tasks.md](tasks.md) Phase 8（T033~T034）
- [contracts/platform-services.md](contracts/platform-services.md)（SRVDP001）
- 需求：[RQDP.md](../../requirements/RQDP.md) §系統參數與清單定義；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP006

**Labels**：`P1-核心`, `DP-平台`, `US5`

---

## Issue #7：[P1-核心] DP — 權限管理（dp-roles）（GitHub [#140](https://github.com/sti-fhb/EDMS/issues/140)）

**對應規格**：[spec_us7.md](spec_us7.md)（US7 / UCDP010，FR-DP-US7-01~07、DP-MSG-DP06-001~003）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §1（`is_module_admin`）/ §3（`get_users_roles_tags` / `assign_roles_tags`；`get_users_roles_audiences` / `assign_roles_audiences`）；[research.md](research.md) §4（角色即時由模組判定，JWT 不含角色）；[spec.md](spec.md) §定義 vs 關聯分層 / §跨模組共用規則（角色分治）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-roles`）
**階段**：P1-核心（ET 學員以外**所有**角色〔ET 教師 / 管理者、DM 四角色〕之唯一開通路徑；「畫面在 DP、資料與判定在模組」2026-07-08 決策）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：模組管理者判定閘 `module_admin_gate`（T017）、`SRVDP001`（讀 `DP_PARAM` 標籤清單）、`SRVDP003` 稽核、認證 / `get_operator`
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：登入 + 後台 layout；`dp-roles` sidebar 連結（現為 `StubPage`）
- Issue #6（GitHub [#68](https://github.com/sti-fhb/EDMS/issues/68)）已合併：`DP_PARAM` 標籤 / 可見對象清單之維護與唯讀查詢（US7 讀啟用中項）；前後端 CRUD toolkit
- **跨模組指派轉接層 registry**（`core/module_assign.py` `module_assign_registry`，DM US1 [#133](https://github.com/sti-fhb/EDMS/issues/133) 建）+ `is_module_admin` 閘（`module_admin_gate`，T017）：US7 泛用消費 registry，**已註冊模組→整合、未註冊→fail-closed**（不硬編哪個模組 real）。當下狀態：**DM 已就緒**（US1 已註冊 `DmAssignProvider`，可 end-to-end 驗）；**ET 未就緒**（ET 模組未開發，fail-closed / UI 不顯示 ET 區，待 ET 落地自動接上、US7 不需改）

### 任務說明

DP 後台權限管理頁（`dp-roles`，ET / DM 共用入口）：查使用者 → 於**同一列**指派本模組**角色**（固定 enum 核取）+ **標籤 / 可見對象**（多選，清單讀 `DP_PARAM` 啟用中項）。DP 為**轉接層**：載入現況呼叫模組 `get_user_roles_*`、儲存呼叫模組 `assign_roles_*`，資料寫**模組表**（`ET_USER_ROLE` / `DM_USER_ROLE` / `ET_USER_TAG` / DM 授權表）。DP **MUST NOT 自持指派資料、不做全域 RBAC、不定義角色能力**（判定與 enforce 在模組）。自我保護（取消自己管理者）與「不檢核至少 1 名管理者」由**模組 service** 判定、DP 呈現模組回傳訊息。模組過濾伺服器端 enforce（越權 403）。

> ℹ️ 全端 issue：後端轉接端點（`roles` router → `module_assign_registry` provider）+ 前端 `dp-roles` 頁。**核心邏輯（角色 enum、自我保護、標籤值檢核、寫模組表 + 稽核）在模組**；DP 僅呼叫 + 呈現 + 模組過濾。**驗收範圍依當下已註冊模組**：DM 已就緒→可實測 end-to-end；ET 未就緒→該區 fail-closed 隱藏（待 ET 落地回歸，US7 程式碼不需改）。

### 範圍

**後端**（`app/dp/roles/` — 轉接層，不建角色 / 指派表）：
- **T035 權限管理轉接端點**（經 `module_assign_registry.get(module)` 取 provider，泛用呼叫）：
  - 查使用者 + 現況：`GET` → `provider.get_users_assignments(user_ids)` 批次回 `AssignmentView`（`roles` + `groups`〔DM groups＝可見對象 TAG_ID、ET groups＝受訓單位標籤〕+ `last_modified_*`）
  - 儲存：`PUT` → `provider.assign(user_id, roles, groups, operator_id)`；模組 `AppError` 透傳為 ROLES-001〔自我保護〕
  - 可選清單：DM 經 `provider.list_audiences()`（DM_TAG AUDIENCE）；ET 經 `DP_PARAM`（`ET_` 前綴、`SRVDP001`）——來源依模組不同
  - 模組過濾 enforce（T017 `is_module_admin`）：越權 403＝ROLES-003
  - 指派異動之稽核**由模組 provider 側**於同交易呼叫 `SRVDP003` 寫入（FR-07，DM US1 已落地）——DP 不重複寫
  - registry（`core/module_assign.py`，US1 已建）：ET / DM 於啟動註冊 provider，未註冊 `get()` 回 None → fail-closed（該模組區不顯示）

**前端**（`frontend/src/dp/roles/` — 沿用 #5 / #6 CRUD toolkit）：
- **T036 `dp-roles` 頁**：查使用者清單 → 每列「**角色核取 + 標籤 / 可見對象多選**」雙維度；按模組分區（平台 / ET / DM，兼具者雙區）；固定 enum、**無「新增角色」入口**；即時生效提示（ROLES-002）

**測試**：
- 後端 int：查現況（stub 回假資料）；儲存呼叫模組 `assign`（驗 stub 被呼叫、參數正確）；模組 `AppError` 透傳 ROLES-001（自我保護）；越權直呼他模組 → 403 ROLES-003；標籤清單讀 `DP_PARAM` 啟用中項
- 前端：雙維度指派（MSW）、模組分區、即時生效提示、無新增角色入口

### 驗收條件

- [ ] ET 管理者查使用者 → 每列顯示 ET 角色（管理者 / 教師 / 學員）核取 + 受訓單位標籤多選；**不顯示** DM 區（FR-01、AC1）
- [ ] DM 管理者 → 顯示 DM 角色（管理者 / 編輯者 / 審核者 / 閱覽者）+ 可見對象 / 單位授權多選；不顯示 ET 區；兼具者兩區皆見（FR-01、AC2）
- [ ] 同一列勾選 / 取消角色 + 標籤（兩維度獨立）→ 儲存經模組 service 寫模組表 → 即時生效 ROLES-002（FR-02/03、AC3）
- [ ] 多角色允許（權限取聯集）；角色固定 enum、無新增角色入口（FR-04、AC4）
- [ ] 取消自己之管理者角色 → 模組 service 阻擋、DP 呈現 ROLES-001（自我保護，**判定在模組**）（FR-06、AC5）
- [ ] **不檢核**「至少 1 名管理者」（取消他人管理者允許）（AC6）
- [ ] 標籤 / 可見對象可選清單讀 `DP_PARAM` 啟用中項（US5）（FR-05）
- [ ] 越權（直呼他模組角色指派）→ 403 ROLES-003（伺服器端 enforce，非僅前端）（FR-01、AC8）
- [ ] 指派異動寫 `DP_AUDIT_LOG`（含前後值）——由**模組側**於同交易寫（FR-07、AC7）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`module_admin_gate`（T017）、`SRVDP001`、`SRVDP003`、認證 / `get_operator`
- **Issue #2（GitHub #31）**：登入 + 後台 layout；`dp-roles` sidebar 連結
- **Issue #6（GitHub #68）**：`DP_PARAM` 標籤 / 可見對象清單（US7 讀啟用中項）；前後端 CRUD toolkit
- **跨模組指派 registry**（`core/module_assign.py`，DM US1 [#133](https://github.com/sti-fhb/EDMS/issues/133) 已建並註冊 DM provider）+ `is_module_admin`（module-callbacks §1 / §3）。當下：**DM real、ET fail-closed（未開發）**；ET 落地後自動接上、US7 不需改

### 注意事項

- ⚠️ **泛用 + fail-closed（不硬編哪個模組 real）**：US7 的核心（角色 enum、自我保護、標籤值檢核、寫模組表 + 稽核）**全在各模組 provider**；US7 泛用消費 `module_assign_registry`，**已註冊模組整合、未註冊 fail-closed（該區不顯示）**。**驗收範圍依當下已註冊模組**：**DM 已就緒（US1 [#133](https://github.com/sti-fhb/EDMS/issues/133) merged）→ 可實測 DM 角色/可見對象指派 end-to-end（含自我保護 DM_ROLE_001、SRVDP003 稽核）**；**ET 未開發 → ET 區 fail-closed 隱藏**，待 ET 落地註冊 provider 後自動接上（US7 程式碼與 body 皆不需再改）。原「全程 stub、待 T049」前提已隨 DM US1 交付而部分解除。
- ⚠️ **admin 授權閘 + 模組過濾（同 #5 / #6 SA Q，開發前釐清）**：模組過濾依 T017 `is_module_admin`（fail-closed stub）；沿用 US4 / US5 裁示（暫行僅 `get_jwt_payload` 認證、admin 閘待 T049）或掛 `require_module_admin` + stub 驗；待 `/sti-plan` 對齊一致策略。
- **DP 為轉接、非權威**：DP MUST NOT 自持指派資料 / 全域 RBAC / 角色能力定義；僅呼叫模組 service + 呈現模組錯誤。自我保護、至少-1-管理者、標籤值合法性**判定皆在模組**（contracts §3），DP 不重複實作。
- **稽核由模組側寫**（FR-07、contracts §3）：指派異動之 `DP_AUDIT_LOG` 由**模組**於同交易呼叫 `SRVDP003`（事件歸屬各自 MODULE），DP 端不重複寫；stub 期以 stub 內呼叫驗證或標記待回歸。
- **標籤 / 可見對象值來源**：讀 `DP_PARAM` 啟用中項（`SRVDP001`）；本頁只做「誰配誰」指派，清單定義維護在 US5（dp-params）。⚠️ 選項清單（`ET_` / `DM_` 前綴，如 `ET_TRAINING_UNIT` / `DM_AUDIENCE`）**由 ET / DM 模組 migration seed 或管理者於 US5 手動建**——**DP-only 開發期這些 row 不存在、標籤下拉會是空的**；stub 期可先於 `DP_PARAM` 手動建幾筆 `ET_` / `DM_` 假清單驗證下拉綁定。
- **模組讀取為批次 + View 形狀**：`get_users_roles_*(user_ids)` 一次回一頁使用者現況（避免 N+1）；`EtRoleTagView` / `DmRoleAudienceView` 帶 `roles` / `tags`（或 `audiences`）之 PARAM_KEY 集合 + `last_modified_by/date`；標籤中文名由 DP 讀 `DP_PARAM` 對應（見 [contracts/module-callbacks.md](contracts/module-callbacks.md) §3）。
- **角色 enum**：ET＝ADMIN / TEACHER / STUDENT；DM＝ADMIN / EDITOR / REVIEWER / VIEWER（固定，畫面無新增角色）。
- **Error codes**（實作 / `/sti-plan` 對齊 `sti-error-codes`）：新增 `DP_ROLE_*`（越權 403）；自我保護 ROLES-001 為**模組 raise 之 `AppError` 透傳**（DP 呈現）；ROLES-002 成功、非 error。
- **ET 學員預設角色非本頁**：於帳號建立當下授予（US2 / US4 `module_provisioning`）；本頁開通「學員以外」所有角色。
- 目錄 `app/dp/roles`（轉接）；資料在模組表，DP 不建角色 / 指派表（定義 vs 關聯分層）。

### 相關文件

- [spec_us7.md](spec_us7.md)、[spec.md](spec.md) §定義 vs 關聯分層 / §跨模組共用規則（角色分治）、[tasks.md](tasks.md) Phase 9（T035~T036）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §1（`is_module_admin`）§3（get / assign roles）
- 需求：[RQDP.md](../../requirements/RQDP.md) §權限管理；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP010
- 模組端：ET / DM 之角色管理規格（跨模組）

**Labels**：`P1-核心`, `DP-平台`, `US7`

---

## Issue #8：[P2-延伸] DP — 個人資料維護 + 強制變更密碼（dp-profile）（GitHub [#83](https://github.com/sti-fhb/EDMS/issues/83)）

**對應規格**：[spec_us8.md](spec_us8.md)（US8 / UCDP004，FR-DP-US8-01~08、DP-MSG-DP04-001~008）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002 發信）；[research.md](research.md) §5（一次性 token）/ §11（密碼策略）；[data-model.md](data-model.md)（`DP_USER`.PENDING_EMAIL / `DP_PWD_RESET`〔EMAIL_CHANGE〕/ `DP_PWD_HIST`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-profile`）
**階段**：P2-延伸（使用者自助作業；登入 / 註冊 P1 先行、個資維護隨後。ET / DM 不自設個資畫面、皆導向本頁）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：密碼策略工具（T016，複雜度〔特權 12〕/ 重複性 / bcrypt / 歷程）、速率限制（T015）、模組管理者判定閘（T017，特權門檻判定）、`DP_PWD_RESET`（`TOKEN_TYPE=EMAIL_CHANGE` + `NEW_EMAIL`）/ `DP_PWD_HIST` / `DP_USER.PENDING_EMAIL` 表、`SRVDP001`（`EMAIL_CHANGE_TTL_MIN` / `PWD_POLICY` 參數）、`SRVDP003` 稽核
- Issue #1（GitHub [#27](https://github.com/sti-fhb/EDMS/issues/27)）已合併：`SRVDP002` 發信 + `EMAIL_CHANGE_VERIFY` 系統信範本（`MODULE=DP`，變數 `user_name / verify_link / expiry_minutes`）——**非 stub、可直接呼叫**
- Issue #2（GitHub [#31](https://github.com/sti-fhb/EDMS/issues/31)）已合併：US1 已建**強制變更密碼閘**（`password_gate`，T023，逾效期 / `MUST_CHANGE_PWD` → 403 `DP_AUTH_009` 導向）+ 前端 **`ForceChangePasswordShell` 頁殼**——本 issue 填實其**提交端點與檢核**

### 任務說明

DP 個人資料頁（`dp-profile`，所有登入者維護**自己的**姓名 / Email / 密碼）：姓名直接存（ET / DM 同步、共用 `DP_USER`）；Email 採「**新信箱驗證後切換**」延遲生效（新 Email 唯一檢核 → 產 `EMAIL_CHANGE` token → 經 SRVDP002 寄驗證信至**新信箱** → 點連結切換、舊失效、逾時作廢；驗證前舊 Email 仍可登入）；密碼變更驗舊 + 複雜度（特權 12）+ 重複性 + 追加 `DP_PWD_HIST` + 清 `MUST_CHANGE_PWD`，掛速率限制。本頁亦承載 **US1 的強制變更密碼情境**（US1 已建閘 + 頁殼，本 issue 提供實際提交 + 檢核，完成前不得離開）。

> ℹ️ 全端 issue：後端 `dp/user/me` 姓名 / 密碼端點 + Email 變更申請 / 驗證端點 + 前端 `dp-profile` 頁 + 強制變更密碼頁（填實 US1 之 `ForceChangePasswordShell`）。發信經 SRVDP002（US6 已交付、非 stub）；Email 變更 token 重用 `DP_PWD_RESET`（`TOKEN_TYPE=EMAIL_CHANGE`）。

### 範圍

**後端**（`app/dp/user/` — 認證 / 個人資料之 /me 端點；與 `dp/users` 管理 CRUD 分開）：
- **T037 姓名變更**：`PUT /api/dp/user/me`（姓名直接存 `DP_USER` + 稽核〔前後值〕；ET / DM 同步生效）
- **T037 密碼變更**：`PUT /api/dp/user/me/password`（驗舊密碼〔bcrypt，錯→PROFILE-001〕 + 兩次一致〔PROFILE-002〕 + 複雜度〔特權 12 依 T017 `is_module_admin` 判定，PROFILE-003〕 + 重複性〔`is_reused` 查 `HISTORY_COUNT`，PROFILE-004〕 → 更新雜湊 + 追加 `DP_PWD_HIST` + 更新 `PWD_CHANGED_DATE` + 清 `MUST_CHANGE_PWD` + 稽核；掛速率限制 T015）
- **T037 公開密碼政策端點**（併 #77 核心，US8 為首個消費者）：`GET /api/password-policy`（**免 JWT**，供變更密碼 / 註冊 / 重設頁動態渲染提示）→ 回 `min_len` / `admin_min_len` / `char_types` / `history_count` / `expiry_days`（值來源 `SRVDP001`、即時不快取）；僅回渲染提示所需之**非機密**數值
- **T038 Email 變更申請**：`PUT /api/dp/user/me/email`（新 Email 唯一檢核〔PROFILE-006〕 → 產一次性 `EMAIL_CHANGE` token〔SHA-256 入 `DP_PWD_RESET`、`NEW_EMAIL`、`DP_USER.PENDING_EMAIL`、TTL `EMAIL_CHANGE_TTL_MIN`〕 → 經 SRVDP002 寄 `EMAIL_CHANGE_VERIFY` 至**新信箱** → 提示 PROFILE-005；舊 Email 仍可登入）
- **T038 Email 變更驗證**：`POST /api/verify-email-change`（信中連結落點）：驗 token〔逾時 / 已用 → PROFILE-008〕 → 切換 `DP_USER.EMAIL`＝`NEW_EMAIL`、清 `PENDING_EMAIL`、作廢 token、稽核〔前後值〕
- **T037 / T038 強制變更閘收尾**：US1 之 `password_gate`（T023）於逾效期 / `MUST_CHANGE_PWD` 擋下並導向；本頁密碼變更端點清 `MUST_CHANGE_PWD` 後放行

**前端**（`frontend/src/dp/user/`〔或 `dp/profile`〕，沿用共用元件）：
- **T039 `dp-profile` 頁**：三區（姓名編輯 / Email 變更〔送出後 PROFILE-005〕 / 密碼變更〔舊 + 新 + 確認，Zod：特權 12 對齊、兩次一致〕）；訊息 PROFILE-001~008
- **T039 密碼提示動態化**（併 #77 核心）：`usePasswordPolicy` hook 讀 `GET /api/password-policy` + 提示組字工具；變更密碼頁之複雜度提示（`8` / `12` 字元、字元組合種類數等數字）**依參數即時渲染、非寫死**——管理者於 US5 改 `ADMIN_MIN_LEN` 提示跟著變（stub 期特權門檻顯示一般 8，見注意事項）
- **T039 強制變更密碼頁**：US1 T023 導入點（填實 `ForceChangePasswordShell`）——未完成變更不得離開至其他功能（DP-MSG-DP01-005 / PROFILE-007）
- **T039 Email 變更驗證落點頁**：信中連結落點 `/verify-email-change?token=`（沿用 US3 `reset-password` / US2 `verify-email` 之免登入落點頁殼模式，置於 `RootLayout` 外）——驗證成功切換提示、逾時 / 失效顯 PROFILE-008

**測試**：
- 後端 int：姓名改（直接存 + 稽核）；密碼改（驗舊 / 兩次 / 複雜度〔特權 12〕/ 重複性 / 清 `MUST_CHANGE_PWD` / `DP_PWD_HIST` / 稽核 / 速率 429）；Email 變更（唯一檢核 / token + 寄新信箱 / 舊仍可登入 / 驗證切換 / 逾時作廢 / 稽核）
- 前端：個資頁三區（MSW）、強制變更頁流程、各錯誤訊息

### 驗收條件

- [ ] 姓名變更 → 直接更新 `DP_USER`（ET / DM 同步）+ 稽核（FR-02、AC1）
- [ ] Email 變更 → 寄驗證信至**新 Email**（TTL 預設 30 分，經 SRVDP002 `EMAIL_CHANGE_VERIFY`）、提示 PROFILE-005；**驗證前舊 Email 仍可登入**（延遲生效）（FR-03、AC2）
- [ ] 點驗證連結未逾時 → 新 Email 生效、舊失效、清 `PENDING_EMAIL`、稽核；逾時 → 變更作廢、舊 Email 維持（PROFILE-008）（FR-03、AC3）
- [ ] 新 Email 已被他人使用 → 阻擋 PROFILE-006（FR-03、AC4）
- [ ] 密碼變更：驗舊 + 兩次一致 + 複雜度 + 重複性 → 更新雜湊 + `DP_PWD_HIST` + 稽核 + 清 `MUST_CHANGE_PWD` + PROFILE-007（FR-04/06、AC5）
- [ ] 舊密碼錯 / 兩次不一致 / 不符複雜度 / 近期重複 → 對應 PROFILE-001~004（皆伺服器端）（FR-04、AC6）
- [ ] 特權帳號（ET / DM 管理者）變更密碼 → 12 字元門檻（一般 8）（FR-05、AC7）
- [ ] 密碼變更端點以「IP + 帳號」速率限制超限回 429（FR-07、AC8）
- [ ] 姓名 / Email / 密碼異動皆寫 `DP_AUDIT_LOG`（含前後值；密碼不入前後值）（FR-06）
- [ ] 強制變更密碼情境：逾效期 / 初始密碼首登 → 導本頁、未完成不得離開（FR-08、spec_us1 T023）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：密碼策略（T016）、速率限制（T015）、`module_admin_gate`（T017）、`DP_PWD_RESET`〔EMAIL_CHANGE〕/ `DP_PWD_HIST` / `DP_USER.PENDING_EMAIL`、`SRVDP001`（TTL / 策略參數）、`SRVDP003`
- **Issue #1（GitHub #27）**：`SRVDP002` 發信 + `EMAIL_CHANGE_VERIFY` 範本（**非 stub、直接呼叫**）
- **Issue #2（GitHub #31）**：US1 之 `password_gate`（T023）+ `ForceChangePasswordShell` 頁殼（本 issue 填實提交）
- **跨模組（stub 先行）**：`is_module_admin`（特權 12 字元判定，T017 fail-closed）——過渡期一律以一般 8 字元判定，特權門檻完整驗收待模組 service 就緒於 T049 回歸

### 注意事項

- **Email 變更重用既有 token 基礎**：`DP_PWD_RESET`（`TOKEN_TYPE=EMAIL_CHANGE` + `NEW_EMAIL`）+ `DP_USER.PENDING_EMAIL`（#16 已建）；`verify_link` 組法同 US3（`{FRONTEND_BASE_URL}/verify-email-change?token=<明文>`，`FRONTEND_BASE_URL` 為後端設定）；token 明文入信、SHA-256 入庫、一次性 + 時效。
- **強制變更頁 US1 已備殼**：US1（#31）已建 `password_gate`（T023 → 403 `DP_AUTH_009`）+ 前端 `ForceChangePasswordShell`；US1 當時「以最小提交 / stub 先行」，**本 issue 填實提交端點 + 檢核 + 清 `MUST_CHANGE_PWD` / 更新 `PWD_CHANGED_DATE`**（spec_us1 已註明實際變更提交屬 US8）。強制變更**沿用同一 `PUT /api/dp/user/me/password` 端點、仍需舊密碼**——使用者剛以現行密碼登入（逾效期之密碼仍有效可作舊密碼、初始密碼由管理者代設使用者已知），非另設免驗舊之特殊端點。
- **特權 12 字元於變更當下判定**（research §11）：依 `is_module_admin`（T017）判定；stub fail-closed → 過渡期一律套一般 8 字元，特權門檻待模組 service（T049 回歸）。
- **併入 #77 核心（密碼規則提示動態化）**：本 issue 建「公開 `GET /api/password-policy` 端點 + `usePasswordPolicy` hook + 提示組字」，US8 變更密碼頁為**首個消費者**、提示數字**動態讀 `PWD_POLICY`**（非寫死）；[#77](https://github.com/sti-fhb/EDMS/issues/77) 隨後收斂為「retrofit 註冊（US2）/ 重設（US3）頁改用同一 hook」。⚠️ 提示**數字**動態（讀參數即時反映），但「顯示一般 8 或特權 12」之**選擇**仍依 `is_module_admin`（stub 期一律顯示一般 8）、特權門檻正確顯示待 T049。端點僅回非機密數值（勿回整包 `DP_PARAM`）。
- **密碼 / token 不入 log / 稽核前後值**（sti-backend-logging）；姓名 / Email 前後值可入稽核。
- **Email 延遲生效**（FR-03）：驗證前 `DP_USER.EMAIL` 不變（舊仍可登入）、`PENDING_EMAIL` 存新值；驗證成功才切換。逾時 / 重新申請作廢舊 token。
- **Error codes**（實作 / `/sti-plan` 對齊 `sti-error-codes`）：驗舊失敗（`DP_AUTH_008` 密碼錯誤或新 `DP_PWD_*`）；複雜度 / 長度 / 重複重用 `DP_PWD_001/002/003`；Email 重複重用 `DP_USER_007`；token 逾時 / 已用重用 `DP_PWD_005`；PROFILE-005/007 為提示 / 成功、非 error。
- **速率限制**掛密碼變更端點（T015，IP + 帳號）；比照 US1 / US3。
- 目錄 `app/dp/user`（/me，認證 / 個資），非 `dp/users`（管理 CRUD）；前端 `dp/user` 或 `dp/profile`。

### 相關文件

- [spec_us8.md](spec_us8.md)、[spec.md](spec.md) §密碼策略與帳號安全、[research.md](research.md) §5 / §11、[data-model.md](data-model.md)（`DP_USER` / `DP_PWD_RESET` / `DP_PWD_HIST`）、[tasks.md](tasks.md) Phase 10（T037~T039）
- [contracts/platform-services.md](contracts/platform-services.md)（SRVDP002）
- 需求：[RQDP.md](../../requirements/RQDP.md) §密碼與帳號安全；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP004

**Labels**：`P2-延伸`, `DP-平台`, `US8`

---

## Issue #9：[P2-延伸] DP — 通知範本維護（dp-templates）（GitHub [#92](https://github.com/sti-fhb/EDMS/issues/92)）

**對應規格**：[spec_us9.md](spec_us9.md)（US9 / UCDP011，FR-DP-US9-01~07、DP-MSG-DP08-001~004）；[data-model.md](data-model.md)（`DP_NOTIFY_TEMPLATE`：`MODULE`+`TEMPLATE_CODE` 複合 PK、`IS_SYSTEM`、`VERSION` 樂觀鎖、DP 系統信 5 支種子）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002 以範本渲染）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-templates`）
**階段**：P2-延伸（範本已有內建種子即可運作；編輯功能於發信服務 P1〔US6〕之後交付）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_NOTIFY_TEMPLATE` 表 + **5 支 DP 系統信種子**（`PWD_RESET` / `ACCOUNT_VERIFY` / `ACCOUNT_INVITE` / `EMAIL_CHANGE_VERIFY` / `PWD_EXPIRY_REMIND`，`MODULE=DP`、`IS_SYSTEM=true`）+ `VERSION` 樂觀鎖欄位（ORM `version_id_col` 待本 issue 接）+ 模組管理者判定閘（T017 `module_admin_gate`）
- Issue #1（GitHub [#27](https://github.com/sti-fhb/EDMS/issues/27)，US6）已合併：`SRVDP002` 以 `get_template` 渲染——本 issue 儲存後，US6 發信即以最新啟用中範本渲染（無需額外接線）

### 任務說明

DP 後台通知範本維護頁（`dp-templates`）：ET / DM 管理者編輯本模組通知範本之**主旨 / 內文 / 管道 / 啟停**，通知內容集中維護。按 `MODULE` 過濾（ET 管理者見 / 編 `ET`＋`DP`、DM 管理者見 / 編 `DM`＋`DP`，A-strict、伺服器端 enforce）；**`MODULE=DP` 系統信（`IS_SYSTEM`）主旨 / 內文可編、但不可停用 / 刪除**（帳號安全信）；儲存採 **`VERSION` 樂觀鎖**防並行覆寫；事件（`TEMPLATE_CODE`）固定，**無新增 / 刪除範本**（內容不同的通知＝同表不同列，由種子建立）。填實既有 `TemplatesPage` stub。

> ℹ️ 全端 issue：後端 `dp/notify` 範本查詢 / 編輯端點 + 前端填實 `TemplatesPage`。**無新表 / migration**（表 + 種子於 #0 已建）；管道「站內」欄位**僅作為該事件是否寄 Email 之開關**，站內訊息之儲存 / 呈現由各模組自理（DP 不設站內訊息表）。與 US5（dp-params）高度相似（既有種子表的 MODULE 過濾維護 + A-strict + 稽核），差異為 US9 多**樂觀鎖**與**系統信保護**。

### 範圍

**後端**（`app/dp/notify/` — 範本維護；與 US6 發信服務同模組）：
- **T040 範本清單**：`GET /api/dp/notify/templates`（依操作者模組管理者身分過濾 `MODULE`：ET→`ET`+`DP`、DM→`DM`+`DP`；A-strict、`module_admin_gate` 判定；回主旨 / 內文 / 管道 / 啟停 / `IS_SYSTEM` / `VERSION` / 變數說明）
- **T040 範本編輯**：`PUT /api/dp/notify/templates/{module}/{template_code}`（主旨 / 內文 / 管道〔Email / 站內 / 兩者〕/ 啟停）——
  - `IS_SYSTEM=true` 之範本：擋停用 / 刪除（TEMPLATES-001），主旨 / 內文仍可編（兩管理者皆可，`MODULE=DP` 共用）
  - **`VERSION` 樂觀鎖**：req 帶當前 `version`，不符回衝突 409（TEMPLATES-002）；成功 `VERSION+1`
  - 越權（改非本模組範本）→ 403（TEMPLATES-004，`module_admin_gate` enforce）
  - **無新增 / 刪除範本端點**（事件固定）；異動寫 `DP_AUDIT_LOG`（前後值）
- 樂觀鎖落地：接 ORM `version_id_col`（#0 已建 `VERSION` 欄、註明待接）或服務層 `WHERE VERSION=:v` 條件式 UPDATE + RETURNING（比對 0 列＝衝突）

**前端**（`frontend/src/dp/notify/`，填實 `TemplatesPage` stub）：
- **T041 清單**：依 `MODULE` 分組（DP 系統信 / 本模組事件）；欄位 MODULE / 範本代碼 / 主旨 / 管道 / 啟用狀態 / 動作
- **T041 編輯**：主旨 / 內文 / 管道（Email / 站內 / 兩者）/ 啟停；**變數說明顯示**（`VARIABLES`，如 `user_name` / `verify_link`）；系統信隱藏 / 禁用「停用」動作
- 樂觀鎖衝突 → 提示重新載入（TEMPLATES-002）；儲存成功（TEMPLATES-003）；管道欄註記「站內訊息由模組自理」

**測試**：
- 後端 int：MODULE 過濾（ET 看不到 DM）/ 越權 403；`IS_SYSTEM` 擋停用；樂觀鎖衝突 409；編輯主旨內文 + 稽核前後值；無新增 / 刪除端點（405 / 不存在）
- 前端：清單分組、編輯儲存（MSW）、系統信不可停用、衝突提示重載

### 驗收條件

- [ ] ET 管理者進頁 → 列 `MODULE=ET`＋`MODULE=DP`，**不顯示** `DM`；DM 管理者反之（FR-02、AC1）
- [ ] 編輯主旨 / 內文 / 管道 / 啟停且版本未衝突 → 寫入 + `VERSION+1` + 稽核 + TEMPLATES-003；US6 後續以新範本渲染（FR-01/06、AC2）
- [ ] 範本停用 → 該事件不寄 Email、觸發事件照常（語意；US6 已依 `IS_ENABLED` 略過）（FR-07、AC3）
- [ ] `MODULE=DP` 系統信嘗試停用 / 刪除 → 阻擋 TEMPLATES-001；主旨 / 內文仍可編（FR-03、AC4）
- [ ] 並行編輯、後儲存者版本落後 → 拒絕 + TEMPLATES-002（樂觀鎖）（FR-05、AC5）
- [ ] 清單 / 編輯頁**無新增 / 刪除範本**功能；後端亦無對應端點（FR-04、AC6）
- [ ] ET 管理者直接呼叫 API 編輯 `MODULE=DM` 範本 → 伺服器端拒絕 TEMPLATES-004（FR-02、AC7）
- [ ] 管道含「站內」可儲存；欄位僅作是否寄 Email 開關（站內由模組自理）（FR-07、AC8）
- [ ] 範本異動寫 `DP_AUDIT_LOG`（含前後值）（FR-06）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`DP_NOTIFY_TEMPLATE` 表 + 5 支 DP 系統信種子 + `VERSION` 欄 + `module_admin_gate`（T017）
- **Issue #1（GitHub #27，US6）**：`SRVDP002` `get_template` 渲染（儲存後即時反映，無需額外接線）
- **跨模組（stub 先行）**：`is_module_admin`（`module_admin_gate`，T017 fail-closed）——過渡期一律回 False，A-strict 下**無人被判為管理者**；比照 US5 dp-params 暫行案（端點對登入者開放、MODULE 過濾邏輯就緒，特權判定待 T049 回歸）
- **ET / DM 範本種子**：目前僅 DP 系統信 5 支；`MODULE=ET` / `DM` 範本由各模組於其 migration 種子建立（未建前 ET / DM 管理者僅見 DP 系統信）

### 注意事項

- **與 US5 dp-params 對稱**：既有種子表的 MODULE 過濾維護 + A-strict + 稽核 + 無新增刪除；可沿用 US5 的 `list_visible` / `update_detail` 服務結構與前端 tab 分組模式。差異：US9 多 **`VERSION` 樂觀鎖** 與 **`IS_SYSTEM` 系統信保護**。
- **樂觀鎖**（FR-05）：儲存以 req body 帶入之 `version` 比對 DB；建議條件式 `UPDATE ... WHERE MODULE=:m AND TEMPLATE_CODE=:c AND VERSION=:v ... RETURNING`（比對 0 列＝衝突 409），關閉「查→改」TOCTOU（比照 US8 token 原子消費）。衝突 409 回應建議帶回**最新版本內容**供前端提示 diff / 重載（SD 自決回應形狀）。
- **系統信保護**（FR-03）：擋停用 / 刪除**依 `IS_SYSTEM` 旗標判定，不硬編碼 `TEMPLATE_CODE` 清單**（目前 `IS_SYSTEM=true` 為 `MODULE=DP` 5 支：`PWD_RESET` / `ACCOUNT_VERIFY` / `ACCOUNT_INVITE` / `EMAIL_CHANGE_VERIFY` / `PWD_EXPIRY_REMIND`；日後新增系統信只需種子設旗標）；主旨 / 內文 / 管道仍可編。
- **CHANNEL 站內為前瞻欄位**：`CHANNEL` 值域 `EMAIL` / `MSG` / `BOTH`，但**本期所有種子範本皆 `EMAIL`、DP 不處理站內發送**（站內由各模組自理，FR-07）；實務上僅「是否寄 Email」toggle 生效，`MSG` / `BOTH` 之站內效果待各模組落地。
- **無新增 / 刪除範本**：事件 `TEMPLATE_CODE` 固定（種子建立）；後端不提供 POST / DELETE 範本端點。
- **管道「站內」**（FR-07）：`CHANNEL` 僅作是否寄 Email 開關依據；DP 不儲存 / 不呈現站內訊息（各模組自理）。
- **Error codes**（實作 / `/sti-plan` 對齊 `sti-error-codes`）：越權重用 `DP_AUTH_006`（需模組管理者權限）；系統信保護 / 樂觀鎖衝突為 US9 新增（如 `DP_MAIL_003` 系統信不可停用〔403〕、`DP_MAIL_004` 版本衝突〔409〕，流水號接 `DP_MAIL_002` 之後）；範本不存在沿用 `DP_MAIL_001`。
- **前端路由已備**：`/dp/templates` 路由 + `TemplatesPage` stub 已存在（#0 骨架），本 issue 填實。

### 相關文件

- [spec_us9.md](spec_us9.md)、[spec.md](spec.md) §通知範本與發信引擎、[data-model.md](data-model.md)（`DP_NOTIFY_TEMPLATE` / DP 系統信種子）、[tasks.md](tasks.md) Phase 11（T040~T041）
- [contracts/platform-services.md](contracts/platform-services.md)（SRVDP002 渲染）
- 需求：[RQDP.md](../../requirements/RQDP.md) §通知範本與發信引擎；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP011

**Labels**：`P2-延伸`, `DP-平台`, `US9`

---

## Issue #10：[P2-延伸] DP — 操作記錄查詢（dp-audit）（GitHub [#97](https://github.com/sti-fhb/EDMS/issues/97)）

**對應規格**：[spec_us10.md](spec_us10.md)（US10 / UCDP007，FR-DP-US10-01~06、DP-MSG-DP09-001~002）；[data-model.md](data-model.md)（`DP_AUDIT_LOG`：append-only〔僅 `CREATED_*`〕、`MODULE` / `FUNC_NAME` / `ACTION_TYPE`〔LOGIN..DELETE〕/ `TARGET_ID` / `SOURCE_IP` / `BEFORE_VALUE` / `AFTER_VALUE`〔JSON 字串〕/ `ROW_HASH` 鏈式雜湊；索引 `(CREATED_DATE)`、`(CREATED_USER, CREATED_DATE)`、`(MODULE, ACTION_TYPE, CREATED_DATE)`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-audit`）
**階段**：P2-延伸（稽核**寫入**於各 US 內建，不依賴本 US；查詢 / 匯出介面於核心作業之後交付）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_AUDIT_LOG` 表 + `AuditLogService.log_action`（**寫入路徑**，各 US CUD 已呼叫）+ 模組管理者判定閘（T017 `module_admin_gate`）
- **各 US 稽核寫入已內建**（US1–US9 已合併、US11 內建）：本 issue 為**唯讀查詢**，查詢對象（`DP_AUDIT_LOG` 列）已由各 US 持續累積，無其他前置

### 任務說明

DP 後台操作記錄查詢頁（`dp-audit`）：ET / DM 管理者以**多條件**（操作者、期間**起訖**、模組、操作類別 LOGIN / LOGOUT / CREATE / UPDATE / DELETE）查詢全平台 `DP_AUDIT_LOG`（後端分頁、時間倒序），展開單筆明細檢視**異動前後值**（JSON），並依當前查詢條件**匯出 CSV**。稽核為**共用項**——**兩管理者皆可查全部**（含登入等不分模組事件；資安監督需全視野），此與 US5（dp-params）/ US9（dp-templates）之 `MODULE` 過濾**不同**：`模組`在此僅為**查詢條件**、非存取控制。日誌 **append-only**：介面與 API **無任何刪除 / 修改功能**。填實既有 `AuditPage` stub。

> ℹ️ 全端 issue：後端 `dp/audit` 補**查詢 / 匯出端點**（既有模組僅 `AuditLogService` 寫入、無 query router）+ 前端填實 `AuditPage`。**無新表 / migration**（表 + 寫入於 #0 已建）。唯讀、不分模組、無刪改——業務邏輯較 US5 / US9 單純（無樂觀鎖、無 MODULE 過濾），新元素為 **CSV 匯出** 與 **明細前後值展開**。

### 範圍

**後端**（`app/dp/audit/` — 補查詢 / 匯出，與既有 `log_action` 寫入同模組）：
- **T042 稽核查詢**：`GET /api/dp/audit/logs`——多條件（`operator`〔姓名 / Email / ID〕、`date_from` / `date_to`、`module`、`action_type`、`result`〔SUCCESS / FAIL〕）+ `paginate()` 後端分頁（**依 `CREATED_DATE` 倒序**）；列表回：時間（至秒）/ 操作者 / 模組 / 功能（`FUNC_NAME`）/ 類別 / **結果（`RESULT`）** / 對象（`TARGET_ID`）/ 來源 IP；明細（同筆或展開）回 **`RESULT` / `DESCRIPTION`** / `BEFORE_VALUE` / `AFTER_VALUE`（JSON 字串，`TEXT` 欄）；**僅管理者**（AUDIT-002）；**不提供任何刪改端點**（對應 FR-01/02/04/05）
- **T043 CSV 匯出**：`GET /api/dp/audit/logs/export`——**依查詢條件全量**（無分頁上限）匯出符合紀錄；欄位對齊列表 + 前後值；`text/csv`、UTF-8（含 BOM 供 Excel 正確顯示中文，編碼細節 SD 自決）（對應 FR-02/03）

**前端**（`frontend/src/dp/audit/`，填實 `AuditPage` stub）：
- **T043 查詢列**：操作者（文字）/ 模組（全部 / DP / ET / DM 下拉）/ 操作類別（全部 / LOGIN / LOGOUT / CREATE / UPDATE / DELETE 下拉）/ **執行結果（全部 / SUCCESS / FAIL 下拉）** / 期間起訖（date ～ date）+ 查詢 / 匯出鈕
- **T043 列表**：欄位 時間 / 操作者 / 模組 / 功能 / 類別（badge）/ **結果（SUCCESS / FAIL badge）** / 對象 / 來源 IP / 明細；後端分頁（`usePagedQuery`）、時間倒序；**無新增 / 編輯 / 刪除任何按鈕**
- **T043 明細展開**：檢視完整欄位（含**執行結果 / 事件描述**）+ 異動前後值（JSON 格式化呈現）；空狀態提示（AUDIT-001）

**測試**：
- 後端 int：多條件查得對應紀錄 + 時間倒序；明細含前後值；CSV 內容與查詢結果一致；一般使用者（非管理者）被擋（AUDIT-002）；**無刪改端點**（POST / PUT / DELETE 回 405 / 不存在）
- 前端：查詢 + 後端分頁、明細展開前後值、空狀態 AUDIT-001、匯出 CSV 觸發（MSW）；介面無刪改功能

### 驗收條件

- [ ] 以多條件（操作者、期間起訖、模組、操作類別、**執行結果 SUCCESS / FAIL**）查詢 → 列出符合之 `DP_AUDIT_LOG`（後端分頁、時間倒序，列表含結果欄）；**兩管理者皆可查全部**（含不分模組之登入等事件）（FR-01/02、AC1）
- [ ] 展開單筆明細 → 顯示完整欄位：操作者、時間（至秒）、功能 / 模組代碼、操作類別、**執行結果（SUCCESS / FAIL）**、**事件描述**、來源 IP、異動對象、**異動前後值（JSON 字串）**（FR-02/05、AC2）
- [ ] 點「匯出 CSV」→ 依**當前查詢條件**匯出全部符合紀錄，內容與查詢結果一致（FR-03、AC3）
- [ ] 查無符合紀錄 → 顯示空狀態提示 DP-MSG-DP09-001（FR-02、AC4）
- [ ] 頁面與 API **無任何刪除 / 修改功能**——日誌 append-only、不可於介面竄改 / 刪除（FR-04、AC5）
- [ ] ET / DM 資安事件（帳號 / 角色權限 / 系統操作）統一寫入同一張 `DP_AUDIT_LOG`、本頁可查；業務歷程（DM 文件變更 / 閱讀、ET 學習 / 作答）**不在此**（FR-05、AC6）
- [ ] 非管理者之一般使用者存取本頁或查詢 API → 伺服器端拒絕 DP-MSG-DP09-002（FR-01、AC7）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`DP_AUDIT_LOG` 表 + `AuditLogService.log_action`（寫入路徑）+ `module_admin_gate`（T017）
- **各 US 稽核寫入（US1–US9 已合併、US11 內建）**：本 issue 為唯讀查詢，查詢對象已由各 US 持續累積，**無其他前置**
- **跨模組（stub 先行）**：`is_module_admin`（`module_admin_gate`，T017 fail-closed）——過渡期一律回 False；本頁「僅管理者」姿態之 interim 處理見注意事項（暫行案）

### 注意事項

- **與 US5 / US9 的關鍵差異——不分模組（共用可見）**：稽核為**共用項**，ET / DM 管理者**皆可查全部**（資安監督需全視野），**不做 `MODULE` 過濾**。`模組`只是**查詢條件**（篩選要看哪個模組的紀錄），**非存取控制**。務必勿套用 dp-params / dp-templates 的 `list_visible` MODULE 過濾邏輯。
- **append-only、無刪改**（FR-04、AC5）：`DP_AUDIT_LOG` 僅 `CREATED_*`；後端**不提供 POST / PUT / DELETE**，前端無任何新增 / 編輯 / 刪除按鈕。`ROW_HASH` 鏈式完整性由**寫入端**（`AuditLogService._compute_row_hash`）維護，**查詢頁僅顯示、不驗鏈**（鏈驗證 / 竄改稽核非本 issue 範圍）。
- **「僅管理者」（AUDIT-002）vs DP 暫行案 A**（需 SA 裁示，`/sti-plan` 列 SA Q）：本頁 gate 比 dp-params / dp-templates **更嚴**——spec AC7 明訂「非管理者 MUST NOT 存取」。但 `is_module_admin`（T017）為 fail-closed stub、過渡期無人被判管理者，兩案擇一：
  - **方案 A（建議）**：比照整個 DP 模組 US5~US9 一致之暫行案——端點對**登入者**開放、`module_admin_gate` 判定邏輯就緒但特權判定待 **T049** 回歸真 gate；此時 AUDIT-002 之「非管理者被擋」以「未登入被擋」先行、管理者細分待 T049。頁面於 interim 可測。
  - **方案 B**：fail-closed 真擋——interim 無人可存取本頁（與模組其他頁不一致、無法手動驗證）。
  - → 傾向方案 A（與模組一致、頁面可測），T049 統一回歸；最終裁示由 SA 於 `/sti-plan` SA Q 確認。
- **執行結果 / 事件描述必呈現**（FR-05；`/sti-sa-precheck #10` 補）：`DP_AUDIT_LOG` 之 `RESULT`（SUCCESS / FAIL）與 `DESCRIPTION`（事件描述）為 FR-05 明訂記錄欄位，**列表 + 明細皆須呈現**、且 `result` 為查詢條件——否則「查失敗登入 / 越權拒絕」等核心資安稽核情境無法在頁面辨識。`RESULT` 值域見 data-model 代碼表（登入成功 / 失敗以 `RESULT` 區分，非 ACTION_TYPE）。
- **CSV 匯出**（FR-03）：依查詢條件**全量**（無分頁），與列表同條件；`text/csv` + UTF-8 BOM（Excel 中文）；欄位含結果 / 事件描述 / 前後值。大量匯出之上限 / 串流細節 SD 自決（可先全量、後續視效能加上限）。
- **Error codes**（實作 / `/sti-plan` 對齊 `sti-error-codes`）：越權（AUDIT-002）可**重用 `DP_AUTH_006`（需模組管理者權限，403）**或新增 `DP_AUDIT_001`（SD / SA 定）；AUDIT-001（查無紀錄）為**空結果 UI 提示、非 error code**（列表回空 `data` + `meta.total=0`）。
- **保留期 / 容量**（FR-06）：日誌保留 ≥ 1 年、容量失效自動因應（覆寫最舊）並留軌跡、每日備份與容量告警——屬 **IT 維運範圍**，spec 明列**不屬系統功能**，本 issue **不實作**（僅標註）。
- **前端路由已備**：`/dp/audit` 路由 + `AuditPage` stub 已存在（#0 骨架），本 issue 填實。

### 相關文件

- [spec_us10.md](spec_us10.md)、[spec.md](spec.md) §稽核（操作記錄）規則、[data-model.md](data-model.md)（`DP_AUDIT_LOG`）、[tasks.md](tasks.md) Phase 12（T042~T043）
- 需求：[RQDP.md](../../requirements/RQDP.md) §操作記錄（稽核）；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP007

**Labels**：`P2-延伸`, `DP-平台`, `US10`

---

## Issue #11：[P2-延伸] DP — 排程引擎與總覽 + SCHDP001（dp-schedule）（GitHub [#106](https://github.com/sti-fhb/EDMS/issues/106)）

**對應規格**：[spec_us11.md](spec_us11.md)（US11 / UCDP008，FR-DP-US11-01~07、DP-MSG-DP10-001）；[data-model.md](data-model.md)（`DP_SCHEDULE`：`JOB_ID` PK / `JOB_NAME` / `MODULE` / `CRON_EXPR` / `HANDLER_REF`〔dotted path〕/ `IS_ENABLED` / `LAST_RUN_DATE` / `LAST_RUN_STATUS`；`DP_SCHEDULE_LOG`：append-only、`JOB_ID` FK / `START_DATE` / `END_DATE` / `STATUS`〔SUCCESS / FAILED / SKIPPED〕/ `ERROR_MSG`）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §5（job handler `async def run()`）；[research.md](research.md) §9（APScheduler + DB 註冊表 + leader）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-schedule`，唯讀總覽）
**階段**：P2-延伸（承載 ET / DM 各模組排程與平台自身 `SCHDP001`；各模組排程功能上線前完成即可）
**前置條件**：
- Issue #0（GitHub [#16](https://github.com/sti-fhb/EDMS/issues/16)）已合併：`DP_SCHEDULE` + `DP_SCHEDULE_LOG` 表（T008）+ **種子（T009）**：`SCHDP001` 啟用（cron `0 8 * * *`、`HANDLER_REF=app.dp.schedules.handlers.daily_platform_job`）、`SCHET001` / `SCHET002` / `SCHDM001` 為 **`IS_ENABLED=false` 預留列**（handler 待各模組提供）+ 平台級參數（`LOGIN.IDLE_DISABLE_DAYS=90`、`PWD_POLICY.EXPIRY_DAYS=90` / `EXPIRY_REMIND_DAYS=7`）+ `apscheduler>=3.11` 依賴（註：`scheduler_leader.py` #0 實際未建，本 issue 自建 `is_leader()` 恆 True 之最小版）
- Issue #1（GitHub [#27](https://github.com/sti-fhb/EDMS/issues/27)，US6）已合併：`SRVDP002` 發信服務——`SCHDP001` 之密碼到期提醒經此寄出
- Issue #9（US9）已合併：`MODULE=DP` **`PWD_EXPIRY_REMIND`「密碼到期提醒」範本**（種子於 #0、內容可於 US9 維護）——本 issue 為其**首個實際寄送點**（US9 手測時確認寄送 await 排程，於此補齊）

### 任務說明

平台**單一排程執行引擎** + **平台自身排程 `SCHDP001`** + **唯讀排程總覽**（`dp-schedule`）。引擎以 APScheduler（`AsyncIOScheduler`）於 FastAPI lifespan 啟動時自 `DP_SCHEDULE` 載入**啟用中** job（cron + `HANDLER_REF` 動態 import 各模組 / 平台 handler），`max_instances=1` + coalesce 落實「前次未完成跳過本次」（跳過亦記 `SKIPPED`），每次執行寫 `DP_SCHEDULE_LOG`（起訖 / 結果 / 錯誤）並更新 `DP_SCHEDULE.LAST_RUN_*`，**單一 job 失敗隔離不影響其他**；多實例以 leader 選舉確保只觸發一次（EDMS 預設單一實例直跑）。`SCHDP001`（每日）執行①閒置帳號禁用②密碼到期提醒。ET / DM 管理者於總覽頁**唯讀**檢視 job 清單與執行歷程，**無 UI 啟停 / 補跑**（啟停由 DB / 部署管理）。填實既有 `SchedulePage` stub。

> ℹ️ 全端 issue（引擎 + handler + 唯讀 UI）。**本 issue 交付「引擎 + `SCHDP001`（DP 自持）+ 總覽」**；`SCHET001` / `SCHET002` / `SCHDM001` 之 handler 由 **ET / DM 模組後補**（預留列 `IS_ENABLED=false`、引擎自動略過），不阻塞本 issue。**無新表 / migration**（表 + 種子於 #0 已建）。與既有 US6 outbox worker（常駐 asyncio task）同屬 lifespan 背景元件、併存。

### 範圍

**後端**（`app/dp/schedules/` — 引擎 + handler + 總覽端點；模型於 #0 已建）：
- **T044 排程引擎** `core/scheduler`：`AsyncIOScheduler`；FastAPI lifespan 啟動時自 `DP_SCHEDULE` 載入 `IS_ENABLED=true` job（`CronTrigger.from_crontab(CRON_EXPR)` + `HANDLER_REF` 動態 import 取 `run` callable）；每 job `max_instances=1` + `coalesce`（前次未完成 → 本次跳過、寫 `DP_SCHEDULE_LOG`（`SKIPPED` + 原因））；執行以獨立交易包裹、寫 `DP_SCHEDULE_LOG`（`START_DATE` / `END_DATE` / `STATUS` / `ERROR_MSG`）+ 更新 `LAST_RUN_DATE` / `LAST_RUN_STATUS`；**例外捕捉、單 job 失敗不影響其他**；`scheduler_leader.py`（單實例直跑、多實例 leader 選舉，起手包沿用），對應 FR-01~04
- **T045 `SCHDP001` handler** `app.dp.schedules.handlers.daily_platform_job`（每日）：① `ACTIVE` 帳號 `LAST_LOGIN_DATE` 逾 `LOGIN.IDLE_DISABLE_DAYS`（90）→ `STATUS=DISABLED` + 寫 `DP_AUDIT_LOG`（**`func_name=DP-USERS`**、operator=SYSTEM，使 dp-audit 對象顯示姓名）；**`LAST_LOGIN_DATE` 為 null（從未登入）以 `CREATED_DATE` 為基準**；② `PWD_CHANGED_DATE` 距 `PWD_POLICY.EXPIRY_DAYS`（90）剩 ≤ `EXPIRY_REMIND_DAYS`（7）之使用者 → 經 `SRVDP002` 寄 `PWD_EXPIRY_REMIND`（**每日跑均寄、直至變更 / 到期**）；兩批次**各自逐筆容錯**（單一使用者失敗不擋其他），對應 FR-05
- **T046 總覽 / 編輯端點**：`GET /api/dp/schedules`（job 清單 + 由 cron 計算之 `next_run_date`）+ `GET /api/dp/schedules/{job_id}/logs`（歷程分頁）+ **`PUT /api/dp/schedules/{job_id}`（編輯 `JOB_NAME` / `CRON_EXPR` / `IS_ENABLED`；cron 驗證、稽核 `func_name=DP-SCHEDULE`、`apply_job_change` 即時生效）**；**無手動補跑端點；`HANDLER_REF` / `MODULE` / `JOB_ID` 不可改**；共用項（`get_jwt_payload`、暫行案 A），對應 FR-06/07。error codes：`DP_SCHED_001`（404）/ `DP_SCHED_002`（422 cron 非法）

**前端**（`frontend/src/dp/schedules/`，填實 `SchedulePage` stub）：
- 唯讀 job 清單（`JOB_ID` / 說明〔`JOB_NAME`〕/ cron / 啟停狀態 / 上次執行時間 + 結果 badge）+ 點列**展開執行歷程**（`DP_SCHEDULE_LOG`：起訖 / 結果 / 錯誤）+ 空狀態提示（SCHEDULE-001）
- **全頁無啟停 / 手動補跑任何按鈕**（唯讀）

**測試**：
- 後端 int：cron 觸發 → 寫 `DP_SCHEDULE_LOG` 起訖 + `SUCCESS` + 更新 `LAST_RUN_*`；job 失敗 → `FAILED` + 錯誤訊息、**其他 job 照常**；前次未完成 → `SKIPPED`；`IS_ENABLED=false` 不觸發；`SCHDP001`：種閒置 > 90 日帳號 → `DISABLED` + 稽核、種密碼將到期使用者 → `DP_EMAIL_LOG` PENDING（`PWD_EXPIRY_REMIND`）；總覽端點唯讀（**無啟停 / 補跑端點** → 405 / 不存在）；未登入 401
- 前端：job 清單 + 歷程展開 + 空狀態 SCHEDULE-001；介面無操作按鈕

### 驗收條件

- [ ] job 於 `DP_SCHEDULE` 登錄且啟用、cron 到期 → 引擎觸發，`DP_SCHEDULE_LOG` 留起訖與 `SUCCESS`、更新 `LAST_RUN_*`；多實例僅 leader 觸發一次（單實例直跑）（FR-01/02/03、AC1/2）
- [ ] job 執行失敗 → `DP_SCHEDULE_LOG` 記 `FAILED` + 錯誤訊息，**不影響其他 job**（FR-03、AC3）
- [ ] 前次執行未完成、下次 cron 到期 → 跳過本次並記 `SKIPPED`（不重複執行同一 job）（FR-03、AC4）
- [ ] `IS_ENABLED=false` 之 job → cron 到期不觸發（FR-01、AC5）
- [ ] `SCHDP001`（每日）→ ① 連續 90 日未登入帳號自動 `DISABLED` + 稽核（`LAST_LOGIN_DATE` 逾 `IDLE_DISABLE_DAYS`；**null 從未登入以 `CREATED_DATE` 為基準**）；② 密碼到期前 7 天起經 US6 寄 `PWD_EXPIRY_REMIND`（`MODULE=DP`，每日跑均寄至變更 / 到期）（FR-05、AC6）
- [ ] ET / DM 管理者進總覽 → 列各 job（`JOB_ID` / 說明 / cron / 狀態 / 上次 + **下次執行時間**）並可展開歷程；**可編輯 JOB_NAME / cron / 啟停（cron 即時生效）**；**無手動補跑、handler 不可改**；無紀錄顯示空狀態 SCHEDULE-001（FR-06、AC7）
- [ ] 排程時間等參數存 `DP_PARAM`（模組前綴），引擎於觸發時讀最新值（FR-07）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check 通過

### 依賴

- **Issue #0（GitHub #16）**：`DP_SCHEDULE` / `DP_SCHEDULE_LOG` 表 + 種子（`SCHDP001` 啟用 + ET/DM 預留列 + 相關參數）+ `apscheduler` 依賴 + `scheduler_leader.py` 起手包
- **Issue #1（GitHub #27，US6）**：`SRVDP002`（密碼到期提醒寄送）
- **Issue #9（US9）**：`PWD_EXPIRY_REMIND` 範本（本 issue 首個實際寄送點）
- **Issue #6（US5）**：平台級參數（`IDLE_DISABLE_DAYS` / `EXPIRY_DAYS` / `EXPIRY_REMIND_DAYS`；已種子、可維護）
- **ET / DM job handler（各模組後補）**：`SCHET001` / `SCHET002` / `SCHDM001` handler 由 ET / DM 提供（`async def run()`，contracts §5）；本 issue 僅交付引擎 + `SCHDP001`，預留列 `IS_ENABLED=false` 引擎自動略過，**不阻塞**

### 注意事項

- **交付邊界**：本 issue = **引擎 + `SCHDP001`（DP 自持）+ 唯讀總覽**。ET / DM 的 `SCHET` / `SCHDM` handler 由各模組於其開發時提供並將對應 `DP_SCHEDULE` 列 `IS_ENABLED=true`；引擎對 `HANDLER_REF` 動態 import，預留列停用故不觸發、亦不需其 handler 存在。
- **`PWD_EXPIRY_REMIND` 首落地**：US9 已備範本 + 維護，但「密碼到期提醒」之**寄送**待本排程（US9 手測時已確認未實作）；本 issue 之 `SCHDP001` ② 補齊寄送鏈（經 `SRVDP002` → `DP_EMAIL_LOG` → outbox worker 寄出）。
- **引擎與 lifespan**：`AsyncIOScheduler` 於 FastAPI lifespan 啟動 / 收斂，與 US6 outbox 常駐 worker **併存**（兩者皆 lifespan 背景元件，非互相依賴）。`max_instances=1` + `coalesce` 落實 FR-03「前次未完成跳過」；**`SKIPPED` 亦寫 `DP_SCHEDULE_LOG`**（非靜默略過）。
- **leader 選舉**（FR-02）：本 issue **自建** `scheduler_leader.py` 最小版（`is_leader()` 恆 True，#0 未實際建）；**EDMS 預設單一實例直跑**（多實例 leader 為前瞻，避免多實例重複觸發）。
- **失敗隔離與交易邊界**（FR-03）：每 job 執行以獨立交易、例外由引擎捕捉記 `FAILED`，不影響排程器與其他 job；`SCHDP001` 內「閒置禁用批次」與「到期提醒批次」各自逐筆容錯（單一使用者失敗不擋其餘）。
- **閒置基準 null 處理**（`/sti-sa-precheck dp us11` 補）：`last_login_date` 僅於**登入成功**時設，活化不設 → 活化但從未登入之帳號 `LAST_LOGIN_DATE=null`；`SCHDP001` 對此類帳號**以 `CREATED_DATE` 為閒置起算基準**（休眠邀請 / 註冊帳號同樣 90 日後禁用）。
- **閒置禁用稽核 `func_name=DP-USERS`**（跨 issue 一致）：US10 dp-audit 之對象解析器依 `func_name ∈ 使用者類` 才把 target 解析為姓名；SCHDP001 禁用寫稽核用 `func_name=DP-USERS`、operator=`SYSTEM`，操作記錄「對象」欄方顯示被禁用者姓名而非原始 USER_ID。
- **密碼到期提醒為每日重寄**（FR-05）：`SCHDP001` 每日跑，落在「到期前 `EXPIRY_REMIND_DAYS` 天」窗內之使用者**每日均寄**一封，直至其變更密碼或密碼到期（非單次；避免遺漏、亦符「持續提醒」意圖）。
- **`DP_SCHEDULE` 異動＝重啟生效（MVP）**：引擎於 lifespan 啟動時載入 `DP_SCHEDULE`，runtime 改 `CRON_EXPR` / `IS_ENABLED` **不熱重載、需重啟生效**。SCHDP001 為固定每日不受影響；**cron 熱重載（watcher 式）留 ET/DM param-driven cron 落地時評估**（本 issue 範圍外）。
- **可編總覽 + 暫行案 A**（FR-06；手測回饋擴充）：總覽為共用項，**可編 `JOB_NAME` / `CRON_EXPR` / `IS_ENABLED`**（`PUT /{job_id}`，cron 驗證 + `apply_job_change` 即時 reschedule/add/remove）；**仍不提供手動補跑**（補跑各模組自理，冪等性因 job 而異——如 SCHDP001 到期提醒重跑會重複寄信）；**`HANDLER_REF` 永不可經 UI 改**（改＝RCE，配合 `_resolve_handler` 白名單）。授權比照 dp-audit 暫行案 A（`get_jwt_payload`、真 gate 待 T049 重用 `DP_AUTH_006`）。
- **稽核 vs 排程歷程**：閒置禁用寫 `DP_AUDIT_LOG`（資安事件、operator=SYSTEM）；排程**執行歷程**寫 `DP_SCHEDULE_LOG`（非稽核表、無 ROW_HASH 鏈）。
- **Error codes**：排程執行本身**無使用者介面錯誤碼**（結果記 `DP_SCHEDULE_LOG` 與應用層 log）；總覽越權待 T049 重用 `DP_AUTH_006`；SCHEDULE-001 為空狀態 UI 提示、非 error code。
- **前端路由已備**：`/dp/schedule` 路由 + `SchedulePage` stub 已存在（#0 骨架），本 issue 填實。

### 相關文件

- [spec_us11.md](spec_us11.md)、[spec.md](spec.md) §排程引擎、[data-model.md](data-model.md)（`DP_SCHEDULE` / `DP_SCHEDULE_LOG`）、[tasks.md](tasks.md) Phase 13（T044~T046）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §5（job handler）、[research.md](research.md) §9（APScheduler + leader）
- 需求：[RQDP.md](../../requirements/RQDP.md) §排程基礎建設；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP008

**Labels**：`P2-延伸`, `DP-平台`, `US11`

---

## Issue #12：[收尾] DP — 整合測試 + 稽核驗鏈工具 + 安全驗收（不含 T049 / ET-DM 回歸）（GitHub [#114](https://github.com/sti-fhb/EDMS/issues/114)；T049 follow-up [#113](https://github.com/sti-fhb/EDMS/issues/113)）

**對應規格**：[spec.md](spec.md) §Success Criteria（SC-001~011）；[tasks.md](tasks.md) Phase 14（T047~T054）；[data-model.md](data-model.md)（`DP_AUDIT_LOG` ROW_HASH 鏈）；各 US spec（本 issue 為既有實作之端到端驗收，不新增業務功能）
**階段**：收尾（DP 各 US〔#0~#11〕已合併後之整合驗收與淨新增工具）
**前置條件**：
- Issue #0~#11 全數已合併（認證鏈 US1~US3、使用者管理 US4、參數 US5、發信 US6、權限 US7、個資 US8、範本 US9、稽核 US10、排程 US11）
- 各 US 之 per-feature 整合測試已就緒（`backend/tests/integration/dp/`）；本 issue 補**跨 US 端到端**串接與淨新增之驗鏈工具

### 任務說明

DP 模組**收尾整合驗收**：以跨 US 端到端整合測試驗證各 Success Criteria 已真正貫通（認證鏈、鎖定失效、發信 outbox、排程、參數即時性、安全防護），並**淨新增稽核 ROW_HASH 驗鏈工具**（目前僅寫入端建鏈、無驗證端）。本 issue **不新增業務功能**，產出為整合測試檔 + 驗鏈工具 + 安全姿態文件化。

> ⚠️ **範圍裁示（2026-08-03）**：`backend/app/et/`、`backend/app/dm/` **尚未存在**，跨模組 checker（`is_module_admin` / `has_any_role` / `grant_default_student_role`）在生產環境未註冊、一律 fail-closed。故 tasks.md 原列 T049 之兩項**排除於本 issue、另立 follow-up**（待 ET/DM 落地）：
> 1. **T049 真授權閘掛 router**：`is_module_admin` gate 與模組過濾邏輯**已就緒**，但各 DP router 仍掛暫行案 A（`get_jwt_payload`，任何登入者可存取）。現在改掛 `require_module_admin` 會因無 checker 註冊 → 每個後台端點對所有人 403、鎖死 DP 後台。
> 2. **T047/T051 之 ET/DM 回歸**：ET `grant_default_student_role`、DM `has_any_role`、`SCHET*/SCHDM*` handler 待各模組提供，本 issue 僅對現有 stub 驗接線。

### 範圍

**淨新增工具（後端）**：
- **T052 稽核 ROW_HASH 驗鏈工具** `app/dp/audit/`：`AuditLogService.verify_chain(db)`（依插入序走訪 `DP_AUDIT_LOG`、逐列以 `_compute_row_hash` 重算並比對存檔 `ROW_HASH`、串接 prev hash，回報總筆數 / 首個斷鏈列〔`ID` / `LOG_TIME` / `FUNC_NAME`〕/ OK|BROKEN）+ 可執行入口（`python -m app.dp.audit.verify_chain`，ops 例行稽核用）；唯讀、不改資料

**整合測試（後端 `backend/tests/integration/dp/`，跨 US 端到端）**：
- **T047 認證鏈端到端**：`e2e` — ① 自助註冊 → 驗證信 → 登入 → 操作換發 → 閒置逾時失效 → 忘記密碼 → 重設 → 新密碼登入；② 管理者代建帳號 → 初始密碼首登 → 強制變更 → 正常使用（SC-001/003/004/005）
- **T048 鎖定與失效端到端**：錯 5 次自動鎖定 → 逾時 / 管理者解鎖後可再登入；停用帳號下次請求即拒（`get_jwt_payload` 閘）；換發逾單日 8h 上限拒絕（SC-002/005/006）
- **T050 發信引擎端到端**：`send_email` 不阻塞呼叫方（PENDING 立即返回、worker 非同步寄）、重試逾上限 → `FAILED` 留錯誤、停用範本 → skip 事件照常、範本改後新信以新內容渲染、**已寄快照不受事後改範本影響**（SC-009）
- **T051 排程端到端（單實例）**：cron 觸發僅一次、單 job 失敗不影響其他、重疊 → `SKIPPED`、`SCHDP001` 兩職責（閒置禁用 + 到期提醒）、`DP_SCHEDULE_LOG` 完整（SC-011；多實例 leader 為前瞻，單實例直跑驗證）
- **T052 稽核驗鏈端到端**：多 US 事件寫入後 `verify_chain` 回 OK；人為竄改一列 before/after 值 → `verify_chain` 精準指出斷鏈列；append-only（repo 無 update/delete、端點 405）（SC-010）
- **T053 安全性驗收**：速率限制生效（登入 / 忘記密碼 / 密碼變更 IP + 帳號維度）、防帳號列舉回覆一致（忘記密碼 / 註冊；**登入分流訊息為 spec_us1 明訂 UX、非盲點**，測試中標註）、token 一次性 + 雜湊儲存、密碼策略 / 歷程 N 次、系統錯誤僅簡短訊息 + 代碼、輸入驗證皆伺服器端
- **T054 參數即時性**：US5 儲存後 `SRVDP001` 讀取即時反映（無快取延遲）、`DETAIL_LOCK` 之碼建立後不可改（SC-008）

**文件化（安全姿態，非程式碼缺口者明載為部署 / 遞延）**：
- **DB 層 append-only GRANT**（`DP_AUDIT_LOG` 僅 INSERT/SELECT）屬 **ops / 部署層**（非 migration），本 issue 於 `docs/ref/` 記錄應套用之 GRANT，實際套用隨部署
- **T049 + ET/DM 回歸** follow-up issue 連結（收尾時開立）

### 驗收條件

- [ ] `AuditLogService.verify_chain(db)` 實作 + 單元 / 整合測試：完整鏈回 OK；竄改任一列 → 精準回報首個斷鏈列（`ID` / `LOG_TIME` / `FUNC_NAME`）；空表回 OK（T052、SC-010）
- [ ] 可執行入口 `python -m app.dp.audit.verify_chain` 輸出人可讀結果（總筆數 / 狀態 / 斷鏈位置），供 ops 例行稽核
- [ ] T047 認證鏈端到端整合測試綠：自助註冊→登入→換發→閒置失效→忘記密碼→重設→登入；代建→首登→強制變更→正常使用（SC-001/003/004/005）
- [ ] T048 鎖定與失效端到端綠：5 次鎖定→解鎖→再登入；停用即拒；換發逾 8h 拒（SC-002/005/006）
- [ ] T050 發信端到端綠：不阻塞、重試 FAILED、停用範本 skip、範本改後新內容、快照不受事後改動（SC-009）
- [ ] T051 排程端到端綠：觸發一次、失敗隔離、重疊 SKIPPED、SCHDP001 兩職責、LOG 完整（SC-011）
- [ ] T053 安全驗收綠：限流、防列舉一致（登入分流已標註為刻意 UX）、token 一次性 + 雜湊、密碼策略 / 歷程、伺服器端驗證（SC-004 + 安全）
- [ ] T054 參數即時性綠：US5 存後 SRVDP001 即時反映、`DETAIL_LOCK` 碼不可改（SC-008）
- [ ] DB append-only GRANT 記於 `docs/ref/`（標明部署層套用）；T049 + ET/DM 回歸 follow-up issue 已開立並於本 issue close 摘要連結
- [ ] `uv run pytest -q` 全綠；ruff / 覆蓋率門檻通過

### 依賴

- **Issue #0~#11（全部已合併）**：本 issue 為其端到端整合驗收
- **ET / DM 模組（未落地）**：T049 真授權閘 + `grant_default_student_role` / `has_any_role` / `SCHET*/SCHDM*` handler 回歸皆待 ET/DM，**排除於本 issue**、另立 follow-up

### 注意事項

- **本 issue 不新增業務功能**：產出＝跨 US 整合測試 + 稽核驗鏈工具 + 安全姿態文件化。既有各 US 實作已於各自 issue 交付並有 per-feature 測試，本 issue 補「端到端貫通」與「淨新增驗鏈工具」。
- **T049 為 follow-up 非本 issue**（2026-08-03 使用者裁示範圍 A）：授權閘骨架（`is_module_admin` fail-closed gate + `require_module_admin` factory + service 層模組過濾）**已就緒**，缺的只是「掛上 router」與「ET/DM 註冊 checker」。因 ET/DM 未落地，現在掛閘會鎖死後台，故遞延；暫行案 A（`get_jwt_payload`）維持不動。
- **稽核鏈為單一全域鏈**：`DP_AUDIT_LOG` 以 advisory lock 序列化寫入、`ROW_HASH` 串接前一列 hash（非 per-func_name 分鏈）；`verify_chain` 依插入序（`ID`）走訪全表重算。竄改偵測涵蓋 before/after 值、`FUNC_NAME`、`ACTION_TYPE` 等入 hash 之欄位。
- **無狀態 JWT、無 refresh token**：T047 換發驗收針對「以現行有效 access token 靜默換新」+ 單日 8h 上限（`DP_AUTH_003`），非 refresh token 機制。
- **登入訊息分流非防列舉盲點**：登入對「帳號不存在 / 未驗證 / 密碼錯誤」回不同訊息（`DP_AUTH_007/010/008`）為 spec_us1 Clarification 明訂之 UX；忘記密碼 / 註冊維持防列舉一致訊息。T053 測試須同時涵蓋兩種策略並註記差異為刻意設計。
- **DB append-only GRANT 屬部署層**：應用層已落地 append-only（repo 無 update/delete、端點 405）；DB 層 `GRANT INSERT, SELECT`（撤 UPDATE/DELETE）於 ops 套用，本 issue 只文件化不落 migration。
- **無新表 / migration**：驗鏈工具為讀取端；整合測試不改 schema。

### 相關文件

- [spec.md](spec.md) §Success Criteria（SC-001~011）、[tasks.md](tasks.md) Phase 14（T047~T054）、[data-model.md](data-model.md)（`DP_AUDIT_LOG`）
- [contracts/module-callbacks.md](contracts/module-callbacks.md)（ET/DM 回歸接口）、各 US spec（端到端驗收對象）

**Labels**：`收尾`, `DP-平台`

---

## 異動紀錄

| 日期 | 異動 |
|------|------|
| 2026-07-09 | 首版：總覽表（#0–#12）+ Issue #0（Foundation）完整撰寫；採增量模式，#1 起待 #0 驗證後補入 |
| 2026-07-09 | 補 Issue 開立規則（標題 `[{階段}] {模組代碼} — {功能名稱}`、Labels 階段+`DP-平台`+US、依序開立標依賴編號）；總覽表加 GitHub # 欄；Issue #0 已開立為 GitHub #16 並依規則更名、換 labels（`priority:P0` + `DP-平台`）|
| 2026-07-16 | #0（#16）實作驗證完成並合併後，依增量模式補入 Issue #1（通知發送服務 / US6）完整 body |
| 2026-07-16 | 收斂郵件環境變數命名為 fastapi-mail 慣例：`config.py` `MAIL_HOST`→`MAIL_SERVER`、`.env.example` 同步、ext 契約 / tasks T020 之 `SMTP_*`→`MAIL_*`（`MAIL_SSL_TLS` / `MAIL_SUPPRESS_SEND` 待 T020 依需要補）|
| 2026-07-16 | US6 交付前自檢（`/sti-sa-precheck dp us6`）補唯一缺口：spec_us6 FR-03 + AC4、contracts SRVDP002、本 Issue #1 驗收條件補明 `CHANNEL` 不含 Email（`MSG`）時不寄（`skipped_reason="CHANNEL_NOT_EMAIL"`）|
| 2026-07-16 | Issue #1（US6 發信服務）已開立為 GitHub [#27](https://github.com/sti-fhb/EDMS/issues/27)，回填總覽表 GitHub # 欄與狀態 |
| 2026-07-20 | Issue #2（US1 登入）已合併（PR #33 / #36）；依增量模式補入 Issue #3（使用者自助註冊 / US2）完整 body（T026~T027，前置 #0 / #2 + ET `grant_default_student_role` stub）|
| 2026-07-20 | Issue #3（US2 自助註冊）已開立為 GitHub [#39](https://github.com/sti-fhb/EDMS/issues/39)，回填總覽表 GitHub # 欄與狀態 |
| 2026-07-20 | Issue #3（US2）已合併（PR #42）並 close（#39）；依增量模式補入 Issue #4（忘記密碼 / US3）完整 body（T028~T029，前置 #0 / #1〔SRVDP002 非 stub〕/ #2）|
| 2026-07-20 | Issue #4（US3 忘記密碼）已開立為 GitHub [#47](https://github.com/sti-fhb/EDMS/issues/47)，回填總覽表 GitHub # 欄與狀態 |
| 2026-07-21 | Issue #4（US3）已合併（PR #51）並 close（#47）；依增量模式補入 Issue #5（使用者管理 / US4）完整 body（T030~T032；標註為首個後台 CRUD 頁、需 bootstrap 前後端 CRUD 共用基礎設施 + get_operator；admin 授權閘列為開工前釐清）|
| 2026-07-16 | Issue #1（US6）實作完成並合併（PR #29 squash），總覽表狀態更新；依增量模式補入 Issue #2（US1 登入 / 登出與模組入口頁）完整 body |
| 2026-07-22 | Issue #5（US4 使用者管理）已開立為 GitHub [#61](https://github.com/sti-fhb/EDMS/issues/61) 並完成開發合併（PR #63 / #64）；依增量模式補入 Issue #6（系統參數與清單維護 / US5）完整 body（T033~T034；讀取服務 SRVDP001 已於 Foundation 就緒，本 issue 補維護 UI + 寫入端點；模組過濾 admin 授權閘同 #5 列為開工前釐清；CRUD toolkit 沿用 #5、不再 bootstrap）|
| 2026-07-23 | US5 交付前自檢（`/sti-sa-precheck`）補缺口：spec_us5 新增「參數型別 / 值域驗證規則」章節（FR-03 落地，平台級逐項對照表 + 跨欄位一致性 + code-registry 宣告）；wireframe `dp-params` 補平台級警告（PARAMS-005）、`IS_ACTIVE`→`IS_ENABLED`；spec.md 稽核前後值 `JSONB`→`TEXT`（對齊 research §6）；Issue #6 body 對齊（分區→三頁籤、VALUE 多鍵參數組澄清）。Issue #6 已開立為 GitHub [#68](https://github.com/sti-fhb/EDMS/issues/68)，回填總覽表 |
| 2026-07-27 | Issue #6（US5 系統參數與清單維護）完成開發並**合併（PR [#73](https://github.com/sti-fhb/EDMS/pull/73)）**、close（#68）；實作期對齊 TBMS（`DP_PARAM_D` 補 `PARAM_NAME`/`DESCRIPTION` 自描述、刪前端硬編碼；ACTION_TYPE 系統 enum 不納維護；`VERIFY_SEND_COOLDOWN_SEC` 納入維護），詳見 spec_us5 §參數型別 / 值域驗證規則。總覽表 #6 狀態更新為已合併 |
| 2026-07-27 | 依增量模式補入 Issue #7（權限管理 / US7 / dp-roles）完整 body（T035~T036）：DP 為**轉接層**（畫面在 DP、資料與判定在模組），全程對 ET/DM `get_user_roles_*` / `assign_roles_*` stub 驗接線，自我保護 / 標籤值檢核 / 稽核皆在模組（contracts §3）；標籤清單讀 DP_PARAM（US5）；admin 授權閘同 #5/#6 列為開工前釐清；完整驗收待 T049 |
| 2026-07-27 | US7 交付前自檢（`/sti-sa-precheck #7`）補缺（PR #80）：contracts §3 定義 `EtRoleTagView` / `DmRoleAudienceView` 欄位 + 讀取改批次 `get_users_roles_*`（決策 3=B）+ 標籤回代碼、名稱由 DP 讀 DP_PARAM（1=A）+ 含 last_modified（2=A）；spec_us7 FR-06 自我保護訊息統一映射 DP-MSG-DP06-001；wireframe dp-roles 補 AC5 呈現；Issue #7 body 同步（批次更名 + 標籤依賴提醒）|
| 2026-07-27 | 依增量模式補入 Issue #8（個人資料維護 + 強制變更密碼 / US8 / dp-profile）完整 body（T037~T039）：姓名直接存、Email 新信箱驗證延遲切換（重用 `DP_PWD_RESET` EMAIL_CHANGE token + `PENDING_EMAIL`）、密碼變更驗舊 + 特權 12 + 重複性 + 清 `MUST_CHANGE_PWD`；承載 US1 強制變更頁（填實 `ForceChangePasswordShell` 提交端點）；發信 SRVDP002 非 stub；特權門檻依 is_module_admin（stub 期套一般 8、待 T049）|
| 2026-07-27 | US8 交付前自檢（`/sti-sa-precheck #8`）：結論規格齊備、無必補；補 2 項澄清進 Issue #8 body ——「強制變更沿用同一 `PUT /me/password` 端點、仍需舊密碼」+「Email 變更驗證落點頁 `/verify-email-change`（沿用 US3 免登入落點頁殼）」。data-model / wireframe / 契約（SRVDP002 非 stub）皆已齊備。另決議將 [#77](https://github.com/sti-fhb/EDMS/issues/77)（密碼規則提示動態化）**核心併入 US8**：建公開 `GET /api/password-policy` 端點 + `usePasswordPolicy` hook，US8 變更密碼頁提示數字動態讀 `PWD_POLICY`；#77 收斂為 retrofit US2 / US3 |
| 2026-07-29 | US8（#83 / PR #87）與 #77（PR #90）已合併進 main；依增量模式補入 Issue #9（通知範本維護 / US9 / dp-templates）完整 body（T040~T041）：既有 `DP_NOTIFY_TEMPLATE` 表 + 種子（#0）之 MODULE 過濾維護（A-strict，比照 US5）、`IS_SYSTEM` 系統信保護（不可停用 / 刪除）、`VERSION` 樂觀鎖（衝突 409）、無新增 / 刪除範本、稽核；無新表 / migration；填實 `TemplatesPage` stub；error codes 建議 `DP_MAIL_003`（系統信保護）/ `DP_MAIL_004`（版本衝突）、越權重用 `DP_AUTH_006`；特權判定同 stub 過渡待 T049 |
| 2026-07-29 | US9 交付前自檢（`/sti-sa-precheck #9`）修 1 必補：spec_us9 FR-03 / AC4 / 前置依賴之「DP 系統信 3 支」→ **4 支**（補 `ACCOUNT_VERIFY` 帳號註冊驗證，對齊 data-model / wireframe / 實際 seed），並改為**系統信保護依 `IS_SYSTEM` 旗標判定、不硬編碼 `TEMPLATE_CODE` 清單**；Issue #9 body 同步（前置 4 支 + 注意事項旗標驅動 + 樂觀鎖 409 回最新版本 + CHANNEL 站內為前瞻欄位）|
| 2026-08-07 | Issue #7（US7 dp-roles）body 對齊：DM US1（[#133](https://github.com/sti-fhb/EDMS/issues/133)）已交付合併，故將原「全程 stub、完整驗收待 T049」之**快照式**前提改為**不變框架**——US7 泛用消費 `core/module_assign.py` `module_assign_registry`（US1 建，generic `ModuleAssignProvider`：`get_users_assignments` / `assign` / `list_controlled` / `list_audiences`），**已註冊模組整合、未註冊 fail-closed**；當下 DM real（可 end-to-end 驗）、ET fail-closed（未開發）。ET 落地後自動接上、US7 不需再改（body 與程式碼皆不重寫）。registry 名由原「`core/module_roles.py` 或類似」更正為 `core/module_assign.py`。尚未開立 GitHub issue |
| 2026-07-29 | US9 開發手測回饋修正：(1) DP 系統信實為 **5 支**（precheck 仍漏 `ACCOUNT_INVITE` 帳號邀請 / US4 #67）—— data-model / spec_us9 / issues.md「4 支」全數更正為 5、補 `ACCOUNT_INVITE`；(2) 範本 `VARIABLES` 加中文名稱（自描述，migration `9b309342e9f3` 更新 5 支 DP 範本，比照 US5 PARAM_NAME）；(3) 前端管道 label「站內→系統內部、兩者→系統內部+email」；`PWD_EXPIRY_REMIND` 之寄送待 US11 SCHDP001（排程未實作）|
| 2026-07-29 | US9（#92 / PR #95）已合併進 main；依增量模式補入 Issue #10（操作記錄查詢 / US10 / dp-audit）完整 body（T042~T043）：唯讀多條件查詢（操作者 / 期間起訖 / 模組 / 操作類別）+ 後端分頁時間倒序 + 明細前後值（JSON）+ CSV 匯出；**與 US5/US9 關鍵差異＝不分模組共用可見**（兩管理者皆查全部，`模組`僅為查詢條件非存取控制）；append-only、後端無刪改端點、ROW_HASH 鏈由寫入端維護（查詢頁不驗鏈）；無新表 / migration（表 + `AuditLogService` 寫入於 #0 已建）；填實 `AuditPage` stub；「僅管理者 AUDIT-002」vs 暫行案 A 之 interim 姿態列為 SA Q（傾向方案 A、gate 待 T049）；error codes 越權建議重用 `DP_AUTH_006` 或新增 `DP_AUDIT_001`；總覽 #10 主要前置補 `#0`（原僅列 #2）|
| 2026-07-29 | US10 交付前自檢（`/sti-sa-precheck dp us10`）修 2 必補一致性缺口：(1) **`RESULT`（執行結果 SUCCESS/FAIL）+ `DESCRIPTION`（事件描述）**——data-model 有欄、FR-05 明訂記錄、SRVDP003 已寫入，但 spec_us10 AC2 / wireframe 明細 modal 皆漏呈現 → spec_us10 AC1/AC2/FR-02 補為查詢條件 + 列表欄 + 明細欄，wireframe `dp-audit` 查詢列補「執行結果」下拉、列表補「結果」欄（加登入 FAIL 示例）、明細 modal 補執行結果 / 事件描述兩列；(2) **「JSONB」用語收斂**——spec_us10（AC2/FR-02）+ wireframe（內部註記 + 明細 label）之「JSONB」改「JSON 字串（`TEXT` 欄）」，對齊 data-model / spec.md / research §6。Issue #10 body 同步（T042/T043 範圍 + AC + 注意事項）|
| 2026-07-30 | Issue #10（US10 dp-audit）已開立 [#97](https://github.com/sti-fhb/EDMS/issues/97) 並**開發合併（PR [#100](https://github.com/sti-fhb/EDMS/pull/100)）**；總覽 #10 狀態更新為已合併。後端 `app/dp/audit/` 補查詢 router + CSV 匯出（無新表 / migration）；SA 裁示 Q1=A（暫行案 A、AUDIT-002 真 gate 待 T049）。**3 輪手測回饋**落地：對象 / 操作者解析為可讀名（使用者姓名→email、參數 / 範本中文、邀請經 pending 或稽核 JSON fallback）、功能顯示中文含 `DP-` 前綴、列表移除模組欄、查詢「模組」改「功能」下拉、即時篩選（防抖 + 清除篩選、無查詢鈕）、期間起訖互相約束且不超過當日、CSV 精簡為 9 欄（操作者帳號=email、對象=姓名）、`cancel_invite`/`resend_invite` 稽核補記 `user_name`（US4）；登入登出依 FR-05 保留。CSV 全量匯出加固（CWE-400）開 follow-up [#102](https://github.com/sti-fhb/EDMS/issues/102)（隨 T049）|
| 2026-07-30 | 依增量模式補入 Issue #11（排程引擎與總覽 + SCHDP001 / US11 / dp-schedule）完整 body（T044~T046）：APScheduler 單一引擎（lifespan 載入 `DP_SCHEDULE` 啟用中 job、`HANDLER_REF` 動態 import、`max_instances=1`+coalesce→SKIPPED、寫 `DP_SCHEDULE_LOG`+`LAST_RUN_*`、失敗隔離、`scheduler_leader` 單實例直跑）+ `SCHDP001`（每日：閒置 90 日禁用 + 稽核、密碼到期前 7 天寄 `PWD_EXPIRY_REMIND`）+ 唯讀總覽（無啟停 / 補跑）；**無新表 / migration**（表 + 種子〔SCHDP001 啟用、ET/DM 預留列〕+ apscheduler 依賴於 #0 已建）；**交付邊界＝引擎 + SCHDP001（DP 自持）+ 總覽**，ET/DM handler 由各模組後補（預留列停用不阻塞）；`PWD_EXPIRY_REMIND` 首落地寄送點（US9 已備範本）；授權暫行案 A（總覽越權待 T049 重用 `DP_AUTH_006`）；填實 `SchedulePage` stub |
| 2026-07-30 | US11 交付前自檢（`/sti-sa-precheck dp us11`）修 1 必補 + 3 建議：**必補**——`last_login_date` 僅登入時設、活化不設，故活化未登入帳號 `LAST_LOGIN_DATE=null`，`SCHDP001` 閒置判定對 null 未定義 → spec_us11 FR-05 / AC6 + data-model（閒置禁用規則 + 欄位說明）明訂 **null 以 `CREATED_DATE` 為閒置起算基準**；**建議**——(1) 密碼到期提醒 spec 明訂「每日跑均寄、直至變更 / 到期」（非單次）；(2) 閒置禁用稽核 `func_name=DP-USERS`、operator=SYSTEM（使 US10 dp-audit 對象顯示姓名）；(3) `DP_SCHEDULE` 異動 MVP 重啟生效、cron 熱重載留 ET/DM 落地評估。Issue #11 body 同步（AC6 + T045 範圍 + 注意事項）|
| 2026-07-31 | US11（#106）開發 + 手測回饋擴充（PR #108）：**總覽由「唯讀」改為「可編排程管理頁」**——新增 `PUT /api/dp/schedules/{job_id}` 編輯 `JOB_NAME` / `CRON_EXPR` / `IS_ENABLED`（cron 驗證 + 稽核 `func_name=DP-SCHEDULE` + `apply_job_change` 即時 reschedule/add/remove 生效，暴露 scheduler 單例）+ 清單加**下次執行時間**（cron 計算）；前端欄位「啟停→狀態」、移除「結果」欄、加編輯 Dialog（JOB_ID 唯讀）；error codes `DP_SCHED_001/002`；US10 dp-audit `func_label` 加 `DP-SCHEDULE→DP-排程管理`。**仍不提供手動補跑**（冪等性因 job 而異，如到期提醒重跑會重複寄信）、**`HANDLER_REF`/`MODULE` 永不可經 UI 改**（RCE 防護 + `_resolve_handler` 白名單）。spec_us11 FR-06/AC7 + spec.md §排程引擎同步為「可編」。另修 `scheduler_leader.py` 前置敘述（#0 未實際建、本 issue 自建最小版）。**登入漸層背景統一**至信中連結落點頁（`ResetPasswordPage` / `VerifyEmailPage` / `ActivateAccountPage` / `VerifyEmailChangePage`，抽 `AUTH_BG_GRADIENT` 共用常數）。Code+Security review 全修（HIGH: shutdown 真等待；SECURITY: HANDLER_REF 白名單）|
| 2026-08-03 | Issue #11（US11 dp-schedule）已**合併（PR [#108](https://github.com/sti-fhb/EDMS/pull/108) squash）**、close（#106）；總覽 #11 狀態更新為已合併。手測 E2E 驗證到期帳號正常發信（`PWD_EXPIRY_REMIND`）。DP 模組 US 全數交付，僅餘 Issue #12（整合測試 + 安全 + 收尾）|
| 2026-08-03 | 補入 Issue #12 完整 body（收尾）。**範圍裁示 A**：因 `backend/app/{et,dm}/` 尚未存在、跨模組 checker 生產環境未註冊（fail-closed），將 tasks.md 原 T049 之「真授權閘掛 router」與「T047/T051 之 ET/DM 回歸」**排除、另立 follow-up**（現在掛 `require_module_admin` 會因無 checker → 全端點 403 鎖死後台）。#12 交付＝跨 US 端到端整合測試（T047/T048/T050/T051/T053/T054，對 SC-001~011）+ **淨新增稽核 ROW_HASH `verify_chain` 驗鏈工具 + `python -m` 入口**（目前僅寫入端建鏈、無驗證端）+ 安全姿態文件化（DB append-only GRANT 標為部署層）。**不新增業務功能 / 無 migration**。總覽 #12 涵蓋 Tasks 改列 T047~T048, T050~T054、狀態 📝 body 已補（待開立）。盤點依據：既有實作已就緒可測者＝T048 鎖定解鎖 / T053 限流·token·防列舉 / T047 換發（無 refresh token）；淨新增＝T052 驗鏈工具 + 跨 US e2e 測試 |
| 2026-08-03 | Issue #12 已開立為 GitHub [#114](https://github.com/sti-fhb/EDMS/issues/114)；T049 遞延項另立 follow-up [#113](https://github.com/sti-fhb/EDMS/issues/113)（真授權閘掛 router + ET/DM 回歸，⏸️ 待 ET/DM 落地）。回填總覽表 GitHub # 欄與 body header；總覽新增 #12-F 列追蹤 follow-up |
| 2026-08-05 | Issue #12（#114）已**合併（PR [#116](https://github.com/sti-fhb/EDMS/pull/116) squash）**、close（#114）；總覽 #12 狀態更新為已合併。交付＝稽核 ROW_HASH `verify_chain` 驗鏈工具（`app/dp/audit/verify.py` + `python -m` CLI，退出碼 0/1/2）+ 8 檔跨 US 端到端整合測試（T047/T048/T050/T051/T053/T054，對 SC-001~011，31 測試）+ `docs/ref` 稽核鏈完整性文件（DB append-only GRANT 部署層 + 工具說明）。**架構差異**：AC 原文 `AuditLogService.verify_chain` → 實作為獨立唯讀模組函式（與寫入服務分離、共用 `_compute_row_hash` canonical）。Code review 1M/2L 全修（stream cursor close / CLI exit-code 2 區隔執行錯誤 / `_amain` 測試）；security APPROVE。手測真實 dev DB 驗鏈完好→竄改偵測（LOG_ID 精準）→還原全通過。**DP 模組 US + 收尾全數交付**，僅餘 follow-up #113（待 ET/DM 落地）|
