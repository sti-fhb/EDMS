# 開發 Issues 清單：文件管理模組（Document Management）

**模組代碼**: DM | **日期**: 2026-08-05
**來源**: [plan.md](plan.md) §功能分群與開發順序 | [tasks.md](tasks.md) | [spec.md](spec.md) | [data-model.md](data-model.md)

> 每張 Issue 為一個**功能之垂直切割**（DB + 後端 + UI + 驗收條件），可獨立開發、測試與交付。Issue #0 為基礎建設，其餘依 plan.md 之 P1 / P2 / P3 階段排序。
>
> **增量模式**：採「產一張 → 實作 → 驗證 OK → 再補下一張」流程；目前僅 Issue #0 完整撰寫，#1 起之完整 body 待 #0 實作驗證後逐張補入（總覽表先列全貌）。
>
> **平台對齊（DP，2026-07-08 集中化）**：DM 與平台模組 DP **共用帳號與認證**（`DP_USER`、SSO、簡單 JWT），並將**登入 / 註冊 / 忘記密碼 / 個資維護**（UCDP001–004）、**系統參數 / 通知範本 / 排程 / 發信**之維護 UI 與基礎設施集中於平台 DP。DM 專注**文件管理業務**；US2 登入不開獨立 issue（DM 端僅存取閘、併入 #0），US1 系統設定為 DM 之**轉接層模組端 + 業務規則 + 種子**（維護 UI 在 DP 後台）。平台 DP 模組（#0~#12）已全數交付合併，SRVDP001（參數唯讀）/ SRVDP002（發信）/ SRVDP003（稽核）/ dp-roles（權限轉接層）/ DP_SCHEDULE（排程引擎）均就緒可供 DM 引用。
>
> **Issue 開立規則**：
> 1. 標題格式：`[{階段}] {模組代碼} — {功能名稱}`（如 `[Foundation] DM — 專案建置與文件管理基礎建設`）
> 2. Labels：`{階段標籤}`（Foundation 用 `priority:P0`；其餘 `P1-核心` / `P2-延伸` / `收尾`）+ `DM-文件管理`（**新 label，開立前先 `gh label list` 確認 / 依 `sti-label-rules` 建立**）+ `{US 標籤}`（無對應 US 者免）
> 3. **依序開立**，於 body「依賴」段標註相依之 **GitHub Issue 編號**（模組內序號 #0–#13 僅為規劃用，實際編號以 GitHub 為準、回填總覽表）

---

## Issue 總覽

| # | 標題 | 對應 | 階段 | 涵蓋 Tasks | 主要前置 | GitHub # | 狀態 |
|---|------|------|------|-----------|---------|----------|------|
| 0 | 專案建置與文件管理基礎建設 | — | Setup + Foundational | T001 ~ T020a（含 13 表 migration + 業務種子 + SSO 存取閘 / 授權 / 檔案 / DOC_ID / 通知接線 / 狀態機 / 可見性）| 平台 DP #0~#12（已交付）| [#127](https://github.com/sti-fhb/EDMS/issues/127) | 🚀 已開立 [#127](https://github.com/sti-fhb/EDMS/issues/127) |
| 1 | 系統設定（轉接層模組端 + 業務規則 + 種子驗證）| US1 / UCDM11 | P1-核心 | T024 ~ T027b | #0；DP dp-params / dp-roles / dp-templates | [#133](https://github.com/sti-fhb/EDMS/issues/133) | 🚀 已開立 [#133](https://github.com/sti-fhb/EDMS/issues/133) |
| 2 | 文件庫與檢索 | US3 / UCDM03 | P1-核心 | T028 ~ T030 | #0, #4 | — | 待補 |
| 3 | 文件詳細頁瀏覽 | US4 / UCDM04 | P1-核心 | T031 ~ T034 | #0 | — | 待補 |
| 4 | 文件新增與編輯 | US5 / UCDM06 | P1-核心 | T035 ~ T039 | #0 | — | 待補 |
| 5 | 簽核處理 | US6 / UCDM07 | P1-核心 | T040 ~ T044 | #4 | — | 待補 |
| 6 | 系統儀表板 | US7 / UCDM02 | P2-延伸 | T045 ~ T046 | #4, #5 | — | 待補 |
| 7 | 文件廢止申請 | US8 / UCDM05 | P2-延伸 | T047 ~ T048 | #3, #5 | — | 待補 |
| 8 | 個人專區（草稿匣 / 我的文件動態 / 撤回送審）| US9 / UCDM09 | P2-延伸 | T050 ~ T052 | #4, #5 | — | 待補 |
| 9 | 已廢止文件查詢 | US10 / UCDM08 | P2-延伸 | T053 ~ T054 | #3, #5 | — | 待補 |
| 10 | 文件變更歷程查詢 | US11 / UCDM10 | P3 | T055 ~ T056 | #5 | — | 待補 |
| 11 | 跨模組教材引用（DM ↔ ET）| US12 / UCDM12 | P3 | T057 ~ T059 | #5；ET 引用端 | — | 待補 |
| 12 | 閱讀統計與 KPI + 排程 SCHDM001 | US13 / UCDM13 | P2-延伸 | T059a ~ T059c | #3；DP 排程引擎 | — | 待補 |
| 13 | 整合測試 + 安全 + 收尾 | — | 收尾 | T060 ~ T067 | 全部 | — | 待補 |
| — | ~~登入 / 註冊 / 忘記密碼~~ | US2 / UCDM01 | — | —（T014）| — | — | **不開獨立 issue**：登入 / 註冊 / 忘記密碼由平台 DP 提供（UCDP001–003）；DM 端僅存取閘（無 DM 角色者拒絕進入），併入 #0（T014）|

