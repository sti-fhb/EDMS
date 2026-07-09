# 實作計畫：平台模組（Platform）

**分支**: `main` | **日期**: 2026-07-09 | **規格**: [spec.md](spec.md)
**輸入**: 依據 [spec.md](spec.md) 與 spec_us1~11.md 產出實作計畫；對齊 [_refs/09-平台模組.md](../../_refs/09-平台模組.md)、[requirements/RQDP.md](../../requirements/RQDP.md)、[use-cases/dp/usecases.md](../../use-cases/dp/usecases.md)、[wireframes/dp/index.html](../../wireframes/dp/index.html) 與 [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md)

---

## 摘要

平台模組（DP）為 EDMS 之**共用基礎層 + 統一管理後台**：帳號與認證（簡單 JWT、短 TTL + 活動換發）、忘記密碼、個人資料、使用者管理、帳號鎖定、系統參數與清單（`DP_PARAM`，前綴分模組）、通知範本與發信引擎（`DP_NOTIFY_TEMPLATE` + outbox `DP_EMAIL_LOG`）、排程引擎（`DP_SCHEDULE` + APScheduler）、權限管理畫面（資料寫模組表）、稽核（`DP_AUDIT_LOG`）。共 10 張平台表、11 個 User Story（UCDP001–011）、1 支平台自身排程 `SCHDP001`。

DP 是 ET / DM 的**開發前置**：兩業務模組依賴 DP 之認證、參數服務（SRVDP001）、發信服務（SRVDP002）、稽核服務（SRVDP003）與排程引擎；DP 反向依賴模組之管理者判定、角色指派寫入與 job handler（[contracts/module-callbacks.md](contracts/module-callbacks.md)）。

> **起手包基礎**：後端 core / Alembic / 測試骨架與認證模組自 TBMS 遷移（EDMS-MIGRATION §3 / §4），惟遷移清單（2026-07-03）早於 spec 定案（2026-07-06 / 08），**須再裁剪** Refresh Token（`DP_SESSION`）、全域 RBAC（roles / menus）、帳號開通信、Email 加密——差異明細見 [research.md §1](research.md)。

---

## 技術背景

**介接方式**: DP 後端對前端提供 RESTful API（DP 後台 + 登入 / 個資頁）；對 ET / DM 提供內部服務 SRVDP001–003；反向呼叫模組 service（管理者判定 / 角色指派 / job handler）；對外經 SMTP 寄信（全 EDMS 唯一出口）
**前端**: React 19 + MUI 7、React Router v7、TanStack Query v5；登入頁（含註冊 / 忘記密碼）、模組入口頁、DP 後台 6 畫面（使用者 / 參數清單 / 權限 / 範本 / 稽核 / 排程總覽）+ 個人資料頁；後台清單一律後端分頁（稽核量大），管理類小表可用 `usePagination`
**後端**: FastAPI 0.115+、SQLAlchemy 2（async）+ Alembic、APScheduler；分層與共用模組依 `sti-backend-modules`（BaseModel / paginate / AppError）
**資料庫**: PostgreSQL 17（命名 / 型別遵循 CLAUDE.md；不使用 JSONB——稽核前後值以 TEXT 存 JSON，research §6）
**認證**: 自建簡單 JWT——token TTL＝閒置逾時 15 分鐘、活動靜默換發、單日上限 8 小時（`auth_time` claim，research §2）；無 MFA / Refresh Token / 伺服器端 session；密碼 bcrypt；每請求檢核帳號狀態（research §3）
**保留**: 稽核日誌 append-only ≥ 1 年（鏈式雜湊）；密碼歷程前 N 次；outbox / 排程歷程不刪除
**專案類型**: Web 應用程式（管理後台）+ 平台內部服務 + 背景引擎（發信 worker、排程）
**模組代碼**: DP（平台）

---

## Constitution 檢查

Constitution 尚未設定（`.specify/memory/constitution.md` 仍為模板），無違規項目。

