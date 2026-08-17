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
| 2 | 文件庫與檢索 | US3 / UCDM03 | P1-核心 | T028 / T028a / T029 / T030 | #0；#4（資料來源）| [#150](https://github.com/sti-fhb/EDMS/issues/150) | 🚀 已開立 [#150](https://github.com/sti-fhb/EDMS/issues/150) |
| 3 | 文件詳細頁瀏覽 | US4 / UCDM04 | P1-核心 | T031 / T032 / T033 / T034 | #0；#4/#5（資料來源）| [#155](https://github.com/sti-fhb/EDMS/issues/155) | 🚀 已開立 [#155](https://github.com/sti-fhb/EDMS/issues/155) |
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
>
> **US2 → Foundation #0（[#127](https://github.com/sti-fhb/EDMS/issues/127)）落地對照**（可追溯性；證明 US2 各條 FR / AC / 訊息已被 #0 涵蓋，無需獨立 issue）：
>
> | spec_us2 | 內容 | 落地位置 | 狀態 |
> |----------|------|---------|------|
> | FR-001 | 具任一 DM 角色放行、無則拒絕進入（含直呼 API）、MUST NOT 自動授予 | #0 T014 SSO 存取閘（`dm/middleware/auth`）；#0 驗收條件「存取閘：具任一 DM 角色放行、無則拒絕（含直呼 API）」 | ✅ [#127](https://github.com/sti-fhb/EDMS/issues/127)（PR #129 合併）|
> | FR-002 | 認證 / 帳密 / 姓名 / Email 維護由平台 DP、DM 不自建畫面 | 平台 DP（UCDP001–004，已交付）；#0 重用 DP 登入 JWT、DM 不建登入 | ✅ DP 既有 |
> | DM-MSG-LOGIN-007 | 「尚未開通文件管理權限，請洽管理者」 | #0 T014 存取閘拒絕訊息 | ✅ #127 |
> | AC1 | 有任一 DM 角色 → 導向 DM00 系統儀表板 | 存取閘僅負責准入判定；導向之 DM00 儀表板屬 US7（Issue #6）| ➡️ US7 / #6 |
> | AC2 | 無 DM 角色（含直接 URL 存取）→ 後端拒絕、提示、MUST NOT 自動授予 | #0 T014（後端 enforce、含直呼 API 擋下）| ✅ #127 |
> | AC3 | 註冊 / 忘記密碼 / 改帳密由 DP；新帳號預設僅 ET 學員、DM 角色由管理者於 DP 後台開通 | 平台 DP（UCDP001–004）+ DM 系統設定轉接層（Issue #1 / [#133](https://github.com/sti-fhb/EDMS/issues/133) 供 dp-roles 消費）| ✅ DP + #133 |

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

## Issue #2：[P1-核心] DM — 文件庫與檢索（US3 / UCDM03 / DM01）（GitHub [#150](https://github.com/sti-fhb/EDMS/issues/150)）