> **US2 說明**：DM 完全不實作登入 / 註冊 / 忘記密碼（由平台 DP 提供、單一登入共用 `DP_USER`）。DM 端唯一之認證相關工作為**存取閘**（經 DP 登入後、無任何 DM 角色者拒絕進入 DM，含直呼 API），屬基礎建設、併入 Issue #0（T014）。故 US2 不開獨立功能 issue。

---

## Issue #0：[Foundation] DM — 專案建置與文件管理基礎建設（GitHub [#127](https://github.com/sti-fhb/EDMS/issues/127)）

**對應規格**：[plan.md](plan.md) §技術背景、§開發階段；[data-model.md](data-model.md)（13 張 DM 業務表 + 與 ET 共用 `DP_USER`）；[research.md](research.md) §1–§10；[contracts/document-service.md](contracts/document-service.md)（SRVDM001 / 002，US12 用）；[spec_us2.md](spec_us2.md)（存取閘）
**階段**：Setup + Foundational（為 DM 所有 Issue 之前置）
**前置條件**：
- **平台模組 DP（#0~#12）已交付合併**：`DP_USER`（共用帳號）、`DP_PARAM_M/D`（前綴 `DM_` 之 DM 參數）、`DP_NOTIFY_TEMPLATE`（`MODULE=DM`）、outbox `DP_EMAIL_LOG`、`DP_SCHEDULE` + `DP_SCHEDULE_LOG`；SRVDP001（參數唯讀）/ SRVDP002（發信）/ SRVDP003（稽核）/ dp-roles（權限轉接層）就緒可引用
- 與 **ET 模組協調** `DP_USER` schema（SSO 共用，USER_ID 為穩定識別碼）
- `backend/.env`、`frontend/.env` 依 `.env.example` 建立；PostgreSQL 17 已建置

### 任務說明

建立 DM 模組後端 / 前端骨架，完成 **13 張 DM 業務表** migration 與 **DM 業務種子**，並實作 DM 共用元件：**SSO 認證接入 + 存取閘**（重用 DP 登入 JWT、無 DM 角色者拒絕進入）、角色授權工具、檔案儲存服務、DOC_ID 產生器、通知服務接線（呼叫平台 SRVDP002）、送審週期 / 狀態機服務、受控資料維護共用（catalog）、標籤式可見性判定。本 Issue 完成後，各 US 功能 issue 即可基於這些共用件開發。

> ℹ️ **後端為主之基礎建設 issue**（migration + 共用服務 / middleware / util）；前端僅建 DM 模組殼與路由骨架、各 US 畫面於對應 issue 填實。**無新業務畫面**。

> ⚠️ **集中化裁剪（2026-07-08，最易踩雷處）**：DM **不建** `DM_PARAM` / `DM_NOTIFY_TEMPLATE` / `DM_NOTIFY_QUEUE` migration（tasks T012 / T012a / T018a 已廢除）——參數存平台 `DP_PARAM`（前綴 `DM_`）、通知範本存 `DP_NOTIFY_TEMPLATE`（`MODULE=DM`）、非同步寄送用平台 outbox `DP_EMAIL_LOG`。標準欄位**省略 SITE / HOSPITAL**（對齊平台 DP，research §1）。

