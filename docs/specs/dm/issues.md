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
| 4 | 文件新增與編輯 | US5 / UCDM06 | P1-核心 | T035 ~ T039（含 T035a）| #0；#3/#5（入口/去向）| [#169](https://github.com/sti-fhb/EDMS/issues/169) | ✅ 已交付（PR #172；spec 對齊 #175/#176）|
| 5 | 簽核處理 | US6 / UCDM07 | P1-核心 | T040 ~ T044 | #4 | [#178](https://github.com/sti-fhb/EDMS/issues/178) | ✅ 已交付（PR #180；catalog 略）|
| 6 | 系統儀表板（入口頁 DM 概況 widget，#89）| US7 / UCDM02 | P2-延伸 | T045 ~ T046 | #4, #5；DP #89 | [#193](https://github.com/sti-fhb/EDMS/issues/193) | ✅ 已交付（PR #195；#89 widget）|
| 7 | 文件廢止申請 | US8 / UCDM05 | P2-延伸 | T047 ~ T048 | #3, #5（本 issue 延伸 US6 核准 / 退回）| [#206](https://github.com/sti-fhb/EDMS/issues/206) | ✅ 已交付（PR #210；follow-up #211）|
| 8 | 個人專區（草稿匣 / 我的文件動態 / 撤回送審）| US9 / UCDM09 | P2-延伸 | T050 ~ T052 | #4, #5；#7（撤回廢止）| [#219](https://github.com/sti-fhb/EDMS/issues/219) | 🚀 已開立 [#219](https://github.com/sti-fhb/EDMS/issues/219) |
| 9 | 已廢止文件查詢 | US10 / UCDM08 | P2-延伸 | T053 ~ T054 | #3, #5 | [#230](https://github.com/sti-fhb/EDMS/issues/230) | 🚀 已開立 [#230](https://github.com/sti-fhb/EDMS/issues/230) |
| 10 | 文件變更歷程查詢 | US11 / UCDM10 | P3 | T055 ~ T056 | #5 | [#243](https://github.com/sti-fhb/EDMS/issues/243) | 🚀 已開立 [#243](https://github.com/sti-fhb/EDMS/issues/243) |
| 11 | 跨模組教材引用（DM ↔ ET）| US12 / UCDM12 | P3-輔助 | T057 ~ T059 | #5；ET 引用端 | [#183](https://github.com/sti-fhb/EDMS/issues/183) | ✅ 已交付（PR #189；契約 #187；T059 廢止通知範圍外＝裁示 A + 待 US8）|
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
- `assign_roles_audiences(user_id, roles, audiences, operator_id)`：寫 `DM_USER_ROLE` + `DM_USER_ROLE_LOG`（append-only 異動）、**即時生效**、記「最後異動」；**自我保護**（operator 取消自己管理者角色 → raise `AppError` `DM_ROLE_001`，DP 端映射 `DP-MSG-DP06-001`）；**不檢核**「至少 1 名管理者」；audience 值 MUST 屬 `DM_TAG`（AUDIENCE 組、`IS_ENABLED=true`）啟用中清單（寫入前檢核）；**同交易**呼叫 SRVDP003 寫稽核（`MODULE=DM`）
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
- [ ] 指派 / 取消角色即時生效、寫 `DM_USER_ROLE_LOG`、同交易 SRVDP003 稽核（`MODULE=DM`）；管理者取消自己 → `DM_ROLE_001`（DP 顯示 `DP-MSG-DP06-001`）；管理者間可互相停用、不檢核「至少 1 名管理者」
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
- 自我保護 error_code `DM_ROLE_001` 已於 #126 定案（DP 統一映射 `DP-MSG-DP06-001`）
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

## Issue #4：[P1-核心] DM — 文件新增與編輯（US5 / UCDM06 / DM03）