---

## 文件結構

### 設計文件（本功能）

```text
specs/dp/
├── spec.md              # 模組總覽（US 索引、Clarifications×5 session、訊息類型、Key Entities、共用規則、Edge Cases、SC）
├── spec_us1.md          # US1 使用者登入 / 登出（UCDP001）
├── spec_us2.md          # US2 使用者自助註冊（UCDP002）
├── spec_us3.md          # US3 忘記密碼（UCDP003）
├── spec_us4.md          # US4 使用者管理（UCDP005）
├── spec_us5.md          # US5 系統參數與清單維護（UCDP006）
├── spec_us6.md          # US6 通知發送服務（UCDP009）
├── spec_us7.md          # US7 權限管理（UCDP010）
├── spec_us8.md          # US8 個人資料維護（UCDP004）
├── spec_us9.md          # US9 通知範本維護（UCDP011）
├── spec_us10.md         # US10 操作記錄查詢（UCDP007）
├── spec_us11.md         # US11 排程作業執行與總覽（UCDP008）
├── plan.md              # 本文件
├── research.md          # Phase 0 研究（12 項決策，含遷移起手包裁剪）
├── data-model.md        # Phase 1 資料模型（ERD + DD，10 張表 + 種子）
├── contracts/
│   ├── platform-services.md    # SRVDP001–003（DP 提供）
│   ├── module-callbacks.md     # 模組回呼介面（ET / DM 提供、DP 呼叫）
│   └── ext-dp-email-server.md  # SMTP 外部介接（全 EDMS 唯一出口）
├── checklists/
│   └── requirements.md  # 規格品質檢核（待 /speckit.checklist）
└── tasks.md             # Phase 2 開發任務清單（54 任務、Phase 1–14）
```

### 相關目錄

```text
use-cases/dp/usecases.md   # 使用案例（UCDP001~011 + 章節對照）
wireframes/dp/index.html   # 畫面原型（登入 overlay + dp-users / dp-params / dp-templates / dp-roles / dp-audit / dp-schedule / dp-profile）
requirements/RQDP.md       # 需求清單（全分析資料、無 RFP RQ 編號）
_refs/09-平台模組.md       # 分析資料（source of truth；2026-07-06 成立 + 2026-07-08 集中化決策）
EDMS-MIGRATION.md          # TBMS 遷移起手包 checklist（repo 根目錄）
```

---

## 跨模組依賴摘要

| 方向 | 介接對象 | 編碼 | 介接方式 | 說明 | 契約位置 |
|------|----------|------|----------|------|---------|
| DP ↔ ET / DM | 兩業務模組 | — | 共用 `DP_USER`（SSO）| USER_ID / 帳號 / 密碼雜湊 / 姓名 / 狀態；模組以 USER_ID 為 FK | [data-model.md](data-model.md) |
| ET / DM → DP | 參數唯讀查詢 | **SRVDP001** | 內部服務 | 模組讀自己前綴之參數 / 清單定義（不快取、即時生效）| [contracts/platform-services.md](contracts/platform-services.md) |
| ET / DM → DP | 發信服務 | **SRVDP002** | 內部服務 | 傳 template_code 渲染 + outbox 非同步寄送 | 同上 |
| ET / DM → DP | 稽核寫入 | **SRVDP003** | 內部服務 | 模組資安事件統一寫 `DP_AUDIT_LOG` | 同上 |
| DP → ET | 預設角色授予 | 待編（SRVET0xx）| 內部服務 | 帳號建立時授予學員（US2 / US4）| [contracts/module-callbacks.md](contracts/module-callbacks.md) |
| DP → ET / DM | 管理者判定 / 角色指派 / 角色摘要 | 待編 | 內部服務 | `is_module_admin` / `assign_roles_*` / `has_any_role`（US1 / US5 / US7 / US9 / US10）| 同上 |
| DP → ET / DM job | 排程引擎執行 | SCHET001 / 002、SCHDM001 | handler 反向 import | `DP_SCHEDULE` 註冊、引擎觸發、`DP_SCHEDULE_LOG` 記錄 | 同上 |
| DP 自身 | 平台排程 | **SCHDP001** | 每日 | 閒置帳號禁用 + 密碼到期提醒 | [spec_us11.md](spec_us11.md) |
| DP → eMail Server | 外部郵件系統 | — | SMTP | 全 EDMS 所有信件之唯一出口 | [contracts/ext-dp-email-server.md](contracts/ext-dp-email-server.md) |