### 範圍

**後端 — 專案結構（T001）**：建立 `app/dm/` 目錄與子模組（依領域組織：各功能自含 router / service / repository / schemas / models）。

**後端 — 13 張 DM 業務表 Migration（T002~T011，各表可平行）**：
- **共用帳號協調**（T002）：`DP_USER`（與 ET 共用、由平台 DP 定義；DM 以 `USER_ID` FK 引用，不自建帳號表）
- **權限 / 標籤**（T003~T006a）：`DM_USER_ROLE`（USER×ROLE_CODE 唯一）+ `DM_USER_ROLE_LOG`（append-only 角色異動）、`DM_CATEGORY`（CATEGORY_CODE PK、IS_BUILTIN、IS_ENABLED）、`DM_FUNC`（FUNC_CODE PK）、`DM_TAG_GROUP`（GROUP_TYPE AUDIENCE / RETRIEVAL）+ `DM_TAG`、`DM_USER_TAG`（閱覽者可見對象授權，TAG 限 AUDIENCE 組）
- **文件核心**（T007~T009b）：`DM_DOCUMENT`（DOC_ID PK、CATEGORY / FUNC / CURRENT_VERSION FK、STATUS + **部分唯一索引**〔FUNC_CODE where CATEGORY='MANUAL' AND STATUS='PUBLISHED'〕）、`DM_DOC_VERSION`（VERSION_ID PK、VERSION_NO、CHANGE_SUMMARY、FILE_*、STATUS、APPROVER、PUBLISHED_DATE）、`DM_DOC_TAG`（DOC×TAG）、`DM_DOC_READ`（append-only 閱讀紀錄、唯一約束 DOC×VERSION×CREATED_USER）
- **簽核 / 歷程**（T010~T011）：`DM_REVIEW`（送審週期：REVIEW_TYPE / ASSIGNED_REVIEWER / STATUS / REASON / 廢止附件 OBSOLETE_FILE_*）、`DM_CHANGE_LOG`（append-only 公開變更歷程）

**後端 — DM 業務種子（T013）**：4 內建分類（SOP / MANUAL / TRAINING / OTHER + 分類碼）、4 標籤組（AUDIENCE〔權限〕/ MODULE / NATURE / LEGAL〔檢索〕）、可見對象預設值（全體 / 護理師 / 軍人 / 醫檢師 / 行政人員）。
> ⚠️ **通知範本 / 參數種子為跨模組協調項**：DM 9 通知範本（`MODULE=DM`）與 DM 參數（`DP_PARAM` 前綴 `DM_`：`DM_REMIND_THRESHOLD` / `DM_FILE_MAX_MB` / `DM_FILE_TYPES` / `DM_WEEKLY_SCHED_DAY_TIME`）之種子寫入**平台 DP 表**——由 DM 提供種子內容、寫入 `DP_NOTIFY_TEMPLATE` / `DP_PARAM`；**精確落點（DM migration 寫 DP 表 vs DP seed 承載）於 `/sti-plan` 盤點時與 SA 確認**。

**後端 — 共用元件（T014~T020a，多可平行）**：
- **T014 SSO 認證接入 + DM 存取閘** `dm/middleware/auth`：重用平台 DP 登入 JWT（共用 `DP_USER`）、未登入擋下、**無任何 DM 角色者拒絕進入**（含直呼 API）；對應 spec_us2 FR-001
- **T015 角色授權工具** `dm/util/authz`：4 角色（DM_ADMIN / EDITOR / REVIEWER / VIEWER）複選聯集判定 + 「指定審核者排除本人」+ 「管理者自我保護」共用檢核
- **T016 檔案儲存服務** `dm/service/file_store`：上傳至檔案系統 / DB 存 metadata、單檔上限讀 `DP_PARAM.DM_FILE_MAX_MB`、依 MIME 判可預覽（PDF / 圖片）/ 僅下載（Office）
- **T017 DOC_ID 產生器** `dm/util/docid`：`DM-{分類碼}-{6 位流水號}`、流水號依分類獨立、草稿建立時配號
- **T018 通知服務接線** `dm/service/notify`：呼叫平台 SRVDP002（傳 `template_code`，範本 `DP_NOTIFY_TEMPLATE` MODULE=DM）；站內訊息 DM 自理、依 CHANNEL 發送；停用範本不發
- **T019 送審週期 / 狀態機服務** `dm/service/review`：`DM_REVIEW` 建立 / 核准 / 退回 / 撤回；約束「同一文件不可同時兩種送審」（單一 PENDING_*）
- **T020 受控資料維護共用** `dm/service/catalog`：分類 / func_name / 標籤之新增 / 改名 / 啟停、**不開放刪除**、停用後既有引用保留；AUDIENCE 組停用採 **soft-retire**（回傳受影響文件 / 閱覽者數）
- **T020a 標籤式可見性判定** `dm/util/visibility`：文件掛「全體」OR（文件 AUDIENCE 標籤 ∩ 使用者 `DM_USER_TAG` ≠ 空）；閱覽者套用、編輯者 / 審核者 / 管理者略過