**對應規格**：[spec_us3.md](spec_us3.md)（FR-001~006 / 008 / 009，UCDM03，訊息 DM-MSG-DM01-001 / 002）；[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_TAG` / `DM_TAG_GROUP` / `DM_CATEGORY` / `DM_FUNC` / `DM_USER_TAG`）；[research.md](research.md) §5b（標籤式可見性）
**對應畫面**：**DM01 文件庫**（[wireframes/dm/index.html](../../wireframes/dm/index.html) `DM01`）——多條件搜尋列 + 結果清單（分頁）+（編輯者）新增文件入口
**階段**：P1-核心
**涵蓋 Tasks**：T028（多條件搜尋 `dm/library`）、T028a（標籤式可見性過濾）、T029（系統操作手冊 func_name 檢索）、T030（新增文件入口，依編輯者角色）
**前置條件**：
- **#0 Foundation（[#127](https://github.com/sti-fhb/EDMS/issues/127)，已交付合併）**：`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_TAG(_GROUP)` / `DM_CATEGORY` / `DM_FUNC` / `DM_USER_TAG` 表；**標籤式可見性判定 `dm/util/visibility`（T020a）**、角色授權 `authz`（T015）、受控資料查詢 `CatalogService`（T020，供分類 / func_name / 檢索標籤下拉）、DM 模組殼與路由骨架
- **文件資料來源**：真實「已發布」文件經 US5（[#4] 新增編輯）+ US6（[#5] 簽核發布）產生；本 Issue 之整合測試以**種子 / fixture 直接寫入已發布文件**獨立驗證，不阻塞於 #4 / #5 交付
- **點列去向**：文件詳細頁 US4（[#3]）；#3 未交付前前端先接路由骨架（進入 DM02 佔位）

### 任務說明

實作 **DM01 文件庫**：使用者以多條件（關鍵字 / 分類 / 作者 / 檢索標籤多選 OR / 發布日期區間）搜尋**已發布**（含廢止待簽核）之**目前發布版本**文件，依發布時間新到舊分頁呈現，點列進入文件詳細頁（US4）。當分類選「系統操作手冊（MANUAL）」時額外顯示「關聯作業項目（func_name）」下拉、依作業項目檢索唯一手冊（線上操作手冊能力）。**閱覽者**之結果套用〈標籤式可見性〉過濾（僅見掛「全體」或可見對象相符者），編輯者 / 審核者 / 管理者不過濾。具編輯者角色者見「新增文件」入口（→ US5 新增模式）。

> ℹ️ **讀取型全端 issue**：後端搜尋端點（`dm/library`，唯讀查詢）+ 前端 DM01 頁。**核心可見性判定重用 #0 T020a**；本 Issue 不改動文件 / 版本寫入（屬 US5 / US6）。

### 範圍

**後端 — 文件庫搜尋（T028，FR-001~003 / 005 / 009）** `app/dm/library`（router → service → repository，唯讀）：
- 多條件查詢：**關鍵字**（`ILIKE` 簡易模糊，比對文件名稱 + 目前版本 `CHANGE_SUMMARY`；非全文檢索）、**分類**（`CATEGORY_CODE`）、**作者**（撰寫者 `DM_DOCUMENT.CREATED_USER` → `DP_USER.user_name`，唯讀 join）、**檢索標籤**（`DM_DOC_TAG` ∩ 選定 `TAG_ID`，**多標籤 OR**；標籤限**檢索組** RETRIEVAL〔MODULE / NATURE / LEGAL〕，**不含** AUDIENCE 權限組）、**發布日期區間**（目前版本 `PUBLISHED_DATE`）
- **狀態集合**：僅 `DM_DOCUMENT.STATUS ∈ {PUBLISHED, PENDING_OBSOLETE}`（廢止待簽核仍對外有效），且僅取 `CURRENT_VERSION_ID` 對應版本；**排除** DRAFT / 送審中 / 已退回 / 已廢止與歷史版本
- 排序 `PUBLISHED_DATE` DESC + **後端分頁**（`paginate()`，回 `{data, meta}`）
- 回應欄位：文件名稱 / 分類 / 發布日期 / 作者姓名 / **檢索標籤清單**（前端灰字頓號呈現）/ DOC_ID；MANUAL 類附 `FUNC_CODE` / func 名稱

**後端 — 標籤式可見性過濾（T028a，FR-008）**：
- 套用 #0 `visibility.visible_docs_condition(user_id, roles)`：**閱覽者**僅得掛「**全體**」或（文件 AUDIENCE 標籤 ∩ 使用者 `DM_USER_TAG` ≠ 空，OR 比對）之文件；未被授予任何可見對象之閱覽者僅得「全體」；**編輯者 / 審核者 / 管理者回 None（不過濾）**
- 與其他搜尋條件（FR-001）以 **AND** 結合

**後端 — 系統操作手冊檢索（T029，FR-004）**：
- 分類為 `MANUAL` 時支援 `func_code` 過濾（選項來自 `CatalogService` 啟用中 FUNC 清單）；因 MANUAL + PUBLISHED 之 `FUNC_CODE` 部分唯一（#0 索引），結果至多一份

**前端 — DM01 文件庫頁（T028 / T029 / T030）** `frontend/src/dm/library`（沿用 `usePagedQuery` / 既有清單版面）：
- 搜尋列：關鍵字輸入、分類 select、作者輸入、**檢索標籤多選**（僅列 RETRIEVAL 組、非 AUDIENCE）、發布日期區間；**分類為 MANUAL 時**條件式顯示「關聯作業項目（func_name）」下拉（受控清單、不可自由輸入）
- 結果清單：欄位文件名稱 / 分類 / 發布日期 / 作者 / **標籤（灰色文字頓號分隔、非彩色 pill）**；MANUAL 類額外顯示 func_name；點列 → US4 詳細頁（路由）
- **新增文件入口**（T030）：僅**編輯者**角色顯示（`has_role` / 角色判定），點擊 → US5 新增模式（[#4]）
- 空結果 → DM-MSG-DM01-001「查無符合條件之文件」；引導提示 DM-MSG-DM01-002（選手冊分類以依作業項目檢索）

**測試**：
- 後端 int：多條件（關鍵字 / 分類 / 作者 / 檢索標籤 OR / 日期區間）；**狀態集合**（僅 PUBLISHED + PENDING_OBSOLETE 之目前版本，排除 DRAFT / 送審中 / 退回 / 已廢止 / 歷史版本）；排序 DESC + 分頁 meta；**可見性**（閱覽者：全體 / 交集 / 空三情境；編輯者 / 審核者 / 管理者見全部）；MANUAL func_code → 唯一手冊；空結果
- 前端：搜尋列渲染 + **func_name 下拉條件式**（選 MANUAL 才出現）；檢索標籤下拉**僅列 RETRIEVAL**（不含可見對象）；結果欄位 + 標籤灰字頓號；**新增文件入口依編輯者角色**顯示 / 隱藏；空狀態；點列導向詳細頁

### 驗收條件

- [ ] 多條件搜尋（關鍵字 / 分類 / 作者 / 檢索標籤多選 OR / 發布日期區間）正確過濾；無條件查詢回全部「已發布目前版本」（FR-001 / 002、AC1 / 2）
- [ ] 清單僅含 `STATUS ∈ {PUBLISHED, PENDING_OBSOLETE}` 之目前版本；送審中 / 草稿 / 已退回 / 已廢止與歷史版本**不出現**；廢止待簽核**持續顯示**（FR-002、AC4）
- [ ] 清單欄位含文件名稱 / 分類 / 發布日期 / 作者 / 標籤；標籤**灰色文字頓號分隔**（非彩色 pill）；MANUAL 類顯示 func_name（FR-003、AC3）
- [ ] 分類選「系統操作手冊」時顯示 func_name 下拉（受控清單、不可自由輸入）；選定 func 後結果唯一（FR-004、AC5 / 6）
- [ ] 依發布時間 DESC 後端分頁；無結果顯示 DM-MSG-DM01-001（FR-005）
- [ ] **閱覽者**結果套標籤式可見性：僅掛「全體」或可見對象相符（OR）；未授予可見對象者僅得「全體」；**編輯者 / 審核者 / 管理者不過濾**（FR-008、AC9 / 10）
- [ ] 檢索標籤下拉**僅列檢索標籤**（模組 / 文件性質 / 法規關聯），**不列可見對象**（FR-009）
- [ ] 具編輯者角色者顯示「新增文件」入口（→ US5 新增模式）、其他角色不顯示（FR-006、AC8）；點任一文件列 → US4 詳細頁（AC7）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

### 依賴

- **#0 Foundation（[#127](https://github.com/sti-fhb/EDMS/issues/127)，已交付）**：文件 / 版本 / 標籤表、可見性判定（T020a）、授權（T015）、受控清單查詢（T020，分類 / func / 檢索標籤下拉）、DM 模組殼 / 路由
- **US5（[#4]，文件資料來源）+ US6（[#5]，發布）**：實際「已發布」文件之產生路徑；本 Issue 以種子 / fixture 獨立測試、不阻塞其交付
- **US4（[#3]，詳細頁）**：點列去向；#3 未交付前前端接路由骨架

### 注意事項

- ⚠️ **狀態集合 vs 可見性判定之交互**（開工前 `/sti-plan` 對齊）：清單狀態集合為 `{PUBLISHED, PENDING_OBSOLETE}`（FR-002 廢止待簽核仍顯示），但 #0 `visibility.py` 對閱覽者之註解僅提「另 AND `STATUS='PUBLISHED'`」——本 Issue 之狀態集合 MUST 含 `PENDING_OBSOLETE`，可見性條件僅負責 AUDIENCE 標籤過濾、狀態集合另行 AND，兩者勿混。實作時確認 `visible_docs_condition` 之呼叫端狀態 AND 對齊 US3（否則廢止待簽核會被閱覽者漏看）
- **關鍵字為簡易 `ILIKE` 模糊**（比對文件名稱 + 目前版本變更摘要），非全文檢索（spec_us3 FR-001 明列）
- **檢索標籤 vs 可見對象分流**：DM01 檢索下拉只列 RETRIEVAL 組（MODULE / NATURE / LEGAL）；AUDIENCE 組為**權限標籤**、僅作用於可見性過濾、**不入檢索下拉**（FR-009）
- **作者** = 撰寫者 `DM_DOCUMENT.CREATED_USER` → `DP_USER.user_name`（唯讀 join；作者搜尋比對姓名）
- **唯讀 issue**：不改文件 / 版本寫入（US5 / US6）；本頁純查詢 + 前端呈現。無新增 error code（讀取型；分頁越界 COMMON_422 / 空結果為提示非 error）
- **省略 SITE / HOSPITAL 欄位**（對齊平台 DP，research §1）

### 相關文件

- [spec_us3.md](spec_us3.md)（FR-001~009）、[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_TAG(_GROUP)`）、[research.md](research.md) §5b（可見性）
- [tasks.md](tasks.md) Phase 5（T028~T030）、[spec_us1.md](spec_us1.md)（受控資料 / 可見對象授權）、[spec_us5.md](spec_us5.md)（新增模式，新增文件入口去向）、[spec_us4.md](spec_us4.md)（詳細頁，點列去向）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`DM01`）

**Labels**：`P1-核心`, `DM-文件管理`, `US3`

---

## Issue #3：[P1-核心] DM — 文件詳細頁瀏覽（US4 / UCDM04 / DM02）（GitHub [#155](https://github.com/sti-fhb/EDMS/issues/155)）

**對應規格**：[spec_us4.md](spec_us4.md)（FR-001~007，UCDM04，訊息 DM-MSG-DM02-001~003）；[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_DOC_READ` / `DM_REVIEW` / `DM_CATEGORY` / `DM_FUNC` / `DM_TAG`）；[research.md](research.md) §3（單版本單檔 / 檔案存檔案系統）
**對應畫面**：**DM02 文件詳細頁**（[wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-detail`）——標題列 + 右側資訊面板 + 文件檔案區（預覽 / 下載）+ 版本歷程抽屜 +（編輯者）動作入口 / read-only 廢止模式
**階段**：P1-核心
**涵蓋 Tasks**：T031（詳細頁版面）、T032（檔案區：預覽 / 下載 + 寫 `DM_DOC_READ`）、T033（版本歷程抽屜）、T034（動作入口 + read-only 模式）

### 任務說明

實作 **DM02 文件詳細頁**：閱讀目前發布版本、依格式線上預覽（PDF / 圖片）或下載原檔（Office 僅下載），展開版本歷程檢視所有版本，具編輯者角色者見「編輯新版本」/「廢止此文件」入口。上方標題列僅顯示識別與狀態（文件名稱 / DOC_ID / 目前版本 / 狀態），描述性 metadata 統一由右側「文件資訊」面板呈現（不重複）。**僅目前發布版可下載**（舊版僅預覽）；**下載目前發布版**寫一筆 `DM_DOC_READ`（KPI「已看」判定、預覽不記、同人同版去重）。自「已廢止文件查詢」（US10）進入時以 **read-only 模式**呈現。

> ℹ️ **讀取型全端 issue**：後端詳細 / 版本 / 檔案存取端點（唯讀查詢 + 下載記錄 `DM_DOC_READ` 為唯一寫入）+ 前端 DM02 頁。檔案預覽 / 下載重用 #0 檔案儲存服務（T016）；本 issue 不改文件 / 版本寫入（屬 US5 / US6）、不實作編輯 / 廢止動作本身（僅入口導向 US5 / US8）。

**前置條件**：
- **#0 Foundation（[#127](https://github.com/sti-fhb/EDMS/issues/127)，已交付合併）**：`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_DOC_READ` / `DM_REVIEW` / 受控主檔表；**檔案儲存服務 `dm/service/file_store`（T016，MIME 判可預覽 / 僅下載、檔案系統存取）**、角色授權 `authz`（T015）、**標籤式可見性 `visibility`（T020a）**（存取控制：閱覽者不可開啟未授權可見對象之文件）、DM 模組殼與路由骨架
- **文件 / 版本資料來源**：US5（[#4] 新增編輯）+ US6（[#5] 簽核發布）產生已發布文件與版本；本 issue 之整合測試以**種子 / fixture 直接寫入文件 + 版本 + 檔案 metadata** 獨立驗證
- **入口來源 / 去向**：由 US3（[#2] 文件庫）點列進入；動作入口導向 US5（[#4] 編輯）/ US8（[#7] 廢止申請）；read-only 模式由 US10（[#9] 已廢止查詢）進入

### 範圍

**後端 — 詳細頁資料（T031，FR-001）** `app/dm/detail`（router → service → repository，唯讀）：
- `GET /api/dm/documents/{doc_id}`：回標題列（`DOC_NAME` / `DOC_ID` / 目前版本 `VERSION_NO` / `STATUS`）+ 資訊面板（分類名 / 作者姓名〔唯讀 join `DP_USER`〕/ 發布日期 / 核准者姓名 / 核准時間 / 標籤）+ 目前版本檔案 metadata（`FILE_NAME` / `FILE_MIME` / 可預覽旗標）+ **操作能力**（`can_edit`：編輯者且無進行中送審週期）
- **存取控制**：套 `visible_docs_condition`（閱覽者不可存取未授權可見對象之文件 → 404 / 403 `DM_DOC_001`）；編輯 / 審核 / 管理不過濾

**後端 — 檔案存取 + 閱讀記錄（T032，FR-002 / 004 / 007）**：
- `GET /api/dm/documents/{doc_id}/versions/{version_id}/file?disposition=preview|download`：經 `file_store` 串流檔案；**PDF / 圖片**可 `preview`（inline）+ `download`；**Office** 僅 `download`（`preview` → 提示 DM-MSG-DM02-001）
- **僅目前發布版可下載**：舊版本 `download` → 403 `DM_DOC_002`（提示 DM-MSG-DM02-002「聯絡管理者」）；舊版本僅 `preview`
- **下載目前發布版** → 寫一筆 `DM_DOC_READ`（`DOC_ID` × `VERSION_ID` × `CREATED_USER` × 時間；**預覽不寫**；唯一約束 DOC×VERSION×USER 天然去重）

**後端 — 版本歷程（T033，FR-003 / 004）**：
- `GET /api/dm/documents/{doc_id}/versions`：列該文件**所有版本**（含 SUPERSEDED 歷史版本）之 `VERSION_NO` / 變更摘要 / 撰寫者姓名 / 核准者姓名 / 發布時間；標示目前發布版（可下載）vs 舊版（僅預覽）

**後端 — read-only / 廢止資訊（T034，FR-005 / 006）**：
- 動作入口能力：`can_edit`（編輯者且**無進行中 PENDING 送審週期**〔查 `DM_REVIEW`，非看文件 STATUS〕）；送審中 / 廢止待簽核 → 入口失效
- 已廢止（`OBSOLETE`）文件之 read-only 資料：廢止 banner（廢止時間 / 申請人 / 核准者 / 廢止原因 / **廢止附件下載，如有**〔取自 `DM_REVIEW` 廢止類〕）

**前端 — DM02 詳細頁（T031~T034）** `frontend/src/dm/detail`：
- 標題列（識別 + 狀態）+ 右側「文件資訊」面板（描述性 metadata、不與標題重複）
- 文件檔案區：PDF / 圖片內嵌預覽 + 下載鈕；Office 顯示「下載原檔以本機應用程式開啟」+ DM-MSG-DM02-001（不預覽）
- 版本歷程抽屜（時間軸）：所有版本；目前版可下載、舊版僅預覽（點下載 → DM-MSG-DM02-002）
- 動作入口（依 `can_edit`）：「編輯新版本」→ US5 編輯模式、「廢止此文件」→ US8；送審中 / 廢止待簽核時失效（灰階 + 提示）
- **read-only 模式**（自 US10 進入，如 route 參數）：隱藏「文件檔案 + 文件資訊」整段、**自動展開版本歷程**、所有版本僅預覽、上方紅色廢止 banner（DM-MSG-DM02-003）

**測試**：
- 後端 int：詳細資料（標題 / 資訊面板不重複欄位）；**存取控制**（閱覽者未授權可見對象 → 擋；編輯者見全部）；檔案存取（PDF / 圖片可預覽、Office 僅下載；舊版下載 403、僅預覽）；**下載目前版寫 `DM_DOC_READ` + 預覽不寫 + 同人同版去重**；版本歷程列所有版本；`can_edit`（編輯者且無 PENDING 送審 → true；有 PENDING → false）；廢止文件 read-only 資料（banner + 附件）
- 前端：標題 vs 資訊面板欄位分工；檔案區依 MIME（預覽 / 僅下載）；版本歷程抽屜（目前版可下載 / 舊版僅預覽）；動作入口依 `can_edit` 顯示 / 失效；read-only 模式（隱藏檔案+資訊、自動展開歷程、廢止 banner）

### 驗收條件

- [ ] 標題列僅顯示 文件名稱 / DOC_ID / 目前版本 / 狀態；描述性 metadata（分類 / 作者 / 發布日期 / 核准者 / 核准時間 / 標籤）僅於右側資訊面板、不重複（FR-001、AC1）
- [ ] PDF / 圖片提供線上預覽 + 下載；Office 檔僅下載（DM-MSG-DM02-001、不預覽）（FR-002、AC2 / 3）
- [ ] 版本歷程抽屜列**所有版本**（含歷史）之 版號 / 變更摘要 / 撰寫者 / 核准者 / 發布時間（FR-003、AC4）
- [ ] **僅目前發布版可下載**；舊版僅預覽、下載被擋（DM-MSG-DM02-002 / `DM_DOC_002`）（FR-004、AC5）
- [ ] **下載目前發布版**寫一筆 `DM_DOC_READ`（預覽不寫；同人同版去重）（FR-007）
- [ ] 具編輯者角色顯示「編輯新版本」/「廢止此文件」入口（→ US5 / US8）；送審中 / 廢止待簽核（`DM_REVIEW` 有 PENDING）時入口失效（FR-005、AC6 / 7）
- [ ] 閱覽者不可存取未授權可見對象之文件（後端 enforce）；編輯 / 審核 / 管理不受限（存取控制對齊 US3）
- [ ] 自 US10 進入以 read-only 模式：隱藏檔案 + 資訊、自動展開版本歷程、所有版本僅預覽、紅色廢止 banner（廢止時間 / 申請人 / 核准者 / 原因 / 附件）（FR-006、AC8、DM-MSG-DM02-003）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

### 依賴

- **#0 Foundation（[#127](https://github.com/sti-fhb/EDMS/issues/127)，已交付）**：文件 / 版本 / 標籤 / `DM_DOC_READ` / `DM_REVIEW` 表、**檔案儲存服務（T016）**、授權（T015）、可見性判定（T020a）、DM 模組殼 / 路由
- **US5（[#4]，文件資料來源）+ US6（[#5]，發布）**：實際文件 + 版本 + 檔案之產生路徑；本 issue 以種子 / fixture 獨立測試、不阻塞
- **US3（[#2]，入口）**：由文件庫點列進入（US3 已交付、點列導向本頁）
- **US5（[#4]）/ US8（[#7]）**：編輯 / 廢止入口之目的頁；**US10（[#9]）**：read-only 模式之進入來源——未交付前入口 / read-only 以骨架 / route 參數承接

### 注意事項

- ⚠️ **送審中 / 廢止待簽核之入口失效判定以「該文件是否已存在進行中（PENDING）之 `DM_REVIEW`」為準**（spec.md §狀態三維度），**非以文件 STATUS 判定**——已發布文件之新版本送審期間文件層 STATUS 仍為 PUBLISHED。
- ⚠️ **存取控制須與 US3 一致**：詳細頁 / 檔案下載端點 MUST 套 `visible_docs_condition`（防閱覽者直呼 API 取未授權可見對象之文件 / 檔案）；且沿用 US3 修正之 `visibility.py`（撤銷授權 / 移除標籤已濾 `DELETED`）。
- **`DM_DOC_READ` 只記「下載目前發布版」**：預覽（PDF / 圖片 inline）不記；發新版後 KPI「已看」綁新版本（US13 語意），本頁僅負責寫下載事件。
- **舊版本永久保留但僅預覽**：稽核取得舊版原始檔須聯絡 DM_ADMIN（spec_us4 FR-004）；本頁不提供舊版下載途徑。
- **檔案存取重用 #0 `file_store`（T016）**：單版本單檔、依 MIME 判可預覽（PDF / 圖片）/ 僅下載（Office）；不於本 issue 重造檔案服務。
- **Error codes（開工前 `/sti-plan` 對齊）**：新增 `DM_DOC_001`（查無此文件或無權存取，404 / 403）、`DM_DOC_002`（舊版本不可下載，403）；訊息 DM-MSG-DM02-001~003 為 UI 提示。
- **read-only 模式進入來源為 US10**（未交付）：本 issue 交付 read-only **渲染能力** + 廢止 banner 資料，實際入口待 US10 落地（架構差異、不阻塞）。
- **省略 SITE / HOSPITAL 欄位**（對齊平台 DP，research §1）。

### 相關文件

- [spec_us4.md](spec_us4.md)（FR-001~007）、[data-model.md](data-model.md)（`DM_DOC_VERSION` / `DM_DOC_READ` / `DM_REVIEW`）、[research.md](research.md) §3（檔案儲存）
- [tasks.md](tasks.md) Phase 6（T031~T034）、[spec_us5.md](spec_us5.md)（編輯入口）、[spec_us8.md](spec_us8.md)（廢止入口）、[spec_us10.md](spec_us10.md)（read-only 進入）、[spec_us13.md](spec_us13.md)（`DM_DOC_READ` KPI 語意）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-detail`）

**Labels**：`P1-核心`, `DM-文件管理`, `US4`

---

## Issue #4 ~ #13：待補（增量模式）

依總覽表順序，於前一張 Issue 實作驗證 OK 後補入完整 body（格式同 Issue #0 / #1 / #2 / #3，對齊 `sti-issue-create` canonical 模板）。

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
| 2026-08-11 | 補「US2 → Foundation #0（#127）落地對照」表於 US2 說明段：逐條列 spec_us2 FR-001/002、DM-MSG-LOGIN-007、AC1~3 之落地位置與狀態，強化可追溯性。維持 US2 **不開獨立 issue** 之切分（DM 端僅存取閘 T014、已隨 #127 / PR #129 交付；AC1 導向之 DM00 儀表板屬 US7 / #6）。未新增總覽表列 |
| 2026-08-11 | 撰寫 Issue #2（US3 文件庫與檢索 / DM01）完整 body：對應 spec_us3 FR-001~009 + UCDM03；涵蓋 T028 / T028a / T029 / T030。**切分要點**：讀取型全端（搜尋端點 + DM01 頁），核心可見性判定重用 #0 T020a、不改文件/版本寫入（屬 US5/US6）；狀態集合 `{PUBLISHED, PENDING_OBSOLETE}`、檢索標籤僅 RETRIEVAL（AUDIENCE 不入檢索下拉）、閱覽者套可見性過濾。前置 #0（必要）+ #4/#5（資料來源，以種子/fixture 獨立測試）。開工前 SA Q 候選：狀態集合 vs 可見性 STATUS AND 之交互（PENDING_OBSOLETE 對閱覽者可見）。Labels `P1-核心` + `DM-文件管理` + `US3`。總覽表 Issue #2 狀態改「📝 body 已撰寫（待開立）」 |
| 2026-08-11 | Issue #2（US3 文件庫與檢索）開立為 GitHub [#150](https://github.com/sti-fhb/EDMS/issues/150)（labels `P1-核心` + `DM-文件管理` + `US3`），回填總覽表 GitHub # / 狀態與 body header。交付前自檢（`/sti-sa-precheck dm us3`）結論 ✅ 齊備、無必補 |
| 2026-08-11 | 撰寫 Issue #3（US4 文件詳細頁瀏覽 / DM02）完整 body：對應 spec_us4 FR-001~007 + UCDM04；涵蓋 T031/T032/T033/T034。**切分要點**：讀取型全端（詳細/版本/檔案端點 + DM02 頁），檔案預覽/下載重用 #0 file_store（T016）、僅下載目前發布版寫 DM_DOC_READ（唯一寫入、預覽不記、同人同版去重）、存取控制套 visibility（對齊 US3、含撤銷授權濾 DELETED）；動作入口失效以 DM_REVIEW PENDING 判定（非文件 STATUS）；read-only 廢止模式進入來源為 US10（未交付、渲染能力先備）。前置 #0（必要）+ #4/#5（資料來源，種子/fixture 獨立測試）。開工前 SA Q 候選：DM_DOC_001/002 error code、檔案串流端點形狀。Labels `P1-核心` + `DM-文件管理` + `US4`。總覽表 Issue #3 狀態改「📝 body 已撰寫（待開立）」 |
| 2026-08-11 | Issue #3（US4 文件詳細頁瀏覽）開立為 GitHub [#155](https://github.com/sti-fhb/EDMS/issues/155)（labels `P1-核心` + `DM-文件管理` + `US4`），回填總覽表 GitHub # / 狀態與 body header。交付前自檢（`/sti-sa-precheck dm us4`）結論 ✅ 齊備、無必補 |
