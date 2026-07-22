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
| 6 | 系統參數與清單維護（dp-params）| US5 / UCDP006 | P1-核心 | T033 ~ T034（2 任務）| #2 | — | 待補 |
| 7 | 權限管理（dp-roles）| US7 / UCDP010 | P1-核心 | T035 ~ T036（2 任務）| #2（模組 service 以 stub）| — | 待補 |
| 8 | 個人資料維護 + 強制變更密碼（dp-profile）| US8 / UCDP004 | P2-延伸 | T037 ~ T039（3 任務）| #1, #2 | — | 待補 |
| 9 | 通知範本維護（dp-templates）| US9 / UCDP011 | P2-延伸 | T040 ~ T041（2 任務）| #1, #2 | — | 待補 |
| 10 | 操作記錄查詢（dp-audit）| US10 / UCDP007 | P2-延伸 | T042 ~ T043（2 任務）| #2 | — | 待補 |
| 11 | 排程引擎與總覽 + SCHDP001（dp-schedule）| US11 / UCDP008 | P2-延伸 | T044 ~ T046（3 任務）| #0, #1 | — | 待補 |
| 12 | 整合測試 + 安全 + 收尾 | — | 收尾 | T047 ~ T054（8 任務）| 全部 | — | 待補 |
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

- [ ] `uv run alembic upgrade head` 成功建立 10 張 DP 表；標準欄位齊備（CREATED/UPDATED_USER/DATE、RES_ID、DELETED，**無 SITE 欄位**）；**不存在** `DP_SESSION` / `DP_ROLE` / `DP_MENU` 表
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

**對應規格**：[spec_us1.md](spec_us1.md)（US1 / UCDP001，FR-DP-US1-01~11、AC 1~12、DP-MSG-LOGIN-001~008）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §1（is_module_admin）/ §4（has_any_role）；[research.md](research.md) §2（短 TTL + 活動換發）/ §3（每請求查 DP_USER）/ §12（redirect + 入口頁）；[data-model.md](data-model.md)（`DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁 + 模組入口頁）
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
- **T024 登入頁**：帳密欄（密碼遮蔽）、錯誤訊息（DP-MSG-LOGIN-001~008）、redirect 白名單返回原目標頁（通知信連結 / 書籤 / 逾時重登）、閒置換發計時器（到期前有操作即 renew）、掛速率限制回應（429 → LOGIN-007）；對應 FR-01/07/09
- **T025 模組入口頁**：ET 入口恆顯、**DM 卡雙狀態**（無 DM 角色呈「未開通」鎖定卡 + 引導文字 DP-MSG-LOGIN-008、點擊不進入）、個資恆顯、**不顯 DP 後台入口**、首次登入歡迎橫幅一次（已顯示旗標儲存位置實作定）；對應 FR-07、research §12

**測試**：
- 後端：登入成功 / 帳號不存在 / 密碼錯誤 / 失敗計數→鎖定 / 鎖定逾時解鎖 / 停用拒絕 / 強制變更旗標 / 換發沿用 auth_time / 逾 8h 拒絕 / 登出稽核；速率限制 429；角色摘要端點（stub）
- 前端：登入流程（MSW）、錯誤訊息呈現、redirect 返回、入口頁 DM 卡雙狀態

### 驗收條件

- [ ] 正確帳密 → 核發 JWT（含 `auth_time`、TTL 15 分）、重設失敗計數、更新 `LAST_LOGIN`、寫 LOGIN 稽核
- [ ] 帳號不存在 / 密碼錯誤 → 分別回對應訊息（DP-MSG-LOGIN-001 / 002）；密碼錯誤累計失敗計數
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

**對應規格**：[spec_us2.md](spec_us2.md)（US2 / UCDP002，FR-DP-US2-01~06、DP-MSG-REGISTER-001~004）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §2（`grant_default_student_role`）；[data-model.md](data-model.md)（`DP_USER` / `DP_PWD_HIST`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁・註冊頁籤）
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
- **T027 前端註冊頁籤**：登入頁「註冊」頁籤欄位（Email 必填 + 格式、姓名必填、密碼 / 確認密碼遮蔽），Zod 前端驗證 + 錯誤訊息（DP-MSG-REGISTER-001~004），成功跳回登入頁預填 Email；對應 FR-01/04

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
- 稽核經 `SRVDP003.log_action`（`res_id` 必填、含來源 IP，走 request_context）。

### 相關文件

- [spec_us2.md](spec_us2.md)、[spec.md](spec.md) Clarifications 釐清第 3 輪、[data-model.md](data-model.md)（`DP_USER` / `DP_PWD_HIST`）、[tasks.md](tasks.md) Phase 5（T026~T027）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §2（`grant_default_student_role`）
- 需求：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP002

**Labels**：`P1-核心`, `DP-平台`, `US2`

---

## Issue #4：[P1-核心] DP — 忘記密碼

**對應規格**：[spec_us3.md](spec_us3.md)（US3 / UCDP003，FR-DP-US3-01~08、DP-MSG-FORGOT-001~006）；[contracts/platform-services.md](contracts/platform-services.md)（SRVDP002 發信）；[research.md](research.md) §5（token 明文入信 / SHA-256 入庫）；[data-model.md](data-model.md)（`DP_PWD_RESET` / `DP_PWD_HIST` / `DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（登入頁・忘記密碼 + 重設密碼頁）
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
- **T028 申請端點**：輸入 Email → **防列舉統一回覆**（DP-MSG-FORGOT-001，不論存在與否；帳號不存在不產 token / 不寄信）；存在帳號產生一次性時效 token（明文入信、SHA-256 入 `DP_PWD_RESET`，TOKEN_TYPE=`PWD_RESET`，EXPIRES_DATE=now+`RESET_TOKEN_TTL_MIN`）、**同帳號同型舊 token 立即作廢**、經 `SRVDP002` 寄 `PWD_RESET` 範本；掛速率限制（IP + 帳號，先限流後查存在性）；對應 FR-01~04/08
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

**對應規格**：[spec_us4.md](spec_us4.md)（US4 / UCDP005，FR-DP-US4-01~09、DP-MSG-USERS-001~005）；[contracts/module-callbacks.md](contracts/module-callbacks.md) §1（`is_module_admin`）/ §2（`grant_default_student_role`）；[data-model.md](data-model.md)（`DP_USER`）；[wireframes/dp/index.html](../../wireframes/dp/index.html)（`dp-users`）
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
- 稽核經 `SRVDP003.log_action`（`res_id`=USER_ID 必填、含 before/after value、來源 IP）；密碼不入 log。
- 角色指派 MUST NOT 於本頁（US7）；目錄 `dp/users`（CRUD）與 `dp/user`（認證）分開（sti-api-routes）。

### 相關文件

- [spec_us4.md](spec_us4.md)、[spec.md](spec.md) §模組過濾與共用項 / §帳號鎖定與閒置控管、[data-model.md](data-model.md)（`DP_USER`）、[tasks.md](tasks.md) Phase 7（T030~T032）
- [contracts/module-callbacks.md](contracts/module-callbacks.md) §1 / §2
- 需求：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理 / §帳號鎖定；使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP005

**Labels**：`P1-核心`, `DP-平台`, `US4`

---

## Issue #6 ~ #12：待補（增量模式）

依總覽表順序，於前一張 Issue 實作驗證 OK 後逐張補入完整 body（格式同 Issue #0 ~ #5，對齊 `sti-issue-create` canonical 模板）。

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