**前端**：建立 DM 模組殼（左側功能列骨架、路由）；各 US 畫面於對應 issue 填實。

**測試**：13 表 migration up / down；DOC_ID 產號（分類獨立流水、草稿配號）；可見性判定（全體 / 交集 / 空）；狀態機單一送審週期約束；存取閘（無 DM 角色 → 拒絕，含 API）；檔案上限 / MIME 判定；catalog 停用保留既有引用 + soft-retire。

### 驗收條件

- [ ] 13 張 DM 業務表 migration 建立且 up / down 正常；`DM_DOCUMENT` 部分唯一索引（MANUAL + PUBLISHED 之 FUNC_CODE 唯一）生效；append-only 表（`DM_USER_ROLE_LOG` / `DM_DOC_READ` / `DM_CHANGE_LOG`）無 update / delete 途徑
- [ ] DM 業務種子（4 分類 + 分類碼 / 4 標籤組 / 5 可見對象）寫入；DM 通知範本（`MODULE=DM`）+ DM_ 參數種子落地（落點依 `/sti-plan` 確認）
- [ ] **存取閘**（T014）：具任一 DM 角色者放行、無 DM 角色者拒絕進入（含直呼 API）；重用 DP 登入 JWT，DM 不自建登入
- [ ] 授權工具（4 角色聯集 + 排除自審 + 自我保護）、DOC_ID 產生器、檔案服務、通知接線、狀態機、catalog、可見性判定共用件實作 + 單元 / 整合測試
- [ ] `DP_PARAM.DM_*` 經 SRVDP001 讀取正常；通知經 SRVDP002 排入 `DP_EMAIL_LOG`
- [ ] `uv run pytest -q` 全綠；ruff / ESLint / type-check / 覆蓋率門檻通過

### 依賴

- **平台模組 DP（#0~#12，已合併）**：`DP_USER` / `DP_PARAM` / `DP_NOTIFY_TEMPLATE` / `DP_EMAIL_LOG` / `DP_SCHEDULE` + SRVDP001 / 002 / 003 + dp-roles 轉接層
- **ET 模組**：`DP_USER` schema 協調（SSO 共用）；ET 引用端（US12 SRVDM）於後續 issue

### 注意事項

- **集中化裁剪**：不建 `DM_PARAM` / `DM_NOTIFY_TEMPLATE` / `DM_NOTIFY_QUEUE`；參數 / 範本 / outbox / 排程集中於平台 DP（見上）。
- **省略 SITE / HOSPITAL 欄位**（對齊平台 DP，research §1）；標準欄位依平台 BaseModel 慣例。
- **存取閘 = US2 之全部 DM 工作**：登入 / 註冊 / 忘記密碼由 DP 提供，DM 不實作；「首次登入自動授予閱覽者」已作廢——新帳號預設僅 ET 學員，DM 角色一律由管理者於 DP 後台權限管理開通。
- **跨模組種子落點**（DM 範本 / 參數寫 DP 表）與 **US1 轉接層契約落地**（DM 端實作 `../dp/contracts/module-callbacks.md` §3 之 `get_users_roles_audiences` / `assign_roles_audiences` + `DmRoleAudienceView` + `has_any_role`；DETAIL_LOCK 碼鎖定對應、AUDIENCE soft-retire 跨模組落點）留待對應 issue 之 `/sti-plan` 與 SA 確認。
- **檔案儲存**：每版本單檔、PDF / 圖片可預覽、Office 僅下載；上限 / 格式由 `DP_PARAM.DM_FILE_MAX_MB` / `DM_FILE_TYPES` 控制。