> **開發時序含義**：ET / DM 之參數 / 發信 / 稽核 / 排程功能以 DP 服務為前置；反之 DP 的 US2 / US7 完整驗收需模組 service 就緒——開發期以 stub 介面（contracts 簽章）先行、模組實作跟進。

---

## 待定案技術決策（本計畫定案，詳見 [research.md](research.md)）

| 議題 | 決策 |
|------|------|
| 遷移起手包裁剪 | 砍 `DP_SESSION` / RBAC roles+menus / 帳號開通信 / EMAIL 加密；`refresh_token` 改 `renew`（research §1）|
| 閒置登出 | 短 TTL（15 分）+ `auth_time` claim + 換發端點（上限 8 小時），完全無狀態（research §2）|
| 停用 / 鎖定即時失效 | middleware 每請求查 `DP_USER` 狀態，不快取（research §3）|
| 角色判定來源 | JWT 不含角色；每請求呼叫模組 `is_module_admin`（research §4）|
| 一次性 token | `DP_PWD_RESET` 存 SHA-256 雜湊；TOKEN_TYPE＝PWD_RESET + EMAIL_CHANGE（research §5）|
| 稽核落地 | TEXT 存 JSON（非 JSONB）+ DB 帳號僅 INSERT/SELECT + 鏈式 ROW_HASH（research §6）|
| DP_PARAM 模型 | M/D 二層、前綴歸屬、`DETAIL_LOCK`、唯讀服務不快取（research §7）|
| 發信引擎 | outbox + lifespan 常駐 worker、渲染快照、逐收件人一列（research §8）|
| 排程引擎 | APScheduler + DB 註冊表 + `max_instances=1` 跳過重疊 + leader（research §9）|
| 速率限制 | 行程內滑動視窗（IP + 帳號），登入 / 忘記密碼 / 密碼變更端點（research §10）|
| 密碼策略 | bcrypt；策略值全讀 `PWD_POLICY` 參數；特權門檻於變更當下判定（research §11）|
| 登入導向 | redirect 白名單 + 模組入口頁角色摘要端點（research §12）|

---

## 功能分群與開發順序

### 第零階段（Foundation — 起手包 + 骨架，先於一切）

| 項目 | 內容 |
|------|------|
| 後端骨架 | EDMS-MIGRATION §3：pyproject / core（db、base_model、pagination、exceptions、config）/ Alembic（versions 清空重建）/ 測試 DB 骨架 |
| DP schema | 10 張表 migration + 種子（平台級參數、DP 系統信 3 支、排程 job 4 筆；模組級參數種子隨各模組補）|
| 稽核服務 | SRVDP003 `log_action`（鏈式雜湊）——所有後續 US 依賴 |
| 參數服務 | SRVDP001 `get_param_value / get_param_list`——認證與各 US 讀參數依賴 |
| 前端骨架 | Vite + React 19 + MUI 7 + Router v7 + TanStack Query v5；DP 後台 layout（sidebar 對齊 wireframe）|

### 第一階段（P1 — 認證鏈與後台核心）