**對應規格**：[spec_us5.md](spec_us5.md)（FR-001~009，UCDM06，訊息 DM-MSG-DM03-001~009）；[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_REVIEW` / `DM_CATEGORY` / `DM_FUNC` / `DM_TAG`）；[research.md](research.md) §4（單一送審週期）、§5（手冊唯一）
**對應畫面**：**DM03 文件新增 / 編輯**（[wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-upload`）——雙模式表單（新增：DOC_ID 配號 + 首版；編輯：身份欄唯讀 + 新版本）+ 可見對象 / 檢索標籤 + 單檔上傳（Office 警示）+ 指定審核者 + 存草稿 / 送簽
**階段**：P1-核心
**涵蓋 Tasks**：T035（新增模式 / DOC_ID 配號）、T035a（可見對象必填檢核）、T036（編輯模式 / 版本號檢核）、T037（func_name 單選 + 唯一檢核）、T038（單檔上傳 / Office 提醒）、T039（審核者排除自己 + 存草稿 + 送簽）

## 任務說明

實作 **DM03 文件新增與編輯**：編輯者新增文件（建 DOC_ID、首版）或對既有文件上傳新版本，填必填欄位、選受控標籤（可見對象必填 ≥1、檢索標籤選填），指定審核者後送簽，或存為草稿續編。**新增模式**必填 文件名稱 / 分類 / 首版摘要 / 可見對象 ≥1，選填檢索標籤，首版版號由撰寫者自行輸入；分類為「系統操作手冊（MANUAL）」時額外單選 func_name。**編輯模式**（自 US4 詳細頁「編輯新版本」進入）文件名稱 / 分類 / func_name 唯讀，僅可改 檔案 / 變更摘要 / 標籤 / 指定審核者 / 版本號。送簽建立一筆 PENDING `DM_REVIEW`（NEW / NEW_VERSION）並通知指定審核者，文件 / 版本進入送審中。

> ℹ️ **寫入型全端 issue（DM 第一個寫入功能）**：後端新增 `app/dm/editor`（建立 / 編輯 / 存草稿 / 送簽，寫 `DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` + 呼叫送審）+ 前端 DM03 表單。**組裝重用 #127 Foundation 既有工具**（DOC_ID 產生器 T017、file_store T016、ReviewService T019、authz T015、notify T018、catalog 轉接層、DB 約束），本 issue 不重造底層；**不含核准 / 發布**（屬 US6）、不含草稿匣列表 / 撤回（屬 US9）。

**前置條件**：
- **#127 Foundation（已交付合併）**：`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_REVIEW` 表 + DB 約束（`UX_DM_DOCUMENT_MANUAL_FUNC` 手冊唯一、`UQ_DM_DOC_VERSION_DOC_NO` 版本號唯一、`UQ_DM_DOC_TAG_DOC_TAG`）；**DOC_ID 產生器 `document/docid.py`（T017：`next_doc_id` MAX+1、並發由 PK 擋、呼叫端重試）**、**檔案儲存 `document/file_store.py`（T016：`validate_upload` 大小 `DM_FILE_001` / 副檔名 `DM_FILE_002`、`is_previewable`）**、**送審狀態機 `review/service.py`（T019：`submit` 審核者≠撰寫者 `DM_REVIEW_001` / 單一 PENDING 閘門 `DM_REVIEW_002`）**、**授權 `roles/authz.py`（T015）**、**通知 `notify/service.py`（T018：`DmNotifier.notify` 送簽用 `DOC_SUBMIT` 範本）**、catalog 轉接層（受控 func / tag / audience 下拉來源）
- **入口來源（已交付）**：US3 文件庫「新增文件」（新增模式）+ US4 詳細頁「編輯新版本」（編輯模式、帶 doc_id）
- **去向**：送簽後核准 / 退回 / 發布見 US6（#5，未交付）；存草稿續編 / 撤回見 US9（未交付）——本 issue 交付草稿寫入，草稿匣列表屬 US9

## 範圍

**後端 — 新增模式（T035 / T035a，FR-001 / 009）** `app/dm/editor`（router → service → repository，寫入）：
- `POST /api/dm/documents`：建立草稿文件——配 DOC_ID（`next_doc_id` + 唯一衝突重試）、寫 `DM_DOCUMENT`（STATUS=DRAFT、CREATED_USER=撰寫者）+ 首版 `DM_DOC_VERSION`（STATUS=DRAFT、版本號自行輸入）+ `DM_DOC_TAG`（可見對象 ≥1 + 檢索標籤）；必填檢核（名稱 / 分類 / 首版摘要）未填 → 422（訊息 DM-MSG-DM03-001）；可見對象 <1 → 422（DM-MSG-DM03-008）
- 寫入操作注入 `OperatorInfo` 填 `CREATED_*`；CUD 於 Service 層寫 AuditLog

**後端 — 編輯模式（T036，FR-003 / 004）**：
- `POST /api/dm/documents/{doc_id}/versions`：對既有文件新增一版（STATUS=DRAFT）——身份欄（名稱 / 分類 / func）不接受變更（唯讀，只吃 檔案 / 摘要 / 標籤 / 審核者 / 版本號）；版本號非空 + 同文件不重複（DB `UQ_DM_DOC_VERSION_DOC_NO` + 應用層友善 DM-MSG-DM03-009）；廢止待簽核（該 doc 有 PENDING OBSOLETE review）→ 阻擋 DM-MSG-DM03-004
- 存取控制：僅 DM_EDITOR 可寫（存取閘 + 角色判定）

**後端 — func 唯一 + 上傳（T037 / T038，FR-002 / 005）**：
- MANUAL 分類：func_name 必填單選 + **送簽 / 發布前唯一檢核**（查 DM_DOCUMENT：同 func_code 於 CATEGORY=MANUAL AND STATUS=PUBLISHED 無他份；DB `UX_DM_DOCUMENT_MANUAL_FUNC` 雙保險）→ 重複阻擋 DM-MSG-DM03-003
- 上傳：`file_store.validate_upload`（單檔 ≤ `DM_FILE_MAX_MB` 預設 50MB、副檔名白名單）；回可預覽旗標（`is_previewable`）供前端 Office 警示；每版本單檔

**後端 — 存草稿 + 送簽（T039，FR-006 / 007 / 008）**：
- `PATCH /api/dm/documents/{doc_id}/draft`：更新草稿續編（不送簽）
- `POST /api/dm/documents/{doc_id}/submit`：送簽——呼叫 `ReviewService.submit(review_type=NEW|NEW_VERSION, assigned_reviewer, author_id, version_id)`（內含審核者≠撰寫者 `DM_REVIEW_001`、單一 PENDING `DM_REVIEW_002`）；送簽前檢核 可見對象 ≥1 / 版本號 / func 唯一；成功 → 版本轉 PENDING_REVIEW、文件轉送審中（首版 PENDING_REVIEW；已發布文件之新版維持 PUBLISHED）、`DmNotifier.notify(DOC_SUBMIT)` 通知指定審核者
- 指定審核者下拉來源：具 DM_REVIEWER 角色且排除本人

**前端 — DM03 表單（T035~T039）** `frontend/src/dm/editor`：
- 雙模式頁（新增 `/dm/documents/new`、編輯 `/dm/documents/:docId/edit`）：新增全欄可填；編輯 名稱/分類/func 唯讀、預帶上版、顯示目前版本 + 新版號輸入
- 分類選 MANUAL → 條件式顯示 func_name 單選；可見對象多選（必填 ≥1、含全體）；檢索標籤多選（模組/性質/法規，選填）
- 版本號自行輸入（無系統建議）；變更摘要 label 依模式切「首版摘要 / 變更摘要」
- 單檔上傳（拖拉）；Office 檔 → 橘色警示條 + Modal 提醒（DM-MSG-DM03-002），可續行或改傳
- 指定審核者下拉（排除自己）；動作：儲存為草稿（DM-MSG-DM03-007）/ 送交簽核（DM-MSG-DM03-006）/ 取消（dirty 追蹤 → 二次確認 DM-MSG-DM03-005）

**測試**：
- 後端 int：新增建 DOC_ID + 首版 + 標籤（可見對象 ≥1）；可見對象缺漏擋；編輯模式身份欄唯讀 + 版本號空 / 重複擋；MANUAL func 唯一擋；上傳大小 / 型別擋 + 可預覽旗標；送簽建 PENDING review + 通知 + 審核者≠撰寫者擋 + 已有 PENDING 擋；廢止待簽核擋新版本；存草稿不送簽
- 前端：雙模式欄位（新增全填 / 編輯唯讀）；MANUAL 條件式 func；可見對象必填；版本號輸入；Office 警示 + Modal；審核者排除自己；存草稿 / 送簽 / 取消二次確認

## 驗收條件

- [ ] 新增模式建立 DOC_ID（`DM-{分類碼}-{6位流水號}`、依分類獨立、草稿即配號）+ 首版；必填 名稱 / 分類 / 首版摘要，未填擋（FR-001、AC1/3、DM-MSG-DM03-001）
- [ ] 可見對象 / 單位必填 ≥1（含「全體」）；送簽 / 發布前未掛則擋（FR-009、AC3a、DM-MSG-DM03-008）
- [ ] 分類 MANUAL 額外單選 func_name；送簽 / 發布前檢核同 func 至多一份已發布手冊，重複擋（FR-002、AC2/7、DM-MSG-DM03-003）
- [ ] 編輯模式 名稱 / 分類 / func 唯讀，僅可改 檔案 / 摘要 / 標籤 / 審核者 / 版號（FR-003、AC4）
- [ ] 版本號撰寫者自行輸入、無系統建議；非空且同文件不重複，否則擋（FR-004、AC4a、DM-MSG-DM03-009）
- [ ] 上傳支援 PDF/Word/Excel/PPT/圖片、單版本單檔、上限 `DM_FILE_MAX_MB`（預設 50MB）；非預覽 Office 跳提醒 + 橘色警示條，PDF/圖片不觸發（FR-005、AC5、DM-MSG-DM03-002）
- [ ] 指定審核者下拉僅列審核者角色且排除本人（FR-006、AC6）
- [ ] 支援存草稿（不送簽、可續編）；送簽轉送審中 + 建 PENDING `DM_REVIEW`（NEW/NEW_VERSION）+ 通知指定審核者（FR-007、AC8、DM-MSG-DM03-006/007）
- [ ] 廢止待簽核時擋上傳新版本（不可兩送審週期並存）；取消有未存變更 → 二次確認（FR-008、AC9/10、DM-MSG-DM03-004/005）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#127 Foundation（已交付）**：DOC_ID 產生器（T017）、file_store（T016）、ReviewService（T019）、authz（T015）、notify（T018）、catalog 轉接層、`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_REVIEW` 表 + DB 約束
- **入口（已交付）**：US3 文件庫「新增文件」+ US4 詳細頁「編輯新版本」
- **US6（#5，未交付）**：送簽後核准 / 退回 / 發布——本 issue 只到「送審中」，發布不在範圍；以獨立測試驗證送簽建 review
- **US9（未交付）**：草稿匣列表 / 撤回送審——本 issue 交付草稿寫入，列表 / 續編入口待 US9

## 注意事項

- ⚠️ **送審週期衝突以 `DM_REVIEW` PENDING 判定**（非文件 STATUS）：已由 `ReviewService.submit` 之單一 PENDING 閘門（`DM_REVIEW_002` + DB partial unique `UX_DM_REVIEW_ONE_PENDING`）保證；廢止待簽核擋新版本亦同此判定。
- ⚠️ **本 issue 不發布**：送簽只建 PENDING review + 轉送審中；核准 → PUBLISHED / SUPERSEDED 屬 US6。首版送審文件層 STATUS=PENDING_REVIEW，已發布文件之新版送審文件層維持 PUBLISHED（新版在版本層 PENDING_REVIEW）。
- ⚠️ **DOC_ID 並發配號**：`next_doc_id` 為 MAX+1，同分類並發可能撞號 → 由 PK 擋、**本 issue 呼叫端須以重試（catch IntegrityError 重取號）處理**。
- ⚠️ **func 唯一 / 版本號唯一雙層**：DB 約束為底、應用層先查給友善訊息（DM-MSG-DM03-003 / 009），並以 IntegrityError 為並發後盾。
- **檔案落盤**：`validate_upload` 僅驗大小 / 副檔名；實際 byte 落盤 + magic-bytes 驗真實型別屬部署 / 落盤層（見 #160 storage-root 圍籬 follow-up）。本 issue `FILE_PATH` 寫入策略須與落盤層一致（開工前 `/sti-plan` 對齊）。
- **Error codes（開工前 `/sti-plan` 對齊）**：沿用 `DM_FILE_001/002`、`DM_REVIEW_001/002`；US5 新增之寫入專屬 code（必填缺漏 / 可見對象缺漏 / 版本號重複 / 身份欄唯讀違反 / 廢止待簽核擋）須登記 `docs/ref/error-codes.md`（比照 US4 `DM_DOC_00x`）。
- **存草稿亦須附檔（現況）**：每版本單一檔案、`DM_DOC_VERSION.FILE_NAME/PATH/SIZE/MIME` 皆 NOT NULL；存草稿即建立版本列（首版 / 新版本）故**須先上傳檔案**，無檔草稿非現行支援（如需放寬須改 data-model 為 nullable，屬 SA 業務決定）。已發布文件必有檔（發布版即帶檔之版本列）。
- **指定審核者清單來源（無現成端點，US5 需新做）**：現有 DM 端點無「列 reviewer」來源；US5 須新增讀取路徑（如 `GET /api/dm/reviewers`）——查 `DM_USER_ROLE`（`ROLE_CODE='DM_REVIEWER'`）join `DP_USER.USER_NAME`、**排除當前使用者**。**`DM_USER_ROLE` 為 DM 自持表、直接查即可（非跨模組、不經 DP）**；送簽時另由 `ReviewService.submit` 擋自審（`DM_REVIEW_001`）雙保險。
- **省略 SITE / HOSPITAL 欄位**（對齊平台 DP，research §1）。

## 相關文件

- [spec_us5.md](spec_us5.md)（FR-001~009）、[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_DOC_TAG` / `DM_REVIEW`）、[research.md](research.md) §4（單一送審週期）/ §5（手冊唯一）
- [tasks.md](tasks.md)（T035~T039 含 T035a）、[spec_us6.md](spec_us6.md)（簽核發布）、[spec_us9.md](spec_us9.md)（草稿匣 / 撤回）、[spec_us3.md](spec_us3.md)（新增入口）、[spec_us4.md](spec_us4.md)（編輯入口）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-upload`）

**Labels**：`P1-核心`, `DM-文件管理`, `US5`

---

## Issue #5：[P1-核心] DM — 簽核處理（US6 / UCDM07 / DM04）（GitHub [#178](https://github.com/sti-fhb/EDMS/issues/178)，✅ 已交付 PR #180）

**對應規格**：[spec_us6.md](spec_us6.md)（FR-001~008，UCDM07，訊息 DM-MSG-DM04-001~006）；[data-model.md](data-model.md)（`DM_REVIEW` / `DM_DOC_VERSION` 狀態機 / `DM_DOCUMENT` / `DM_CHANGE_LOG`）；research §4（單一送審週期）
**對應畫面**：**DM04 簽核中心**（[wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-review`）——待簽核 / 已完成雙頁籤、清單 + 明細、核准並發布 / 退回
**階段**：P1-核心
**涵蓋 Tasks**：T040~T044

## 任務說明

實作 **DM04 簽核處理**：審核者於簽核中心處理**指派給自己**之送審，核准並發布（NEW 首版 / NEW_VERSION 新版本）或退回。核准發布原子完成版本切換（新版 PUBLISHED、舊版 SUPERSEDED、`CURRENT_VERSION_ID` 更新）、寫公開變更歷程、以 `DOC_PUBLISH` 通知撰寫者 + 可見對象相符閱覽者；退回必填原因、被退版本回草稿並 `DOC_REJECT` 通知撰寫者。停留逾門檻每日催辦；已完成頁籤回顧。組裝重用 #127 Foundation（`ReviewService.approve/reject`、`DmChangeLog`、`DOC_PUBLISH`/`DOC_REJECT`/`AUTO_REMIND` 範本、排程引擎、visibility）。

> ℹ️ **範圍切分（precheck）**：交付 `NEW`/`NEW_VERSION` 之核准/退回/發布 + 催辦 + 已完成；**`OBSOLETE` 核准（待 US8）、AC7 撤回消失（待 US9）不在範圍**（`DM_REVIEW_006` 擋 OBSOLETE、清單亦排除）。

## 範圍

**後端** `app/dm/review`（router → service → repository）：
- `GET /api/dm/reviews/pending`：僅 `assigned_reviewer=登入者` 之 PENDING（含停留天數、review_type、doc/version meta；排除 OBSOLETE）；不列「指定審核者」欄 — FR-001
- `GET /api/dm/reviews/{id}`：明細（變更摘要 + 檔案 meta；新版本附目前發布版供比對）；非本人 `DM_REVIEW_005` — FR-002
- `GET /api/dm/reviews/{id}/versions/{vid}/file`：**簽核明細取檔端點**（US4 端點僅開放目前發布版，審核者取不到待審版故另設；僅本人、版本白名單＝待審版＋目前發布版）
- `POST /api/dm/reviews/{id}/approve`：核准並發布——`ReviewService.approve` → 版本切換 + `CURRENT_VERSION_ID` + `DM_CHANGE_LOG(PUBLISH)` + 收件名單 + `DOC_PUBLISH`（單一交易原子、`FOR UPDATE` 序列化防重複發布）— FR-003/005/008
- `POST /api/dm/reviews/{id}/reject`：退回——必填原因（`DM_REVIEW_004`）→ 被退版本回 `DRAFT`（供續編再送 / 刪除，FR-004）；NEW 首版文件亦回 DRAFT、NEW_VERSION 文件維持 PUBLISHED（現行發布版不受影響）→ `DOC_REJECT` — FR-004/005
- `GET /api/dm/reviews/completed`：已完成（APPROVED/REJECTED、文件名 keyword、後端分頁、不可再操作）— FR-007
- 催辦 job `reminder.run`：每日掃停留 ≥ `DM_REMIND_THRESHOLD` → `AUTO_REMIND` Email；註冊於 `DP_SCHEDULE` **`SCHDM002`**（每日 08:00，migration `a1c8e6f4b920`）— FR-006

**前端** `frontend/src/dm/review`：DM04 雙頁籤；待簽核主從明細（點列 → 變更摘要 + 版本對照表〔版本/狀態/檔案/動作〕+ X 收合）+ 核准二次確認 + 退回 Dialog（原因必填、Zod）+ 停留天數標紅；已完成唯讀 + 文件名搜尋 + 分頁。

**測試**：後端 int（清單只列自己 PENDING / 核准原子切換 / 退回回 DRAFT + 通知 / 已完成搜尋分頁 / 收件名單全體+指定 / 催辦掃描 / 授權 / 取檔白名單 / HTTP）+ 前端（雙頁籤 / 核准二次確認 / 退回必填 / 停留標紅 / 明細下載）。

## 驗收條件

- [x] 待簽核僅列 `assigned_reviewer=登入者` 之 PENDING、不列指定審核者欄（FR-001）
- [x] 明細可下載送審檔（新版本新舊並列）、不預覽（FR-002）
- [x] 核准並發布（NEW/NEW_VERSION）二次確認後原子完成：新版 PUBLISHED + 舊版 SUPERSEDED + `CURRENT_VERSION_ID` + `DM_CHANGE_LOG(PUBLISH)` + `DOC_PUBLISH`（FR-003/005/008、DM-MSG-DM04-001）
- [x] 退回必填原因 → 被退版本回 DRAFT、通知撰寫者（FR-004/005、DM-MSG-DM04-004/005）
- [x] 已完成頁籤搜尋分頁、不可再操作（FR-007）
- [x] 催辦：停留 ≥ `DM_REMIND_THRESHOLD` 每日 `AUTO_REMIND` + 清單標紅（FR-006）
- [x] 僅指定審核者本人可核准/退回；核准者自 Session（FR-005、`DM_REVIEW_005`）
- [x] CI 全綠
- [ ] **（範圍外）** `OBSOLETE` 核准（待 US8）、AC7 撤回消失（待 US9）

## 依賴

- **#127 Foundation / #169 US5（已交付）**：`ReviewService`、`DmChangeLog`、通知範本、排程引擎、visibility、`DM_REMIND_THRESHOLD`；送審來源（NEW/NEW_VERSION 之 PENDING review）
- **US8（未交付）**：`OBSOLETE` 送審來源；**US9（未交付）**：AC7 撤回消失、退回續編入口

## 注意事項 / 實作與 spec 差異（交付後回填）

- ⚠️ **催辦排程 job id：`SCHDM002`（非 spec_us6 FR-006 原寫的 `SCHDM001`）**——`SCHDM001` 種子實為「DM KPI 週報 + 未讀提醒（週一）」，簽核催辦（每日）另用新排程 `SCHDM002`。**建議 SA 同步 spec_us6 FR-006 措辭**。
- ⚠️ **退回被退版本狀態＝`DRAFT`（非原述 `REJECTED`）**：符 FR-004「文件回草稿」供撰寫者續編/刪除；邊界（送審後又開草稿撞每人一份草稿唯一索引）保留 REJECTED；並連帶新增 `DM_DOC_012`（編輯器擋審核中再開草稿）。**建議 SA 同步 FR-004 措辭**。
- 催辦免站內訊息表（SA 裁示 Q1）：清單標紅（即時算）+ AUTO_REMIND Email；審核者站內「催辦中」呈現屬 US9。
- Error codes：新增 `DM_REVIEW_004/005/006`；取檔沿用 `DM_DOC_001/002`。

## 相關文件

- [spec_us6.md](spec_us6.md)、[data-model.md](data-model.md)、[wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-review`）、[spec_us9.md](spec_us9.md)（撤回 / 續編）、[spec_us8.md](spec_us8.md)（廢止）

**Labels**：`P1-核心`, `DM-文件管理`, `US6`

---

## Issue #6：[P2-延伸] DM — 系統儀表板（入口頁 DM 文件概況 widget）（US7 / UCDM02）（GitHub [#193](https://github.com/sti-fhb/EDMS/issues/193)）

**對應規格**：[spec_us7.md](spec_us7.md)（FR-001~004，UCDM02，訊息 DM-MSG-DM00-001）；DP [spec_us1.md](../dp/spec_us1.md)（導覽重構 #89：中性歡迎頁 + 依權限 widget）；[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_CATEGORY` / `DM_REVIEW`）
**對應畫面**：中性歡迎頁（`/`）之**依權限 DM 文件概況 widget**（內容示意見 [wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-overview`：各類型文件總數 4 卡 + 近 30 天公告）——**非獨立 DM00 落地頁**（#89）
**階段**：P2-延伸
**涵蓋 Tasks**：T045（統計卡區）、T046（最新更新公告區）

## 任務說明

實作**中性歡迎頁之 DM 文件概況 widget**（導覽重構 #89：不做獨立落地頁）：具任一 DM 角色之使用者於登入後之中性歡迎頁見此區塊——上方 4 內建分類（SOP / MANUAL / TRAINING / OTHER）之**已發布目前版本**數量與總計（純資訊、不可點）；下方近 30 天已發布文件公告（新增 / 新版本），點入 US4 詳細頁、「查看全部文件」進 US3 文件庫；近 30 天無事件顯示空狀態。**無任何 DM 角色者不顯示此區塊**（最小知悉）。純讀取、無寫入、無 migration。

> ℹ️ **讀取型全端 issue（簡單）**：後端 2 支唯讀查詢（統計 + 公告）+ 前端於中性歡迎頁疊加 DM widget（依 `has_any_role` 條件渲染）。重用既有 `DM_DOCUMENT` / `DM_DOC_VERSION` 查詢與 `visible_docs_condition` 可見性慣例。**設計依 DP #89**（原 spec_us7「登入自動導向 DM00 獨立頁」為 DM 單模組舊觀點、已於 spec_us7 更新對齊）。

## 範圍

**後端**（`app/dm/dashboard`，router → service → repository，唯讀）：
- **T045 統計卡**（FR-002）：`GET /api/dm/dashboard/stats` → 4 內建分類之「已發布目前版本」數 + 總計。計數＝`DM_DOCUMENT` STATUS in (PUBLISHED, PENDING_OBSOLETE)（含在架廢止待簽核）group by `CATEGORY_CODE`；排除 OBSOLETE / 送審 / 草稿 / 舊版；**套 `visible_docs_condition`**（閱覽者僅計其可見範圍）。
- **T046 最新更新公告**（FR-003/004）：`GET /api/dm/dashboard/announcements` → 近 30 天已發布版本（`DM_DOC_VERSION` PUBLISHED AND published_date≥now-30d AND 文件在架），發布時間 DESC + doc_id 次要鍵；join 文件 / 版本摘要 / 撰寫者（版本 `CREATED_USER`）+ **badge**（join 該版本 APPROVED `DM_REVIEW.REVIEW_TYPE` in (NEW, NEW_VERSION)；無對應 review 預設 NEW）；**套 `visible_docs_condition`**。
- 存取：掛 `get_dm_context`（任一 DM 角色，FR-001）；純讀取、不寫稽核。

**前端**（`frontend/src/dm/dashboard` widget + 掛入中性歡迎頁）：於 **WelcomePage（`/`）** 依 `useModuleSummary().dm.has_role` 條件渲染「DM 文件概況」區塊——4 統計卡（純資訊、不可點）+ 總計；近 30 天公告清單（文件名 / badge / 摘要 / 發布日期 / 撰寫者 / 分類，點入 US4）+「查看全部文件」→ US3；空狀態 DM-MSG-DM00-001；載入失敗顯示 error 提示。**不設獨立 `/dm` 落地路由、不加側欄項**（#89 / FR-001）。

**測試**：後端 int（統計狀態過濾 + 可見性；公告近 30 天 / badge / DESC / 可見性 / 空；HTTP 401/403）+ 前端（widget 於有 DM 角色時渲染、無 DM 角色不渲染；4 卡 + 總計、公告點入 / 查看全部導向、空狀態、載入失敗）。

## 驗收條件

- [ ] 具任一 DM 角色者於中性歡迎頁顯示「DM 文件概況」區塊；**無 DM 角色者不顯示**（FR-001、AC1；#89 最小知悉）
- [ ] 4 張統計卡 + 總計；卡片純資訊不可點（FR-002、AC2）
- [ ] 計數僅計已發布目前版（含 PENDING_OBSOLETE、排除 OBSOLETE / 送審 / 草稿 / 舊版）+ **套可見性**（FR-002、AC3）
- [ ] 公告近 30 天（新增 / 新版本），每筆含 文件名 / badge / 摘要 / 發布日期 / 撰寫者 / 分類 + **套可見性**（FR-003、AC4）
- [ ] 點公告進 US4 詳細頁；「查看全部文件」進 US3 文件庫（FR-004、AC5）
- [ ] 近 30 天無事件 → 空狀態「近期無新發布文件」（FR-004、AC6、DM-MSG-DM00-001）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#127 Foundation（已交付）**：存取閘、`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_CATEGORY`、`visible_docs_condition`
- **DP #89 導覽重構（已落地）**：中性歡迎頁（WelcomePage）+ 依權限側欄 + `useModuleSummary`（`has_any_role`）——本 widget 掛入其上
- **#4 US5 / #5 US6（已交付）**：資料來源＝已發布文件；**#155 US4 / #150 US3（已交付）**：公告點入 / 查看全部去向

## 注意事項

- ⚠️ **設計取向（#89）**：DM 儀表板為**中性歡迎頁之依權限 widget**，非獨立落地頁 / 無側欄入口 / 無自動導向。spec_us7 原「自動導向 DM00」措辭已同步更新。
- ⚠️ **可見性（Sec）**：統計與公告皆須套 `visible_docs_condition`，閱覽者不得見 / 計其不可見之受限可見對象文件（比照 library / detail 之 US3 FR-008）；privileged 不過濾。
- **badge 來源**：`DM_CHANGE_LOG.OPERATION` 不帶新增 / 新版本；改由版本之 APPROVED `DM_REVIEW.REVIEW_TYPE` 取得（限 NEW / NEW_VERSION，避免 US8 OBSOLETE review 重複列）。
- 統計 `PENDING_OBSOLETE` 計入（在架）；公告限文件在架（US8 廢止上線後不誤列）。撰寫者取版本 `CREATED_USER`。
- 純讀取、無 migration、無稽核寫入。

## 相關文件

- [spec_us7.md](spec_us7.md)、DP [spec_us1.md](../dp/spec_us1.md)（#89）、[data-model.md](data-model.md)、[tasks.md](tasks.md)（T045/T046）、[spec_us4.md](spec_us4.md) / [spec_us3.md](spec_us3.md)
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-overview`，內容示意）

**Labels**：`P2-延伸`, `DM-文件管理`, `US7`

---

## Issue #7：[P2-延伸] DM — 文件廢止申請（US8 / UCDM05 / DM02）（GitHub [#206](https://github.com/sti-fhb/EDMS/issues/206)）

**對應規格**：[spec_us8.md](spec_us8.md)（FR-001~005，UCDM05，訊息 DM-MSG-DM02-011~015）；[data-model.md](data-model.md)（`DM_DOCUMENT` 狀態機 PENDING_OBSOLETE / OBSOLETE、`DM_REVIEW`（REVIEW_TYPE=OBSOLETE + `OBSOLETE_FILE_*`）、`DM_CHANGE_LOG`（OPERATION=OBSOLETE））
**對應畫面**：DM02 文件詳細頁（[DmDetailPage](../../../frontend/src/dm/detail/DmDetailPage.tsx)）之「廢止此文件」→ 廢止申請確認 modal（內容示意見 [wireframes/dm/index.html](../../wireframes/dm/index.html) `openObsoleteModal`：必填廢止原因 + 選填單檔附件 + 選指定審核者）；已廢止後之 read-only banner（申請人 / 核准者 / 原因 / 附件）由 DM02 呈現
**階段**：P2-延伸
**涵蓋 Tasks**：T047（廢止申請對話框：必填原因 + 選填附件 + 選審核者 + 轉 PENDING_OBSOLETE 並通知）、T048（廢止待簽核行為：仍在架可下載、阻擋同時新版本送審、核准 / 退回）

## 任務說明

實作**整份文件廢止申請**（編輯者由 DM02 發起）：必填廢止原因、選填單檔附件（格式 / 大小比照文件上傳）、選指定審核者（排除本人）→ 文件轉 **PENDING_OBSOLETE（廢止待簽核）** 並通知審核者。廢止待簽核期間**原發布版本仍持續對外**（在文件庫、可下載），至核准後才正式下架。核准 → 文件 **OBSOLETE（已廢止）** + 版本歷程末尾新增廢止紀錄（申請人 / 申請時間 / 原因 / 廢止附件（如有）/ 核准者 / 廢止時間）並通知撰寫者；退回 → 文件回 **PUBLISHED（已發布）** 並通知撰寫者。撤回交由 US9。

> ⚠️ **本 issue 需延伸 US6（#178 已交付）之簽核處理**：US6 目前以 `DM_REVIEW_006`「廢止類送審之簽核暫未支援（待 US8）」在 [center_service.py](../../../backend/app/dm/review/center_service.py) `_ensure_actionable` **直接擋掉 OBSOLETE 的核准 / 退回**（同時 review 清單 repository 也排除 OBSOLETE）。spec_us8 FR-005 雖寫「核准 / 退回交由 US6」，但該路徑實為 stub——**US8 必須解除此封鎖並實作 OBSOLETE 核准 / 退回**（含版本歷程廢止紀錄與文件狀態轉換），此為本 issue 淨新增、非 US6 已完成之工作。

## 範圍

**後端**（`app/dm`，router → service → repository）：
- **T047 發起廢止**（FR-001/002）：新增發起端點（如 `POST /api/dm/documents/{doc_id}/obsolete`），掛 `get_dm_context` + 編輯者權限：
  - **必填廢止原因**（缺 → DM-MSG-DM02-011）；**必選指定審核者**（缺 → DM-MSG-DM02-014）、**排除撰寫者本人**（重用 `ensure_reviewer_not_author` → `DM_REVIEW_001`）。
  - **選填單檔附件**：格式 / 大小比照文件上傳，重用 [file_store](../../../backend/app/dm/document/file_store.py) `validate_upload`（違規 → `DM_FILE_001` / `DM_FILE_002`，對映 DM-MSG-DM02-015）+ 落地經 **storage-root fence（#160）** `resolve_within_root`，存 `DM_REVIEW.OBSOLETE_FILE_*`（T010 已建欄位）。
  - 重用 `ReviewService.submit(review_type="OBSOLETE", version_id=current_version_id, reason=...)` 建立送審週期；**阻擋同時新版本送審**由「一文件至多一筆 PENDING」唯一索引天然涵蓋（→ `DM_REVIEW_002`，對映 DM-MSG-DM02-012，FR-004）；成功後文件轉 **PENDING_OBSOLETE**、以 `DmNotifier` 通知審核者，回 DM-MSG-DM02-013。
- **T048 廢止待簽核行為 + 核准 / 退回**（FR-003/005）：
  - **仍對外**（FR-003）：驗證 PENDING_OBSOLETE 於文件庫（US3）/ 詳細頁（US4）仍列出且目前版本可下載（既有在架集合已含 PENDING_OBSOLETE，本 issue 驗證不回歸）。
  - **解除 US6 之 OBSOLETE 封鎖**：移除 / 改寫 `_ensure_actionable` 的 `DM_REVIEW_006` 分支與 review repository 對 OBSOLETE 的排除，實作：
    - **核准** → 文件轉 **OBSOLETE**；版本歷程末尾寫入廢止紀錄（申請人 / 申請時間 / 廢止原因 / 廢止附件 / 核准者 / 廢止時間）；`DM_CHANGE_LOG` OPERATION=OBSOLETE；通知撰寫者。
    - **退回** → 文件回 **PUBLISHED**；通知撰寫者。
  - **撤回**：範圍外，交由 US9。

**前端**（`frontend/src/dm/detail` 廢止申請 modal + 落地入口）：
- DM02「廢止此文件」（`detail.is_editor && detail.can_edit`）目前 `navigate` 到 `/dm/documents/:docId/obsolete`（**router 尚無此路由**）。US8 落地此流程——依 spec / wireframe 為**確認 modal**（必填原因 + 選填單檔附件 + 選指定審核者），Zod 驗證（原因必填、附件格式 / 大小），送出成功 → toast DM-MSG-DM02-013 並回文件庫 / 刷新詳細頁為廢止待簽核。**設計取向傾向 dialog（對齊 wireframe `openObsoleteModal`、免新增 route）**，最終落地方式（dialog vs 新增 page 路由）於 `/sti-plan` 定案。
- 已廢止後之 read-only banner（申請人 / 核准者 / 原因 / 附件提示）DM02 已具備 `obsolete_info` 呈現，本 issue 提供其資料來源。

**測試**：後端 int（發起 → PENDING_OBSOLETE + 通知；缺原因 / 缺審核者 / 選自己 / 附件格式或大小違規之錯誤；新版本送審中發起廢止被擋；PENDING_OBSOLETE 仍列於文件庫且目前版可下載；核准 → OBSOLETE + 版本歷程廢止紀錄 + 通知撰寫者；退回 → PUBLISHED + 通知；HTTP 401/403）+ 前端（廢止 modal 必填原因驗證、附件選填、送出成功 toast、無編輯權時不顯示入口）。

## 驗收條件

- [ ] 編輯者由 DM02 發起廢止：必填原因（缺 → DM-MSG-DM02-011）、選填單檔附件（格式 / 大小比照上傳，違規 → DM-MSG-DM02-015）、選審核者（缺 → DM-MSG-DM02-014、排除自己 → `DM_REVIEW_001`）（FR-001/002）
- [ ] 送出成功 → 文件轉 PENDING_OBSOLETE、通知指定審核者、回 DM-MSG-DM02-013（FR-002）
- [ ] 新版本送審進行中無法同時發起廢止（一文件一 PENDING）→ DM-MSG-DM02-012（`DM_REVIEW_002`，FR-004）
- [ ] 廢止待簽核期間文件仍列於文件庫且目前版本可下載（FR-003）
- [ ] 核准 → 文件 OBSOLETE + 版本歷程末尾廢止紀錄（申請人 / 申請時間 / 原因 / 附件 / 核准者 / 廢止時間）+ 通知撰寫者（FR-005）
- [ ] 退回 → 文件回 PUBLISHED + 通知撰寫者（FR-005）
- [ ] US6 原 `DM_REVIEW_006`「待 US8」封鎖已解除，OBSOLETE 核准 / 退回可正常處理；error-codes.md 之 `DM_REVIEW_006` 描述同步更新
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#127 Foundation（已交付）**：`DM_REVIEW`（REVIEW_TYPE=OBSOLETE + `OBSOLETE_FILE_*`，T010 migration 已建）、`DM_CHANGE_LOG`、file_store、**storage-root fence（#160）**、`DmNotifier`、狀態機
- **#155 US4 詳細頁（已交付）**：廢止發起入口（DM02「廢止此文件」）與已廢止 read-only banner（`obsolete_info`）
- **#178 US6 簽核處理（已交付，本 issue 需延伸）**：`ReviewService.submit` / 簽核中心核准 / 退回骨架——US8 解除其 `DM_REVIEW_006` OBSOLETE 封鎖並補實作核准 / 退回
- **#169 US5（已交付）**：`file_store` 上傳驗證慣例（格式 / 大小）沿用於廢止附件

## 注意事項

- ⚠️ **延伸 US6（非新模組）**：核准 / 退回落在既有簽核中心流程；務必移除 `center_service._ensure_actionable` 的 `DM_REVIEW_006` 分支與 review repository 對 OBSOLETE 的排除，並同步更新 [error-codes.md](../../ref/error-codes.md) `DM_REVIEW_006` 描述（不再「待 US8」，或改標記為已停用）。
- ⚠️ **廢止附件走 storage-root fence（#160）**：`OBSOLETE_FILE_PATH` 落地 / 讀取一律經 `resolve_within_root`，fail-closed。
- **FR-004 由唯一索引天然涵蓋**：「一文件至多一筆 PENDING」（`UX_DM_REVIEW_ONE_PENDING`）已擋同時新版本送審 + 廢止；前端訊息對映 DM-MSG-DM02-012、後端沿用 `DM_REVIEW_002`。
- **缺原因 / 缺審核者之 error_code**：DM-MSG-DM02-011 / 014 對應之後端 error_code 於 `/sti-plan` 定（可能新增 `DM_DOC_0xx` 或比照 `DM_DOC_004` 必填欄位樣式）；附件違規重用 `DM_FILE_001` / `DM_FILE_002`、選自己重用 `DM_REVIEW_001`、並發送審重用 `DM_REVIEW_002`。
- **前端入口路由**：DM02 現有 `navigate("/dm/documents/:docId/obsolete")` 指向未存在路由；US8 落地時決定改 dialog（傾向）或補 page 路由（`/sti-plan` 定案）。
- **版本歷程廢止紀錄**：核准後於版本歷程末尾呈現，非新增版本列；欄位取自 `DM_REVIEW`（申請人 `CREATED_USER` / `SUBMIT_DATE` / `REASON` / `OBSOLETE_FILE_*` / `APPROVER_USER_ID` / `COMPLETE_DATE`）。

## 相關文件

- [spec_us8.md](spec_us8.md)、[data-model.md](data-model.md)、[tasks.md](tasks.md)（T047/T048）、[spec_us6.md](spec_us6.md)（簽核處理，本 issue 延伸）、[spec_us4.md](spec_us4.md)（詳細頁入口）、[spec_us9.md](spec_us9.md)（撤回）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`openObsoleteModal` 廢止確認 modal、`review-detail-obsolete-target` 簽核端廢止對象資訊、`detail-obsolete-banner` 已廢止橫幅）

**Labels**：`P2-延伸`, `DM-文件管理`, `US8`

---

## Issue #8：[P2-延伸] DM — 個人專區（US9 / UCDM09 / DM07）（GitHub [#219](https://github.com/sti-fhb/EDMS/issues/219)）

**對應規格**：[spec_us9.md](spec_us9.md)（FR-001~004，UCDM09，訊息 DM-MSG-DM07-004/005）；[data-model.md](data-model.md)（`DM_DOC_VERSION` 草稿狀態、`DM_REVIEW`（PENDING→WITHDRAWN 撤回、REVIEW_TYPE 決定撤回回復狀態）、`DM_USER_ROLE` 角色判定）
**對應畫面**：DM07 個人專區（左側 DM 功能列之個人工作區；示意見 [wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-personal`：草稿匣 / 撤回送審 / 我的文件動態三塊）——**入口僅對具編輯者或審核者角色者顯示**
**階段**：P2-延伸
**涵蓋 Tasks**：T050（草稿匣）、T051（撤回送審）、T052（我的文件動態 + 個人專區入口可見性）。**T049（個人資料維護）已廢除**——姓名 / Email / 密碼變更由平台 DP 提供（UCDP004、右上使用者選單、共用 `DP_USER`），DM 不自建個資畫面。

## 任務說明

實作**編輯者 / 審核者之個人工作區**（DM 左側功能列），含三塊 DM 業務：
- **草稿匣**（FR-001，編輯者）：列未送審 / 被退回待修改 / 已撤回三類草稿；「繼續編輯 / 修改」進 US5（DM03），「刪除」須確認（DM-MSG-DM07-004、不可復原、僅影響草稿不動已發布版本）。
- **撤回送審**（FR-002，編輯者）：把卡住之送審撤回——新增 / 新版本 → 版本回草稿；廢止 → 文件回已發布；以**站內訊息**通知原指派審核者（不發 Email）；可重新編輯並改選新審核者再送；原送審週期之指定審核者紀錄保留不改寫。
- **我的文件動態**（FR-003）：依角色 tab 呈現近 30 天事件（撰寫者視角：送審中 / 核准發布 / 退回 / 廢止待簽核 / 已廢止 / 已撤回；審核者視角：待處理 / 催辦中 / 已被撤回 / 已處理歷史）；兼具兩角色者兩 tab 皆顯示。
- **入口可見性**（FR-004）：僅具**編輯者或審核者**角色者於左側見「個人專區」；純閱覽者 / 純管理者不顯示。

> ℹ️ **收尾型全端 issue**：主要為組裝既有能力——`ReviewService.withdraw`（PENDING→WITHDRAWN，已存在）、US5 草稿續編 / 刪除、`DM_REVIEW` / `DM_DOC_VERSION` 查詢、依權限側欄（#89）。**個資維護不在本 US**（平台 DP UCDP004）。

## 範圍

**後端**（新 `app/dm/personal/` 或延伸 editor/review，router → service → repository）：
- **T050 草稿匣**（FR-001）：`GET` 列該使用者之 DRAFT 版本，分三類——**未送審**（從未有送審紀錄之 DRAFT）/ **被退回**（最近一次 `DM_REVIEW` 為 REJECTED 後回 DRAFT）/ **已撤回**（最近一次 `DM_REVIEW` 為 WITHDRAWN 後回 DRAFT）；三類判定依 `DM_REVIEW` 歷史（非單看版本狀態，因三類版本皆 DRAFT）。刪除＝軟刪 `DELETED=1`（須確認、僅草稿版本、不影響已發布）。
- **T051 撤回送審**（FR-002）：`POST /api/dm/reviews/{review_id}/withdraw`（限撰寫者本人）→ 重用 `ReviewService.withdraw`（PENDING→WITHDRAWN）；依 `review_type` 回復——NEW / NEW_VERSION → 版本回 DRAFT（首版文件亦回 DRAFT）、OBSOLETE → 文件回 PUBLISHED；**站內訊息**通知原指派審核者（範本 `SUBMIT_WITHDRAWN`、CHANNEL=MSG_ONLY、不發 Email；**本 issue 需新增此範本之 seed migration**）；原 `ASSIGNED_REVIEWER` 保留不改寫；撤回後可經 US5 改選新審核者再送。
- **T052 我的文件動態**（FR-003）：`GET` 近 30 天事件，依角色（撰寫者 / 審核者）分視角回傳；資料來源 `DM_REVIEW` / `DM_CHANGE_LOG` / `DM_DOC_VERSION`。**入口可見性**（FR-004）：後端提供「具編輯者或審核者」判定（供 DP 依權限側欄 `has_any_role` 回呼 / 前端渲染）。
- 存取：掛 `get_dm_context`；撤回 / 草稿刪除為寫入型（`get_operator` + 本人校驗 + 稽核）。

**前端**（`frontend/src/dm/me` DM07 頁）：三區塊（草稿匣清單 + 續編/刪除、撤回送審動作、我的文件動態角色 tab）；掛左側功能列、**入口依「具編輯者或審核者」條件渲染**（對齊 #89 依權限側欄）；刪除確認（DM-MSG-DM07-004）、撤回成功 toast（DM-MSG-DM07-005）。`DmPersonalPage` 現為 stub、於本 issue 填實。

**測試**：後端 int（草稿匣三類分類正確、刪除軟刪且不影響已發布、撤回各 review_type 狀態回復 + 站內訊息 + 保留原審核者、我的文件動態近 30 天 / 角色視角、入口可見性授權、HTTP 401/403）+ 前端（草稿匣三類渲染 / 續編導向 / 刪除確認、撤回 toast、動態 tab、無編輯/審核角色不顯示入口）。

## 驗收條件

- [ ] 個人專區入口僅對具編輯者或審核者角色者顯示；純閱覽 / 純管理不顯示（FR-004、AC1）
- [ ] 草稿匣列未送審 / 被退回 / 已撤回三類（FR-001、AC2）
- [ ] 草稿「繼續編輯」進 US5；「刪除」須確認、軟刪、不影響已發布版本（FR-001、AC3、DM-MSG-DM07-004）
- [ ] 撤回送審：NEW / NEW_VERSION → 草稿、OBSOLETE → 已發布；站內訊息通知原審核者；原審核者紀錄保留；可改選新審核者再送（FR-002、AC4、DM-MSG-DM07-005）
- [ ] 我的文件動態依角色 tab 呈現近 30 天事件；兼具兩角色者兩 tab 皆顯示（FR-003、AC5）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#4 US5（已交付）**：草稿續編 / 刪除、改選審核者再送之編輯流程
- **#5 US6（已交付）**：撤回影響之送審項目；`ReviewService.withdraw`（PENDING→WITHDRAWN）
- **#7 US8（已交付）**：撤回廢止申請（OBSOLETE → PUBLISHED）之對應狀態回復
- **#127 Foundation（已交付）**：`DM_USER_ROLE` 角色判定、`DM_REVIEW` / `DM_DOC_VERSION` / `DM_CHANGE_LOG`、通知（站內訊息管道）
- **DP #89 導覽重構（已落地）**：依權限側欄 + `has_any_role`——個人專區入口掛其上

## 注意事項

- ⚠️ **個資維護不在本 US**（T049 已廢除）：姓名 / Email / 密碼由平台 DP UCDP004（右上使用者選單、共用 `DP_USER`）提供，DM 不自建。
- **撤回站內訊息管道（已定案，precheck 必補）**：新增通知範本 **`SUBMIT_WITHDRAWN`**（CHANNEL=MSG_ONLY、對象＝原指派審核者、不發 Email），已補列 `data-model` 通知事件表（10 項）；**本 issue 實作需新增對應 seed migration**（比照 #127 之 `dm_seed_templates_params_into_dp`）。
- **撤回 vs 退回**：撤回為**撰寫者主動**（WITHDRAWN）、退回為**審核者**（REJECTED）——兩者皆使版本回 DRAFT，但 `DM_REVIEW` 終態不同；草稿匣三類分類即依此區分（被退回 vs 已撤回）。
- **草稿三類分類依 `DM_REVIEW` 歷史（已定於 spec_us9 FR-001）**：未送審＝無對應送審紀錄；被退回＝最近一次送審 `REJECTED`；已撤回＝最近一次送審 `WITHDRAWN`（三類版本皆 DRAFT，不能單看版本狀態）。
- 入口可見性由前端依「具編輯者或審核者」渲染；與 US7 widget（任一 DM 角色）之可見條件不同，勿混用。

## 相關文件

- [spec_us9.md](spec_us9.md)、[data-model.md](data-model.md)、[tasks.md](tasks.md)（T050-T052）、[spec_us5.md](spec_us5.md)（草稿續編/刪除）、[spec_us6.md](spec_us6.md)（送審撤回）、[spec_us8.md](spec_us8.md)（撤回廢止）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-personal`）

**Labels**：`P2-延伸`, `DM-文件管理`, `US9`

---

## Issue #9：[P2-延伸] DM — 已廢止文件查詢（US10 / UCDM08 / DM06）（GitHub [#230](https://github.com/sti-fhb/EDMS/issues/230)，🚀 已開立）

**對應規格**：[spec_us10.md](spec_us10.md)（FR-001~005，UCDM08，訊息 DM-MSG-DM06-001/002）；[data-model.md](data-model.md)（`DM_DOCUMENT`（STATUS=OBSOLETE）、`DM_DOC_VERSION`（末版版號）、`DM_REVIEW`（OBSOLETE 已核准週期：申請人 / 核准者 / 廢止時間 / 廢止原因 / 廢止附件）、`DM_USER_ROLE`（DM_ADMIN 判定））
**對應畫面**：DM06 已廢止文件查詢（左側 DM 功能列，示意見 [wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-obsolete`）——**入口與後端皆僅 DM_ADMIN 可存取**
**階段**：P2-延伸
**涵蓋 Tasks**：T053（已廢止查詢清單 + 搜尋）、T054（CSV 匯出 + read-only 詳細頁導向 + 入口 / 存取閘）

## 任務說明

實作 **DM06 已廢止文件查詢**（管理者，供稽核 / 醫療糾紛追溯 / 法規查核）：DM_ADMIN 以關鍵字（文件名 / 廢止原因）、分類、廢止日期區間搜尋**已廢止（STATUS=OBSOLETE）**文件，清單呈現廢止脈絡欄位，點列進入 **US4 read-only 詳細頁**檢視歷史版本，並可**匯出 CSV** 供封存。已廢止文件不出現於文件庫主清單（US3 已排除），一般使用者無法存取。

> ℹ️ **讀取型全端 issue**：後端為唯讀查詢 + CSV 匯出；**read-only 詳細頁（US4 FR-006：隱藏檔案+文件資訊、版本歷程自動展開、僅預覽、廢止 banner + 廢止附件下載）已於 #3 交付、本 issue 直接重用**，不改動 DM02 瀏覽語意。本 issue 不產生廢止（廢止申請 / 核准屬 US8 / US6）。

## 範圍

**後端**（新模組 `app/dm/obsolete_archive/`〔暫名，開工時定〕，router → service → repository；與 US8 廢止申請之 `app/dm/obsolete/` 分離——一為查詢、一為寫入）：
- **T053 查詢清單**（FR-002/003）：`GET /api/dm/obsolete-archive/documents`——列 STATUS=OBSOLETE 文件，搜尋條件：關鍵字（`DM_DOCUMENT.DOC_NAME` / 廢止原因 `DM_REVIEW.OBSOLETE_REASON`）、分類、廢止日期區間（廢止核准完成時間 `DM_REVIEW.COMPLETE_DATE`）。回欄位（FR-003）：文件名稱（含末版版號）/ 分類 / 原撰寫者 / 廢止時間 / 廢止申請人 / 核准者 / 廢止原因。資料來源＝`DM_DOCUMENT` join `DM_DOC_VERSION`（末版）join `DM_REVIEW`（該文件 OBSOLETE 且 APPROVED 之週期）。後端分頁 `paginate()`（依廢止時間新→舊）。
- **T054 CSV 匯出**（FR-005）：`GET /api/dm/obsolete-archive/documents/export`——依相同查詢條件回 CSV（欄位同清單），供稽核封存。
- **存取閘**（FR-001）：兩端點皆掛 `get_dm_context` + **細粒度 `DM_ADMIN` 檢核**（非管理者 → 403，對應 DM-MSG-DM06-002）；**後端 MUST 擋直接 URL 存取**、非僅前端隱藏。查無結果回空清單（前端呈現 DM-MSG-DM06-001）。
- **入口可見性判定**：提供 DM_ADMIN 判定供前端側欄 per-item 閘（資料來源待 SA 定案，見注意事項）。

**前端**（`frontend/src/dm/obsolete/DmObsoletePage.tsx` 現為 stub、於本 issue 填實）：DM06 查詢頁——搜尋列（關鍵字 / 分類 / 廢止日期區間）+ 結果清單（FR-003 欄位）+「匯出 CSV」鈕；點列導向 `/dm/documents/{docId}`（US4 read-only 詳細頁，已支援 OBSOLETE）；空結果提示 DM-MSG-DM06-001。側欄「已廢止文件查詢」項**僅 DM_ADMIN 顯示**（per-item 角色閘，比照 US9 個人專區入口機制）。

**測試**：後端 int（DM_ADMIN 查得已廢止清單、關鍵字 / 分類 / 廢止日期區間過濾、欄位正確含末版版號與廢止脈絡、CSV 匯出內容、非 DM_ADMIN 403〔清單 + 匯出 + 直連〕、未登入 401、查無回空）+ 前端（查詢渲染 / 空結果提示 / 匯出鈕 / 點列導向 read-only 詳細、非管理者不顯示入口）。

## 驗收條件

- [ ] DM06 僅 DM_ADMIN 可進入；一般使用者側欄不顯示且**後端擋直接 URL 存取**（FR-001、AC1/AC6、DM-MSG-DM06-002）
- [ ] 可依關鍵字（文件名 / 廢止原因）/ 分類 / 廢止日期區間查詢已廢止文件（FR-002、AC2）
- [ ] 清單欄位含文件名稱（含末版版號）/ 分類 / 原撰寫者 / 廢止時間 / 廢止申請人 / 核准者 / 廢止原因（FR-003、AC3）
- [ ] 點任一筆進入 US4 read-only 詳細頁（隱藏檔案+文件資訊、版本歷程自動展開、僅預覽、廢止 banner + 廢止附件下載）（FR-004、AC4；重用 #3）
- [ ] 支援 CSV 匯出當前查詢結果（FR-005、AC5）
- [ ] 查無結果顯示 DM-MSG-DM06-001（FR-002）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#3 US4（已交付）**：read-only 詳細頁模式（FR-006：OBSOLETE read-only + 廢止 banner + 廢止附件下載）——本 issue 之點列去向直接重用，不重建
- **#5 US6（已交付）/ #7 US8（已交付）**：已廢止文件之來源（廢止申請 → 核准）；`DM_REVIEW` OBSOLETE 已核准週期之申請人 / 核准者 / 時間 / 原因 / 附件
- **#2 US3（已交付）**：文件庫已排除 OBSOLETE、確保已廢止文件僅由 DM06 查閱
- **#127 Foundation（已交付）**：`DM_USER_ROLE`（DM_ADMIN 判定）、`DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_REVIEW`
- **DP #89 導覽重構（已落地）**：依權限側欄——DM06 入口掛其上（per-item DM_ADMIN 閘）

## 注意事項

- **入口 / 存取閘為 DM_ADMIN**（與 US9 個人專區「編輯者或審核者」不同閘）：FR-001 要求**後端擋直連**，非僅前端隱藏；細粒度授權以 `has_role(ctx.roles, DM_ADMIN)` 判定。
- **per-item 側欄角色閘資料來源**（待 SA 定案，同 US9 SA Q1 脈絡）：DM-local 判定端點（如 `GET /api/dm/obsolete-archive/access` → `{ can_access }`，不動 DP module-summary）vs 擴充 DP `module-summary` 帶 DM 角色細節（`is_admin` 等）——US9 採前者（A 過渡），本 issue 沿用或收斂由 `/sti-plan` 提請 SA。
- **模組分離**：US8 廢止**申請**（寫入）已在 `app/dm/obsolete/`；本 issue 為廢止**查詢**（唯讀），另立模組避免讀寫混雜、命名勿衝突。
- **read-only 詳細頁不重建**：US4 FR-006 已實作（`dm/detail` 之 `is_obsolete` / `obsolete_info` + 版本歷程自動展開 + 廢止附件下載授權含 DM_ADMIN）；本 issue 僅導向、不改 DM02。
- **CSV 匯出**：欄位對齊清單；注意廢止原因等文字之 CSV 跳脫（逗號 / 換行 / 引號），避免格式破損。

## 相關文件

- [spec_us10.md](spec_us10.md)、[spec_us4.md](spec_us4.md)（FR-006 read-only）、[spec_us8.md](spec_us8.md)（廢止申請）、[spec_us6.md](spec_us6.md)（核准廢止）、[data-model.md](data-model.md)、[tasks.md](tasks.md)（T053-T054）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-obsolete`）

**Labels**：`P2-延伸`, `DM-文件管理`, `US10`

---

## Issue #10：[P3-輔助] DM — 文件變更歷程查詢（US11 / UCDM10 / DM08）（GitHub [#243](https://github.com/sti-fhb/EDMS/issues/243)，🚀 已開立）

**對應規格**：[spec_us11.md](spec_us11.md)（FR-001~006，UCDM10，訊息 DM-MSG-DM08-001/002）；[data-model.md](data-model.md)（`DM_CHANGE_LOG`（append-only，`OPERATION`=PUBLISH/OBSOLETE、`APPLICANT_USER_ID` / `APPROVER_USER_ID` / `OPERATION_TIME` / `VERSION_ID` / `NOTE`）、`DM_DOCUMENT`（文件名）、`DM_DOC_VERSION`（版本號）、`DP_USER`（申請人 / 核准人姓名）、`DM_USER_ROLE`（DM_ADMIN 判定））
**對應畫面**：DM08 文件變更歷程查詢（左側 DM 功能列，示意見 [wireframes/dm/index.html](../../wireframes/dm/index.html) `dm-audit`）——**入口與後端皆僅 DM_ADMIN 可存取**
**階段**：P3-輔助
**涵蓋 Tasks**：T055（變更歷程查詢清單 + 搜尋）、T056（CSV 匯出 + 入口 / 存取閘）

## 任務說明

實作 **DM08 文件變更歷程查詢**（管理者，供資安稽核 / 合規追溯）：DM_ADMIN 跨文件查詢**公開變更歷程**（`DM_CHANGE_LOG` 之**發布 / 廢止**兩類事件），依日期區間、申請人 / 核准人（帳號或姓名）、操作類型篩選，清單呈現稽核欄位，並**匯出 CSV**。撰寫過程動作（上傳 / 編輯 / 送審 / 退回 / 撤回）與閱讀動作（下載 / 預覽）不入此公開歷程；系統設定變更亦不於本頁顯示。變更歷程**永久保留、不可竄改**。

> ℹ️ **讀取型全端 issue**：後端為唯讀查詢 + CSV 匯出；資料來源 `DM_CHANGE_LOG` 之發布 / 廢止事件已由 **US6 核准發布 / US8→US6 核准廢止**（`app/dm/review/center_service`）寫入，**本 issue 不產生變更事件**。與 US10 已廢止查詢同屬「唯讀跨文件稽核查詢」，可大量鏡像其 `obsolete_archive` 範式（DM_ADMIN 硬閘 + `core/csv_export` + access 端點 + 前端逐項側欄閘）。

## 範圍

**後端**（新模組 `app/dm/change_log/`〔暫名，開工時定〕，router → service → repository；與 US6/US8 之**寫入**端 `app/dm/review/` 分離——本 issue 純唯讀查詢）：
- **T055 查詢清單**（FR-002/003）：`GET /api/dm/change-log/entries`〔端點命名開工定〕——列 `DM_CHANGE_LOG` 事件，搜尋條件：日期區間（`OPERATION_TIME`）、申請人 / 核准人（`APPLICANT_USER_ID` / `APPROVER_USER_ID` 之帳號或 `DP_USER.USER_NAME` ILIKE，單一輸入比對兩者）、操作類型（全部 / PUBLISH / OBSOLETE）。回欄位（FR-003）：時間 / 申請人 / 核准人 / 操作 / 文件名稱 / 版本號 / 備註（`NOTE`：發布＝變更摘要、廢止＝廢止原因）。資料來源＝`DM_CHANGE_LOG` join `DM_DOCUMENT`（文件名）join `DM_DOC_VERSION`（版本號）join `DP_USER`（姓名，唯讀報表例外）。後端分頁 `paginate()`（依 `OPERATION_TIME` 新→舊）。
- **T056 CSV 匯出**（FR-004）：`GET /api/dm/change-log/entries/export`——依相同查詢條件回 CSV（欄位同清單），供資安稽核封存。**重用 `app/core/csv_export.py`**（US10 建立，含公式注入防護 + UTF-8 BOM）。
- **存取閘**（FR-001）：兩端點皆掛 `get_dm_context` + 細粒度 `DM_ADMIN` 檢核（非管理者 → 403 `DM_AUTH_003`，對應 DM-MSG-DM08-002）；**後端 MUST 擋直接 URL 存取**。查無結果回空清單（前端呈現 DM-MSG-DM08-001）。
- **入口可見性判定**：提供 DM_ADMIN 判定供前端側欄 per-item 閘（資料來源待 SA 定案，見注意事項）。

**前端**（`frontend/src/dm/changelog/DmChangeLogPage.tsx` 現為 stub、於本 issue 填實）：DM08 查詢頁——搜尋列（日期起訖 / 申請人或核准人 / 操作類型）+ 結果清單（FR-003 七欄，操作以 badge 呈現發布 / 廢止）+「匯出 CSV」鈕；空結果提示 DM-MSG-DM08-001。側欄「文件變更歷程查詢」項**僅 DM_ADMIN 顯示**（per-item 角色閘，比照 US10）。

**測試**：後端 int（DM_ADMIN 查得清單、日期 / 申請人或核准人 / 操作類型過濾、欄位正確含版本號與備註、**僅 PUBLISH/OBSOLETE 事件**〔驗撰寫過程 / 閱讀動作不入歷程〕、CSV 匯出內容、非 DM_ADMIN 403〔清單 + 匯出 + 直連〕、未登入 401、查無回空）+ 前端（查詢渲染 / 空結果提示 / 匯出鈕 / 操作 badge、非管理者不顯示入口）。

## 驗收條件

- [ ] DM08 僅 DM_ADMIN 可進入；一般使用者側欄不顯示且**後端擋直接 URL 存取**（FR-001、AC1、DM-MSG-DM08-002）
- [ ] 可依日期區間 / 申請人或核准人（帳號或姓名）/ 操作類型（全部 / 發布 / 廢止）查詢（FR-002、AC2）
- [ ] 清單欄位含時間 / 申請人 / 核准人 / 操作 / 文件名稱 / 版本號 / 備註（發布＝變更摘要、廢止＝廢止原因），依時間 DESC（FR-003、AC3）
- [ ] 僅含發布 / 廢止兩類；撰寫過程動作（上傳 / 編輯 / 送審 / 退回 / 撤回）與閱讀動作（下載 / 預覽）不出現、系統設定變更不顯示（FR-001/FR-005、AC5/AC6）
- [ ] 支援 CSV 匯出當前查詢結果（FR-004、AC4）
- [ ] 查無結果顯示 DM-MSG-DM08-001（FR-002）
- [ ] `uv run pytest -q` 全綠；前端測試通過；ruff / ESLint / type-check / 覆蓋率門檻通過

## 依賴

- **#5 US6（已交付）**：核准發布 / 核准廢止寫 `DM_CHANGE_LOG`（PUBLISH / OBSOLETE 事件）——本 issue 之資料來源，程式在 `app/dm/review/center_service`
- **#7 US8（已交付）**：廢止核准之 OBSOLETE 事件來源
- **#9 US10（已交付）**：鏡像其 `obsolete_archive` 唯讀查詢範式（手動 count+分頁 enriched 列）+ `app/core/csv_export`（公式注入防護）+ DM_ADMIN 硬閘（`DM_AUTH_003`）+ access 端點 + 前端側欄逐項閘
- **#127 Foundation（已交付）**：`DM_CHANGE_LOG` / `DM_DOCUMENT` / `DM_DOC_VERSION` / `DM_USER_ROLE`
- **DP #89 導覽重構（已落地）**：依權限側欄——DM08 入口掛其上（per-item DM_ADMIN 閘）

## 注意事項

- **入口 / 存取閘為 DM_ADMIN**（同 US10）：FR-001 要求**後端擋直連**，非僅前端隱藏；細粒度授權以 `has_role(ctx.roles, DM_ADMIN)` 判定。
- **per-item 側欄角色閘資料來源**（待 SA 定案，同 US9/US10 SA Q 脈絡）：US10 採 A（DM-local `obsolete-archive/access`）。US11 可（a）鏡像新增 `change-log/access`、（b）**收斂為共用** `GET /api/dm/admin-access`（一次供 US10/11/13）、或（c）待 DP 擴 `module-summary` 帶 `is_admin`（US9 前瞻方向 B）——由 `/sti-plan` 提請 SA；未定前沿用 US10 模式。
- **模組分離**：`DM_CHANGE_LOG` 寫入屬 US6/US8（`app/dm/review/`）；本 issue 為唯讀**查詢**，另立模組、不改寫入端。
- **僅 PUBLISH / OBSOLETE 由資料來源保證**：`DM_CHANGE_LOG` 依設計只寫這兩類事件（撰寫過程 / 閱讀 / 設定變更本就不寫入本表，FR-005 由來源保證）；查詢無需額外排除，但**測試應驗證**表內僅此兩類（防未來誤寫回歸）。
- **版本號欄**：PUBLISH 事件 `VERSION_ID` 指向該發布版 → 取 `version_no`；OBSOLETE 事件 `VERSION_ID` 可能為 null（廢止屬文件層）→ 版本號欄對廢止列可留空或顯示廢止時發布版，開工時依 `DM_CHANGE_LOG` 實際寫入值決定（SD 自決 / 必要時 SA Q）。
- **CSV 匯出**：重用 `core/csv_export`；備註（變更摘要 / 廢止原因）為自由文字，跳脫由共用模組處理。

## 相關文件

- [spec_us11.md](spec_us11.md)、[spec_us6.md](spec_us6.md)（核准發布 / 廢止寫歷程）、[spec_us8.md](spec_us8.md)（廢止）、[spec_us9.md](spec_us9.md)（撰寫過程動作個人視角）、[spec_us1.md](spec_us1.md)（系統設定異動紀錄）、[data-model.md](data-model.md)（`DM_CHANGE_LOG`）、[tasks.md](tasks.md)（T055-T056）
- [wireframes/dm/index.html](../../wireframes/dm/index.html)（`dm-audit`）

**Labels**：`P3-輔助`, `DM-文件管理`, `US11`

---

## Issue #11：[P3-輔助] DM — 跨模組教材引用（US12 / UCDM12）（GitHub [#183](https://github.com/sti-fhb/EDMS/issues/183)，✅ 已交付 PR #189）

**對應規格**：[spec_us12.md](spec_us12.md)（FR-001~005，UCDM12，訊息 DM-MSG-ETREF-001）；[contracts/document-service.md](contracts/document-service.md)（SRVDM001 / SRVDM002，**權威**）；[data-model.md](data-model.md)（`DM_DOCUMENT` / `DM_DOC_VERSION`）
**對應畫面**：無 DM 畫面（消費端 UI 在 ET 模組 ET02 / ET05）
**階段**：P3-輔助
**涵蓋 Tasks**：T057（SRVDM001）、T058（SRVDM002）、T059（廢止通知 ET，**範圍外**）

## 任務說明

DM 提供 ET 消費之 **in-process 服務門面** `DmDocumentService`（經 `app/services/__init__.py` 匯出；ET 依 `sti-backend-boundaries` 不打掛 `DM_AUTH_001` 角色閘的 HTTP 端點）：SRVDM001 依 DOC_ID 取當前發布版、SRVDM002 取 TRAINING 分類清單、`read_file_for_reference` 供 ET 學員取教材檔。解鎖 ET #0（DM Service Client）/ #3（ET02 教材下拉）/ #5（ET05 取檔）。

## 範圍

**後端**（`app/dm/integration`，門面 → repository）：
- **T057 `get_current_by_doc_id`**（SRVDM001）：依 DOC_ID 取當前發布版 metadata；廢止仍回廢止前最後版 + `obsolete=true`；無發布版 → `DM_DOC_013`（409）。
- **T058 `list_training_documents`**（SRVDM002）：取 TRAINING 分類、有當前發布版且在架（PUBLISHED/PENDING_OBSOLETE）之清單；keyword（LIKE 轉義）/ func_code 過濾；發布時間 DESC + doc_id 次要鍵。
- **取檔 `read_file_for_reference`**：供 ET 學員取檔——**不掛 DM 角色閘**（授權由 ET 自判）；**D-1 只給目前發布版**（非目前版 `DM_DOC_002`）、**D-2 不寫 `DM_DOC_READ`**；OBSOLETE 文件仍可取（FR-003）；經 storage-root 圍籬（#160）。
- **分類白名單**（Security）：三方法僅允許 `TRAINING`（DOC_ID 內嵌分類碼可枚舉，防跨分類越權取檔/窺 metadata）；非 TRAINING 取檔/metadata → `DM_DOC_001`、清單 → `DM_DOC_010`。
- `app/services/__init__.py` 匯出 `DmDocumentService`。

**測試**：後端 int（SRVDM001 當前/廢止/無發布版；SRVDM002 分類+狀態過濾+keyword+func_code+DESC；取檔 D-1/D-2/OBSOLETE/跨分類越權；匯出）。

**前端 / migration**：無。

## 驗收條件

- [x] SRVDM001 回當前發布版；廢止仍回最後版 + `obsolete`；無發布版 `DM_DOC_013`
- [x] SRVDM002 回 TRAINING 有效清單（含 PENDING_OBSOLETE、排除 OBSOLETE/草稿/送審）
- [x] DM Service 自 `app/services/__init__.py` 匯出、簽章與契約一致
- [x] 無 DM 角色 ET 學員可經 `read_file_for_reference` 取檔（不被 `DM_AUTH_001` 擋）
- [x] 回應欄位與契約一致（docId / items / obsolete / status）
- [x] CI 綠
- [ ] **（範圍外）** T059 DM 廢止後通知 ET 教師 → **裁示 A：ET 端依 `obsolete` 旗標自偵測、DM 不主動推播**；且相依 US8（廢止未交付）

## 依賴

- **#5 US6（已交付）**：發布 / `CURRENT_VERSION_ID` 維護
- **契約 + `DM_DOC_013`（#187，已入 main）**：in-process Service 介面 + ET 取檔授權路徑（交付前自檢補正）
- **US8（未交付）**：T059 廢止通知來源
- **ET（消費端，未落地）**：ET #0/#3/#5 以此開發、回歸驗證

## 注意事項 / 交付前自檢裁示

- **必補 1/2（契約，#187）**：REST 契約補「in-process Service 介面」（類名/簽章/DTO/error 對映）；ET 取檔授權路徑定案 **D-1 只給目前版 / D-2 不寫 DM_DOC_READ**。
- **必補 3（裁示 A）**：廢止通知採 ET 自偵測、DM 不推播；spec_us12 FR-003/AC4/`DM-MSG-ETREF-001` 已同步（#187）。
- **follow-up**：Security MED-2（裸 file_path）已由 #160 storage-root 圍籬收斂；AUDIENCE 可見性下放 ET（契約假設）。

## 相關文件

- [spec_us12.md](spec_us12.md)、[contracts/document-service.md](contracts/document-service.md)、[data-model.md](data-model.md)、[tasks.md](tasks.md)（T057~T059）
- ET 側對齊契約：`docs/specs/et/contracts/srv-et-dm-document-list.md` / `srv-et-dm-document-content.md`

**Labels**：`P3-輔助`, `DM-文件管理`, `ET-教育訓練文件管理`, `US12`

---

## Issue #12 ~ #13：待補（增量模式）

US13 閱讀統計與 KPI + 排程 SCHDM001（#12）/ 整合測試 + 安全 + 收尾（#13）——尚未開工，於前置就緒後補入完整 body。

---

## 異動紀錄

| 日期 | 異動 |
|------|------|
| 2026-08-05 | 首版建立。DM 分析文件對齊平台 DP 集中化後（spec / plan / research / data-model / tasks / wireframe，PR #122 + tasks.md 對齊）產出 issues.md：總覽表列 #0~#13 全貌 + Issue #0（Foundation）完整撰寫，採增量模式。**切分要點**：US2 登入不開獨立 issue（DP 提供、存取閘併 #0 T014）；US1 系統設定為轉接層模組端 + 業務規則 + 種子（維護 UI 在 DP 後台，精確契約待 /sti-plan）；US12 / US13 跨模組（依賴 ET 引用端 / DP 排程引擎）。DM 業務種子屬 #0；DM 通知範本 / 參數種子寫平台 DP 表之落點待 /sti-plan 確認。`DM-文件管理` label 待建（依 sti-label-rules）|
| 2026-08-05 | US1 交付前自檢（`/sti-sa-precheck dm us1`）2 必補修正（PR #126）：轉接層命名對齊 DP 契約（`get_users_roles_audiences` / `assign_roles_audiences`）+ 自我保護 error_code `DM_ROLE_001`（DP 映射 `DP-MSG-DP06-001`）；AUDIENCE soft-retire 跨模組落點留為 US1 開工前 SA Q。`DM-文件管理` label 已建（#5319E7）|
| 2026-08-05 | Issue #0（Foundation）已開立為 GitHub [#127](https://github.com/sti-fhb/EDMS/issues/127)（labels `priority:P0` + `DM-文件管理`），回填總覽表 GitHub # 欄與 body header |
| 2026-08-06 | Issue #0（#127）已交付合併（PR #129）。撰寫 Issue #1（US1 系統設定）完整 body：對應 spec_us1 FR-001~010 + module-callbacks §3/§4；涵蓋 T024~T027b。**切分要點**：US1 無獨立 DM 畫面（維護 UI 全在 DP 後台按模組過濾），淨新增主體為權限 / 可見對象**轉接層回呼**（`get_users_roles_audiences` / `assign_roles_audiences` / `has_any_role`）+ catalog 轉接層，其餘為 #127 已種之範本 / 參數 / 分類之維護驗證。Labels `P1-核心` + `DM-文件管理` + `US1` |
| 2026-08-06 | US1 交付前自檢（`/sti-sa-precheck dm us1`）3 必補（皆 #127 集中化修正未回傳造成的 drift）：**(1)** spec_us1 開頭「定義存 DP_PARAM」措辭過寬 → 對齊 spec.md §跨模組共用規則（分類/func/標籤/可見對象＝DM 自持表）；**(2)** module-callbacks §3 `DmRoleAudienceView.audiences` 來源 DP_PARAM → `DM_TAG`（AUDIENCE 組）TAG_ID；**(3)** 新增 module-callbacks §3.1 catalog 轉接層契約（受控主檔維護 + `list_audiences` + AUDIENCE soft-retire 觸發落點）。開工前 3 項 SA Q 已定案 2 項（catalog 轉接層 / soft-retire 落點），剩「參數值域校驗落點」待 `/sti-plan` |
| 2026-08-06 | Issue #1（US1）開立為 GitHub [#133](https://github.com/sti-fhb/EDMS/issues/133)（labels `P1-核心` + `DM-文件管理` + `US1`），回填總覽表與 body header。開立前同步修正 Issue #1 body 內殘留 drift（範圍/驗收條件之 `audiences`＝DP_PARAM → `DM_TAG` TAG_ID、catalog 轉接層引 §3.1），與交付前自檢後之 spec_us1 / module-callbacks 一致 |
| 2026-08-11 | 補「US2 → Foundation #0（#127）落地對照」表於 US2 說明段：逐條列 spec_us2 FR-001/002、DM-MSG-LOGIN-007、AC1~3 之落地位置與狀態，強化可追溯性。維持 US2 **不開獨立 issue** 之切分（DM 端僅存取閘 T014、已隨 #127 / PR #129 交付；AC1 導向之 DM00 儀表板屬 US7 / #6）。未新增總覽表列 |
| 2026-08-11 | 撰寫 Issue #2（US3 文件庫與檢索 / DM01）完整 body：對應 spec_us3 FR-001~009 + UCDM03；涵蓋 T028 / T028a / T029 / T030。**切分要點**：讀取型全端（搜尋端點 + DM01 頁），核心可見性判定重用 #0 T020a、不改文件/版本寫入（屬 US5/US6）；狀態集合 `{PUBLISHED, PENDING_OBSOLETE}`、檢索標籤僅 RETRIEVAL（AUDIENCE 不入檢索下拉）、閱覽者套可見性過濾。前置 #0（必要）+ #4/#5（資料來源，以種子/fixture 獨立測試）。開工前 SA Q 候選：狀態集合 vs 可見性 STATUS AND 之交互（PENDING_OBSOLETE 對閱覽者可見）。Labels `P1-核心` + `DM-文件管理` + `US3`。總覽表 Issue #2 狀態改「📝 body 已撰寫（待開立）」 |
| 2026-08-11 | Issue #2（US3 文件庫與檢索）開立為 GitHub [#150](https://github.com/sti-fhb/EDMS/issues/150)（labels `P1-核心` + `DM-文件管理` + `US3`），回填總覽表 GitHub # / 狀態與 body header。交付前自檢（`/sti-sa-precheck dm us3`）結論 ✅ 齊備、無必補 |
| 2026-08-11 | 撰寫 Issue #3（US4 文件詳細頁瀏覽 / DM02）完整 body：對應 spec_us4 FR-001~007 + UCDM04；涵蓋 T031/T032/T033/T034。**切分要點**：讀取型全端（詳細/版本/檔案端點 + DM02 頁），檔案預覽/下載重用 #0 file_store（T016）、僅下載目前發布版寫 DM_DOC_READ（唯一寫入、預覽不記、同人同版去重）、存取控制套 visibility（對齊 US3、含撤銷授權濾 DELETED）；動作入口失效以 DM_REVIEW PENDING 判定（非文件 STATUS）；read-only 廢止模式進入來源為 US10（未交付、渲染能力先備）。前置 #0（必要）+ #4/#5（資料來源，種子/fixture 獨立測試）。開工前 SA Q 候選：DM_DOC_001/002 error code、檔案串流端點形狀。Labels `P1-核心` + `DM-文件管理` + `US4`。總覽表 Issue #3 狀態改「📝 body 已撰寫（待開立）」 |
| 2026-08-11 | Issue #3（US4 文件詳細頁瀏覽）開立為 GitHub [#155](https://github.com/sti-fhb/EDMS/issues/155)（labels `P1-核心` + `DM-文件管理` + `US4`），回填總覽表 GitHub # / 狀態與 body header。交付前自檢（`/sti-sa-precheck dm us4`）結論 ✅ 齊備、無必補 |
| 2026-08-17 | 撰寫 Issue #4（US5 文件新增與編輯 / DM03）完整 body：對應 spec_us5 FR-001~009 + UCDM06；涵蓋 T035/T035a/T036/T037/T038/T039。**切分要點**：DM 第一個**寫入型** issue，主體為組裝 #127 Foundation 既有工具（DOC_ID 產生器 T017、file_store T016 上傳驗證、ReviewService T019 送簽、notify T018 `DOC_SUBMIT`、DB 約束 手冊唯一/版本號唯一）；範圍到「送審中」為止——核准/發布屬 US6、草稿匣列表/撤回屬 US9。前置 #0（必要）+ #3/#5（入口/去向，以獨立測試不阻塞）。新增寫入專屬 error code 待開工前 `/sti-plan` 對齊登記 `docs/ref/error-codes.md`。Labels `P1-核心` + `DM-文件管理` + `US5`。總覽表 Issue #4 狀態改「📝 body 已撰寫（待開立）」 |
| 2026-08-21 | **US7 設計對齊導覽重構 #89**：DP spec_us1 FR-DP-US1-07（2026-07-28 D1/D2）定登入後主頁為中性歡迎頁、模組儀表板改為依權限疊加之 widget（不設獨立落地頁）；原 spec_us7「登入自動導向 DM00 獨立頁 / 無側欄入口 / home 返回」為 DM 單模組舊觀點、與 #89 衝突。據此更新 spec_us7（改為中性歡迎頁之 DM 文件概況 widget、加可見性要求）、spec.md（US7 描述 + DM00 畫面列移除「待辦彙總」）、issues.md Issue #6 body（前端改掛 WelcomePage widget、去獨立 `/dm` 落地）。後端 stats/announcements 端點不變。前端據此重塑（原 PR #195 之獨立頁改為 widget）|
| 2026-08-21 | **回填 issues.md 至現況**（自 2026-08-17 後未維護、body 停在 Issue #4）：**(1)** 總覽表狀態 / GitHub # 更正——US5(#4)→已交付 [#169]（PR #172；spec 對齊 #175/#176）、US6(#5)→已交付 [#178]（PR #180）、US12(#11)→已交付 [#183]（PR #189；契約 #187；T059 範圍外）、US7(#6)→「body 已撰寫（待開立）」。**(2)** 補撰三張完整 body：Issue #5（US6 簽核處理 / DM04，含交付後差異：催辦排程 `SCHDM001`→`SCHDM002`、退回被退版本 `REJECTED`→`DRAFT` + 新增 `DM_DOC_012`）、Issue #6（US7 系統儀表板 / DM00，含交付前自檢建議：badge 來源 `DM_REVIEW.REVIEW_TYPE`、統計計入 `PENDING_OBSOLETE`、`spec.md` 待辦彙總措辭待 SA 修）、Issue #11（US12 跨模組引用，含 in-process Service 介面、TRAINING 分類白名單、T059 裁示 A 範圍外）。**(3)** 其餘未開工者維持待補：#7 US8 / #8 US9 / #9 US10 / #10 US11 / #12 US13 / #13 收尾。補強 follow-up #160（storage-root 圍籬，非 US）不列入總覽。US7 GitHub issue 尚未開立（依指示先補 issues.md、暫不開 issue）|
| 2026-08-24 | 撰寫 Issue #7（US8 文件廢止申請 / UCDM05 / DM02）完整 body：對應 spec_us8 FR-001~005 + 訊息 DM-MSG-DM02-011~015；涵蓋 T047（廢止申請對話框：必填原因 + 選填單檔附件 + 選審核者 → PENDING_OBSOLETE 並通知）/ T048（廢止待簽核行為：仍在架可下載、阻擋同時新版本送審、核准 / 退回）。**關鍵切分**：**本 issue 需延伸 US6（#178 已交付）**——US6 目前以 `DM_REVIEW_006`「待 US8」在 `center_service._ensure_actionable` 擋掉 OBSOLETE 核准 / 退回（review repository 亦排除 OBSOLETE），spec_us8 FR-005 雖寫「核准 / 退回交由 US6」實為 stub，故 US8 淨新增＝解除封鎖 + 實作核准（→OBSOLETE + 版本歷程廢止紀錄）/ 退回（→PUBLISHED）。**重用**：`ReviewService.submit(review_type=OBSOLETE)`、file_store 上傳驗證（`DM_FILE_001/002`）+ storage-root fence #160 存 `DM_REVIEW.OBSOLETE_FILE_*`（T010）、`DmNotifier`；FR-004 同時新版本送審由「一文件一 PENDING」唯一索引天然涵蓋（`DM_REVIEW_002` / DM-MSG-DM02-012）。**待 plan**：缺原因（DM-MSG-DM02-011）/ 缺審核者（DM-MSG-DM02-014）之後端 error_code；前端入口（DM02 現 `navigate("/dm/documents/:docId/obsolete")` 指向未存在路由）落地為 dialog（傾向、對齊 wireframe `openObsoleteModal`）或補 page 路由。Labels `P2-延伸` + `DM-文件管理` + `US8`。總覽表 Issue #7 狀態改「📝 body 已撰寫（待開立）」；placeholder 收斂為 #8~#10。body 經 `/sti-sa-precheck dm us8` 交付前自檢 ✅ 齊備、無擋交付必補（wireframe `obsoleteModal` 完整、`OBS_SUBMIT/APPROVE/REJECT` 範本已 seed），5 項建議補強留待 `/sti-plan`。issues.md body 落地 PR #205（已合併）|
| 2026-08-24 | Issue #7（US8 文件廢止申請）開立為 GitHub [#206](https://github.com/sti-fhb/EDMS/issues/206)（labels `P2-延伸` + `DM-文件管理` + `US8`），回填總覽表 GitHub # / 狀態（🚀 已開立）與 body header。GitHub body 沿用 issues.md #7 canonical 內容（連結轉 `../blob/main/` 形式、`OBS_*` 範本已 seed 補註、結尾 `Refs #178` 不自動關閉 US6）|
| 2026-08-24 | US8（#206）交付並 close（PR #210 squash 合併 main `074298f`）：發起端點 `app/dm/obsolete/` + 延伸簽核中心 OBSOLETE 核准/退回（解除 `DM_REVIEW_006`）+ 廢止附件下載（授權 SA 裁示 **Q1=C**：僅 DM_ADMIN 或指定審核者、發起人不可）+ 前端 DM02 廢止 dialog / DM04 廢止明細；新增 error codes `DM_DOC_014/015/016`。Code review 抓到並修正 CRITICAL（`OBS_*` 通知 params key `author_name`→`applicant_name` + 補 `reason`，原致空信 FAILED）；SA 裁示 **Q2=A**（廢止 banner 承載紀錄、不插版本列）。security review 之 M1/M2/M3/L1（上傳/送審共用層加固）另開 follow-up **#211**。總覽 Issue #7 → ✅ 已交付。**順帶回填**：Issue #6（US7）狀態由「開發中」更正為 ✅ 已交付（PR #195，#193 已 close）|
| 2026-08-24 | 撰寫 Issue #8（US9 個人專區 / UCDM09 / DM07）完整 body：對應 spec_us9 FR-001~004 + 訊息 DM-MSG-DM07-004/005；涵蓋 T050（草稿匣三類：未送審/被退回/已撤回）/ T051（撤回送審：NEW·NEW_VERSION→草稿、OBSOLETE→已發布、站內訊息通知原審核者、保留原審核者紀錄、改選再送）/ T052（我的文件動態角色 tab 近 30 天 + 個人專區入口可見性：僅編輯者或審核者）。**T049 個資維護已廢除**（平台 DP UCDP004，不自建）。**重用** `ReviewService.withdraw`（PENDING→WITHDRAWN，已存在）、US5 草稿續編/刪除、依權限側欄（#89）。**待 plan**：撤回站內訊息之通知範本/管道（data-model 通知事件表無「撤回」事件，採 MSG-only 既有或新增）、草稿三類分類依 `DM_REVIEW` 歷史之判定邏輯。Labels `P2-延伸` + `DM-文件管理` + `US9`。總覽 Issue #8 → 「📝 body 已撰寫（待開立）」；placeholder 收斂為 #9~#10 |
| 2026-08-24 | US9 交付前自檢（`/sti-sa-precheck dm us9`）**1 必補**：FR-002 撤回要求「站內訊息通知原指派審核者」，但 data-model 通知事件表（9 項）**無撤回事件**、Foundation 亦未 seed → SD 無 template_code 可用。修正：新增 **`SUBMIT_WITHDRAWN`**（CHANNEL=MSG_ONLY、對象原指派審核者）至 data-model 通知事件表（→10 項）+ 集中化清單；spec_us9 FR-002 引用之、FR-001 補草稿三類判定規則（未送審=無 review / 被退回=最近 REJECTED / 已撤回=最近 WITHDRAWN）；issues.md #8 body 同步（T051 註明需 seed migration、注意事項兩項「待 plan」改為已定案）。實作時（T051）新增 `SUBMIT_WITHDRAWN` seed migration。修正折入 #218（issues.md body PR）同批 |
| 2026-08-24 | Issue #8（US9 個人專區）開立為 GitHub [#219](https://github.com/sti-fhb/EDMS/issues/219)（labels `P2-延伸` + `DM-文件管理` + `US9`），回填總覽表 GitHub # / 狀態（🚀 已開立）與 body header。GitHub body 沿用 issues.md #8 canonical 內容（連結轉 `../blob/main/`、驗收條件含 `SUBMIT_WITHDRAWN` seed migration） |