### 相關文件

- [plan.md](plan.md)、[data-model.md](data-model.md)、[research.md](research.md) §1–§10、[tasks.md](tasks.md) Phase 1–2（T001~T020a）
- [contracts/document-service.md](contracts/document-service.md)（SRVDM001 / 002）、[spec_us2.md](spec_us2.md)（存取閘）、[spec_us1.md](spec_us1.md)（受控資料 / 權限業務規則）
- 平台：[../dp/spec.md](../dp/spec.md)（SRVDP001–003 / dp-roles / DP_SCHEDULE）

**Labels**：`priority:P0`, `DM-文件管理`（新 label）

---

## Issue #1：[P1-核心] DM — 系統設定（轉接層模組端 + 業務規則 + 種子驗證）（GitHub [#133](https://github.com/sti-fhb/EDMS/issues/133)）

**對應規格**：[spec_us1.md](spec_us1.md)（FR-001~010 / UCDM11）；[../dp/contracts/module-callbacks.md](../dp/contracts/module-callbacks.md) §3（角色 / 可見對象指派回呼）、§4（`has_any_role`）；[data-model.md](data-model.md)（`DM_USER_ROLE` / `DM_USER_ROLE_LOG` / `DM_USER_TAG` / `DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG`）
**對應畫面**：**無獨立 DM 畫面**——維護 UI 全在平台 DP 系統管理後台，按 `MODULE=DM` / `DM_` 前綴過濾：「權限管理」（角色 + 可見對象指派）、「系統參數與清單」（分類 / func_name / 標籤 / 催辦門檻）、「通知範本」（9 事件）
**階段**：P1-核心
**涵蓋 Tasks**：T024（catalog 業務規則 + 轉接層）、T025（催辦門檻）、T026（權限轉接層）、T027（通知範本語意）、T027a（可見對象授權轉接層）、T027b（每週執行時間）
**前置條件**：
- **#127 Foundation（已交付合併）**：`DM_USER_ROLE(_LOG)` / `DM_USER_TAG` / `DM_CATEGORY` 等 13 表；`CatalogService`（T020，含 AUDIENCE soft-retire）/ `authz`（T015，含自我保護 `DM_ROLE_001`）；DM 業務種子（4 分類 / 4 標籤組 / 5 可見對象）+ 9 通知範本（`MODULE=DM`）+ DM_ 參數（`DM_REMIND_THRESHOLD` / `DM_WEEKLY_SCHED_DAY_TIME` 等）皆已種入 DP 共用表
- **平台 DP（#0~#12，已交付合併）**：dp-roles（權限管理 UI，US7）/ dp-params（系統參數與清單）/ dp-templates（通知範本）之後台畫面；SRVDP001（參數唯讀）/ SRVDP003（稽核）

### 任務說明

DM 系統設定「無獨立 DM 畫面」——所有維護介面集中於平台 DP 系統管理後台（按模組過濾，只見 / 只改 `MODULE=DM` / `DM_` 前綴之列）。本 Issue 交付 **DM 端**讓 DP 後台得以維護 DM 設定所需的三類接點：

1. **權限 / 可見對象轉接層回呼**（供 DP dp-roles 呼叫）——本 Issue 之淨新增主體；
2. **catalog 轉接層**（供 DP「系統參數與清單」維護 DM 分類 / func_name / 標籤，包裝 #127 之 `CatalogService`）；
3. **業務規則落地與種子維護驗證**——#127 已種之範本 / 參數 / 分類，確認經 DP 後台按模組過濾可正確維護、經 SRVDP001 讀回正確。

> ℹ️ **後端為主之轉接層 issue**：與 ET 之 `assign_roles_tags` 同機制，DM 提供對稱之 `assign_roles_audiences`。**無新 DM 業務畫面**；前端僅在 DP 後台按模組過濾呈現（DP 側既有畫面消費本 Issue 之回呼）。

### 範圍