| 群組 | User Story | 對應畫面 | 說明 / 依賴 |
|------|------------|---------|------------|
| 發信引擎 | US6 | —（服務）| SRVDP002 + outbox + worker；US3 / US8 / SCHDP001 前置 |
| 登入 / 登出 | US1 | 登入頁 + 模組入口頁 | JWT 核發 / 換發 / 鎖定 / 導向 / 速率限制；起手包 `auth.py` 改造 |
| 自助註冊 | US2 | 登入頁註冊籤 | 建帳號 + ET 學員授予（ET service 未就緒前以 stub）|
| 忘記密碼 | US3 | 登入頁忘記密碼 | token + 防列舉；依賴 US6 |
| 使用者管理 | US4 | dp-users | 代建（初始密碼）/ 停用 / 啟用 / 解鎖 |
| 參數與清單維護 | US5 | dp-params | 維護 UI + 模組過濾（讀取服務已於 Foundation 就緒）|
| 權限管理 | US7 | dp-roles | 依賴 ET / DM `assign_roles_*`（contracts 簽章 stub 先行）|

### 第二階段（P2 — 自助個資與維運查詢）

| 群組 | User Story | 對應畫面 | 說明 / 依賴 |
|------|------------|---------|------------|
| 個人資料維護 | US8 | dp-profile | 姓名 / Email 驗證切換 / 密碼變更 + 強制變更頁（US1 導入點）|
| 通知範本維護 | US9 | dp-templates | MODULE 過濾 + 樂觀鎖 + 系統信保護 |
| 稽核查詢 | US10 | dp-audit | 多條件 + 明細 + CSV（寫入已於 Foundation 起可用）|
| 排程引擎與總覽 | US11 | dp-schedule | APScheduler + `SCHDP001` + 唯讀總覽；ET / DM job 於各模組開發時掛入 |

> 順序原則：**Foundation → US6 → US1–US3（認證鏈）→ US4 / US5 → US7 → P2**。US6 先於 US3（重設信依賴）；US5 維護 UI 可與認證鏈並行（讀取服務已就緒）；US11 排最後但 `SCHDP001` 之閒置禁用不阻塞 US1（上線前補齊即可）。

---

## 複雜度追蹤

> 無 Constitution 違規需要正當化說明。

| 設計決策 | 理由 | 備註 |
|----------|------|------|
| 無 Refresh Token，改「短 TTL + 活動換發 + auth_time 上限」| 滿足閒置 ≤ 15 分 + 單日 8 小時，且維持完全無狀態（無 session 表）| 與遷移起手包差異最大處；`DP_SESSION` 不建（research §1 / §2）|
| 每請求查 `DP_USER` 狀態 + 模組 `is_module_admin` | 停用即時失效（SC-006）與角色即時生效（US7）優先於單鍵查詢成本 | EDMS 單一組織規模，無快取必要（research §3 / §4）|
| 稽核前後值 TEXT 存 JSON | 型別規範限用集合不含 JSONB（DM 同裁定）；US10 僅展示不做 JSON 條件查詢 | _refs「JSONB」字樣以 research §6 為準 |
| 稽核鏈式 ROW_HASH + DB 帳號僅 INSERT/SELECT | 法規「不可竄改、以雜湊確保完整性」之最小落地 | 竄改任一列即斷鏈可稽；不引入 WORM / trigger |
| 發信 worker 為常駐 asyncio task（非排程 job）| 秒級輪詢語意與 cron 排程不合；重試 / 速率屬佇列消費行為 | 不入 `DP_SCHEDULE`；Celery / MQ 屬過度設計（research §8）|
| 權限管理「畫面在 DP、資料與判定在模組」| 單一後台 UX 與模組自治並存（2026-07-08 決策）| DP 僅轉呼叫 + 呈現模組錯誤；自我保護判定不重複實作於 DP |
| `DP_PARAM` 唯讀服務不快取 | 「儲存即生效」證據鏈最短；參數讀取頻率低 | 若日後量測有熱點再演進短 TTL 快取（research §7）|
| 速率限制行程內實作 | 預設單一實例；不為未發生的多實例引入 Redis | 多實例部署時再演進（research §10）|