**後端 — 權限轉接層（T026，FR-005 / 006 / 008）**：
- 實作 [module-callbacks.md](../dp/contracts/module-callbacks.md) §3 `get_users_roles_audiences(user_ids)` → `dict[user_id, DmRoleAudienceView]`（`roles` ⊂ {ADMIN/EDITOR/REVIEWER/VIEWER}、`audiences`＝`DM_TAG`（AUDIENCE 組）之 `TAG_ID` 集〔DM 自持表，非 DP_PARAM〕、`last_modified_by/date` 取自模組表 `UPDATED_*`）；**批次**載入一頁使用者避 N+1、查無指派回**空集合 View**（非缺 key）
- `assign_roles_audiences(user_id, roles, audiences, operator_id)`：寫 `DM_USER_ROLE` + `DM_USER_ROLE_LOG`（append-only 異動）、**即時生效**、記「最後異動」；**自我保護**（operator 取消自己管理者角色 → raise `AppError` `DM_ROLE_001`，DP 端映射 `DP-MSG-ROLES-001`）；**不檢核**「至少 1 名管理者」；audience 值 MUST 屬 `DM_TAG`（AUDIENCE 組、`IS_ENABLED=true`）啟用中清單（寫入前檢核）；**同交易**呼叫 SRVDP003 寫稽核（`MODULE=DM`）
- §4 `has_any_role(user_id)`：入口頁 DM 卡狀態 + 側欄 DM 組可見性判定（包裝 #127 `authz.has_any_dm_role`）
- 回呼註冊至 DP 呼叫之 registry（與 ET 同機制）

**後端 — 可見對象授權轉接層（T027a，FR-009 / 010）**：
- 使用者 × AUDIENCE 標籤指派 → `DM_USER_TAG`、即時生效、寫異動、「最後異動」（併入上述 `assign_roles_audiences` 之 audiences 參數）
- AUDIENCE 值停用採 **soft-retire**（包裝 #127 `CatalogService.soft_retire_audience_tag`）：既有文件 / 授權可見性不變、僅停後續指派，回傳受影響文件 / 閱覽者數

**後端 — catalog 轉接層（T024，FR-001 / 002 / 003）**：
- 實作 [module-callbacks.md §3.1](../dp/contracts/module-callbacks.md)（`list_controlled` / `create_controlled` / `rename_controlled` / `set_controlled_enabled` / `list_audiences`），供 DP「系統參數與清單」維護 DM 分類 / func_name / 標籤（包裝 #127 `CatalogService`）：新增 / 改名 / 啟停、**不開放刪除**、分類碼英數唯一 + 建立後鎖定（`DM_CATALOG_003` / `001`）、停用後既有引用 100% 保留；`list_audiences` 供權限管理可見對象核取清單

**後端 — 參數 / 範本維護驗證（T025 / T027 / T027b，FR-004 / 007）**：
- 催辦門檻 `DP_PARAM.DM_REMIND_THRESHOLD`（1–30、預設 7）、每週執行時間 `DP_PARAM.DM_WEEKLY_SCHED_DAY_TIME`（`星期,HH:MM`、預設 `週一,10:00`，供 SCHDM001 讀取）、9 通知範本（`MODULE=DM`，「文件發布通知」＝撰寫者+相符閱覽者、「KPI 週報」「未讀提醒」＝僅 Email、自動催辦含門檻）——皆 #127 已種；本 Issue **驗證**經 DP 後台按模組過濾可正確維護（值域校驗落點依 `/sti-plan`）

**前端**：無新 DM 畫面。維護 UI 全在 DP 後台（dp-roles / dp-params / dp-templates 既有畫面，按 `MODULE=DM` 過濾消費本 Issue 回呼）。

**測試**：
- 轉接層 `get_users_roles_audiences` 批次往返（含空集 View、多使用者一頁）
- `assign_roles_audiences`：角色 / 可見對象即時生效、寫 `DM_USER_ROLE_LOG`、同交易 SRVDP003 稽核（`MODULE=DM`）、自我保護 `DM_ROLE_001`、audience 非啟用值拒絕、管理者間可互相停用（不檢核 0 管理者）
- AUDIENCE soft-retire 回傳受影響數、既有授權保留
- `has_any_role` 正反（有 / 無 DM 角色）
- catalog 轉接層：分類新增 / 改名 / 停用（既有引用保留）
- 種子維護驗證：`DP_PARAM.DM_*` 經 SRVDP001 讀回正確、範本 `MODULE=DM` 過濾

### 驗收條件

- [ ] DP 後台「權限管理」（DM 模組）經 `get_users_roles_audiences` 批次列出使用者之 DM 4 角色 + 可見對象 + 「最後異動」
- [ ] 指派 / 取消角色即時生效、寫 `DM_USER_ROLE_LOG`、同交易 SRVDP003 稽核（`MODULE=DM`）；管理者取消自己 → `DM_ROLE_001`（DP 顯示 `DP-MSG-ROLES-001`）；管理者間可互相停用、不檢核「至少 1 名管理者」
- [ ] 可見對象授權指派即時生效、寫異動；AUDIENCE 值停用 soft-retire 回傳受影響文件 / 閱覽者數、既有可見性不變；audience 值非 `DM_TAG`（AUDIENCE 組）啟用清單則拒絕
- [ ] DP 後台「系統參數與清單」（DM 模組）可維護 DM 分類 / func_name / 標籤（新增 / 改名 / 啟停、**不刪除**、分類碼英數唯一 + 建立後鎖定）；停用後既有文件引用保留
- [ ] 催辦門檻（1–30、預設 7）、每週執行時間（預設 `週一,10:00`）經 DP 後台按模組過濾維護、經 SRVDP001 讀回正確
- [ ] 9 通知範本（`MODULE=DM`）經 DP 後台「通知範本」按模組過濾可編輯主旨 / 內文 / 啟停；只見 / 只改 `MODULE=DM` 的列
- [ ] `has_any_role` 正確驅動入口頁 DM 卡狀態 + 側欄 DM 組可見性
- [ ] 轉接層回呼已註冊至 DP 呼叫之 registry；單元 / 整合測試全綠；ruff / ESLint / type-check / 覆蓋率門檻通過

### 依賴

- **#127 Foundation（已交付）**：`DM_USER_ROLE(_LOG)` / `DM_USER_TAG` / `DM_CATEGORY` 等表、`CatalogService` / `authz`（含 `DM_ROLE_001`）、範本 + 參數 + 分類種子
- **平台 DP dp-roles（US7）/ dp-params / dp-templates（#0~#12，已交付）**：呼叫 DM 轉接層回呼之上游畫面；SRVDP001（參數唯讀）/ SRVDP003（稽核）
- **契約**：[module-callbacks.md](../dp/contracts/module-callbacks.md) §3 / §4

### 注意事項

- **無獨立 DM 畫面**：維護 UI 全在 DP 後台（按模組過濾）；本 Issue 主體為後端轉接層 + 業務規則 + 種子維護驗證，避免與 #127 已交付之種子 / 服務重複造輪（本 Issue 為**包裝為轉接層回呼 + 驗證**）
- **已於 2026-08-06 交付前自檢定案**（`/sti-sa-precheck dm us1`，PR 待提）：
  - ✅ **catalog 轉接層契約**：[module-callbacks.md](../dp/contracts/module-callbacks.md) **§3.1**（`list_controlled` / `create` / `rename` / `set_controlled_enabled` / `list_audiences`）已定義 DP 後台呼叫 DM 維護 `DM_CATEGORY` / `DM_FUNC` / `DM_TAG`
  - ✅ **AUDIENCE soft-retire 跨模組觸發落點**：DP 後台呼叫 DM `set_controlled_enabled(enabled=False)` → DM 端執行 soft-retire 回 `SetEnabledResult(affected_docs, affected_viewers)`、DP 呈現提示（§3.1）
  - ✅ **`DmRoleAudienceView.audiences` 來源**：`DM_TAG`（AUDIENCE 組）TAG_ID，非 DP_PARAM（module-callbacks §3 已更正）
- **開工前 `/sti-plan` 尚待確認**：**參數值域校驗落點**（催辦門檻 1–30、每週時間格式）於 `DP_PARAM` 定義端（DP 通用參數編輯器）或 DM 端——參數為 `DP_PARAM`、由 DP dp-params 直接維護，值域屬 DM 業務規則，需確認 DP 參數定義是否承載值域 metadata
- 自我保護 error_code `DM_ROLE_001` 已於 #126 定案（DP 統一映射 `DP-MSG-ROLES-001`）
- **省略 SITE / HOSPITAL 欄位**（對齊平台 DP，research §1）

### 相關文件

- [spec_us1.md](spec_us1.md)（FR-001~010）、[../dp/contracts/module-callbacks.md](../dp/contracts/module-callbacks.md) §3 / §4、[data-model.md](data-model.md)
- 平台：[../dp/spec_us7.md](../dp/spec_us7.md)（dp-roles 權限管理）、[../dp/contracts/platform-services.md](../dp/contracts/platform-services.md)（SRVDP001 / 003）
- [tasks.md](tasks.md) Phase 4（T024~T027b）

**Labels**：`P1-核心`, `DM-文件管理`, `US1`

---

## Issue #2 ~ #13：待補（增量模式）

依總覽表順序，於前一張 Issue 實作驗證 OK 後補入完整 body（格式同 Issue #0 / #1，對齊 `sti-issue-create` canonical 模板）。

---

## 異動紀錄

| 日期 | 異動 |
|------|------|
| 2026-08-05 | 首版建立。DM 分析文件對齊平台 DP 集中化後（spec / plan / research / data-model / tasks / wireframe，PR #122 + tasks.md 對齊）產出 issues.md：總覽表列 #0~#13 全貌 + Issue #0（Foundation）完整撰寫，採增量模式。**切分要點**：US2 登入不開獨立 issue（DP 提供、存取閘併 #0 T014）；US1 系統設定為轉接層模組端 + 業務規則 + 種子（維護 UI 在 DP 後台，精確契約待 /sti-plan）；US12 / US13 跨模組（依賴 ET 引用端 / DP 排程引擎）。DM 業務種子屬 #0；DM 通知範本 / 參數種子寫平台 DP 表之落點待 /sti-plan 確認。`DM-文件管理` label 待建（依 sti-label-rules）|
| 2026-08-05 | US1 交付前自檢（`/sti-sa-precheck dm us1`）2 必補修正（PR #126）：轉接層命名對齊 DP 契約（`get_users_roles_audiences` / `assign_roles_audiences`）+ 自我保護 error_code `DM_ROLE_001`（DP 映射 `DP-MSG-ROLES-001`）；AUDIENCE soft-retire 跨模組落點留為 US1 開工前 SA Q。`DM-文件管理` label 已建（#5319E7）|
| 2026-08-05 | Issue #0（Foundation）已開立為 GitHub [#127](https://github.com/sti-fhb/EDMS/issues/127)（labels `priority:P0` + `DM-文件管理`），回填總覽表 GitHub # 欄與 body header |
| 2026-08-06 | Issue #0（#127）已交付合併（PR #129）。撰寫 Issue #1（US1 系統設定）完整 body：對應 spec_us1 FR-001~010 + module-callbacks §3/§4；涵蓋 T024~T027b。**切分要點**：US1 無獨立 DM 畫面（維護 UI 全在 DP 後台按模組過濾），淨新增主體為權限 / 可見對象**轉接層回呼**（`get_users_roles_audiences` / `assign_roles_audiences` / `has_any_role`）+ catalog 轉接層，其餘為 #127 已種之範本 / 參數 / 分類之維護驗證。Labels `P1-核心` + `DM-文件管理` + `US1` |
| 2026-08-06 | US1 交付前自檢（`/sti-sa-precheck dm us1`）3 必補（皆 #127 集中化修正未回傳造成的 drift）：**(1)** spec_us1 開頭「定義存 DP_PARAM」措辭過寬 → 對齊 spec.md §跨模組共用規則（分類/func/標籤/可見對象＝DM 自持表）；**(2)** module-callbacks §3 `DmRoleAudienceView.audiences` 來源 DP_PARAM → `DM_TAG`（AUDIENCE 組）TAG_ID；**(3)** 新增 module-callbacks §3.1 catalog 轉接層契約（受控主檔維護 + `list_audiences` + AUDIENCE soft-retire 觸發落點）。開工前 3 項 SA Q 已定案 2 項（catalog 轉接層 / soft-retire 落點），剩「參數值域校驗落點」待 `/sti-plan` |
| 2026-08-06 | Issue #1（US1）開立為 GitHub [#133](https://github.com/sti-fhb/EDMS/issues/133)（labels `P1-核心` + `DM-文件管理` + `US1`），回填總覽表與 body header。開立前同步修正 Issue #1 body 內殘留 drift（範圍/驗收條件之 `audiences`＝DP_PARAM → `DM_TAG` TAG_ID、catalog 轉接層引 §3.1），與交付前自檢後之 spec_us1 / module-callbacks 一致 |
