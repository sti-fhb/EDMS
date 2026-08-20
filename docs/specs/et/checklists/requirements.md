# Specification Quality Checklist: 教育訓練文件管理模組（Education & Training）

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)（僅用業務代碼名稱如 ET_COURSE / ET-MSG，per sti-spec-style §4；無框架 / 語言細節）
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed（模組定位 / 主要角色 / User Stories 索引 / Requirements / Key Entities / Success Criteria / Assumptions / 跨模組介接 / 排程作業總覽 / RQ 追蹤矩陣）

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain（2026-07-03 grep 確認無 TBD / 待補 / 待確認 / ???）
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable（SC-001 ~ SC-013 皆量化；SC-013 為 2026-07-17 線下核可新增）
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined（spec_us1 ~ 17.md 各含 Acceptance Scenarios）
- [x] Edge cases are identified（可逆狀態機、影片累計覆蓋率邊界、Attempt Snapshot 並發、軟刪除分流、標籤對應變更影響、Email 變更逾時、問卷凍結、0 管理者情境、DM 文件廢止等）
- [x] Scope is clearly bounded（Assumptions + Out of Scope + 跨模組介接總覽；ET/DM 獨立部署、不依賴主系統業務模組）
- [x] Dependencies and assumptions identified（Assumptions + 跨模組介接總覽 + 各 spec_us 前置依賴）

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria（各 spec_us{N}.md 具 `FR-ET-US{N}-NN` 功能需求 ＋ Acceptance Scenarios ＋ 系統訊息表 ET-MSG-…；2026-07-03 補齊 15 US 共 146 條 FR，2026-07-17 線下核可再補 US16 11 條 / US17 6 條 / US3 增 1 條，合計 17 US 164 條 FR，採 MUST / MUST NOT 規範句、比照 DM 風格）
- [x] User scenarios cover primary flows（17 US 涵蓋 UCET001 ~ UCET017）
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- spec.md（索引）已完成：模組定位、主要角色（管理者 / 教師 / 學員 / 系統自動）、User Stories 索引（17 US / P1~P3；US16 / US17 為 2026-07-17 線下核可新增）、優先級總覽、Key Entities、全模組業務規則（受訓單位標籤 / 起訖時間與可逆狀態機 / 強制完成解鎖 80% 累計覆蓋率 / 課後回饋問卷 / 排程統計與提醒 / 通知信統一範本 / 多選題部分計分 / 洗牌與 Attempt Snapshot / 閱卷明細 / 軟刪除分流 / 並發處理 / 樂觀鎖 / 管理者保護 / DM 文件廢止 / 邀請與加入 / 完課率 / 章節異動 / 系統初始化 / Email 變更）、Success Criteria、Assumptions、跨模組介接、排程作業總覽、RQ 追蹤矩陣。
- **已完成**：spec_us1 ~ 17.md 全數產出（各含 User Story 描述、Acceptance Scenarios、系統訊息表 ET-MSG-…、前置依賴）；data-model.md（28 表〔含 ET_APPROVAL〕 + 9 類 Lookup + ERD）、plan.md、research.md、tasks.md、issues.md、contracts/（SRVDM001 / SRVDM002 / EXT-ET-EMAIL）、wireframes/et/index.html。
- **2026-07-02 客戶 6 項需求變更**已傳播至 spec / data-model / plan / tasks / wireframe / research（受訓單位標籤取代業務模組、發布標籤自動邀請＋寄信、起訖時間與可逆關閉、課後問卷、排程統計與提醒、每次作答明細、通知範本、影片倍速）。
- **2026-07-03 交付前自檢後續**：（1）通知 Email 契約 `ext-et-email-server.md` 已整份改寫對齊 2026-07-02（統一範本 / 通知範本 / 排程信 / IS_ACTIVE）；（2）US13 課後問卷填寫頁已補入 wireframe（`et-survey` / ET05-Q）；（3）本檢核清單補建；（4）**S1 已補**：15 檔各補 `## Functional Requirements` 區塊，編號 `FR-ET-US{N}-NN`（共 146 條）。
- **2026-07-08 集中化對齊**：系統參數、通知範本、發信、排程集中於平台 DP（見 [../../../requirements/RQDP.md](../../../requirements/RQDP.md)、[../../../_refs/09-平台模組.md](../../../_refs/09-平台模組.md)）。ET 不再自持 `ET_PARAM` / `ET_NOTIFY_TEMPLATE`：參數存平台 `DP_PARAM`（前綴 `ET_`）、通知範本存平台 `DP_NOTIFY_TEMPLATE`（`MODULE=ET`）、寄信走平台唯一發信服務（`DP_EMAIL_LOG`）、排程於平台 `DP_SCHEDULE` 註冊由平台引擎執行（`DP_SCHEDULE_LOG`）；密碼重設 / Email 變更驗證 TTL 改平台級 `DP_` 參數。維護 UI 於平台 DP 後台（參數於「系統參數與清單」、範本於「通知範本」，按模組過濾）。已傳播至 spec / data-model / plan / research / tasks / issues / contracts / RQET / usecases / wireframe。
- **已補（原 SA precheck 建議項）**：
  - ~~**S1**：各 spec_us 之功能需求編號~~ ✅ **已補**（2026-07-03；採 `FR-ET-US{N}-NN`，15 檔共 146 條 FR）。
- **2026-08-19 交付前自檢（全模組 17 US）已補**：
  - ~~**跨模組契約與 DM 對調**~~ ✅ **已補**：ET 兩份 DM 契約依提供方 DM 之定稿契約（2026-06-24）整份對齊——編碼對調更正（SRVDM001 = 依 DOC_ID 取當前發布版、SRVDM002 = 取分類清單）、`docId` BIGINT → VARCHAR(20)、分類碼 `TRAINING_MATERIAL` → `TRAINING`、回應包裝 `documents` → `items`、廢止語意改採 DM 三態、移除 DM 不提供之欄位（分頁 / `file_type` / `file_size_bytes` / `content_url` / `content_base64`）與 401 錯誤碼；並補「經 `app/services` in-process 呼叫、不打 DM HTTP 端點」（DM 存取閘要求 DM 角色，ET 學員未必具備）。已傳播至 plan / tasks / data-model。
  - ~~**週報 CSV 郵件附件**~~ ✅ **已改**：平台唯一發信服務不支援附件（`DP_EMAIL_LOG` 無附件欄位、`app/dp/notify/` 無附件實作），且 ET 不得自建寄件佇列 → 改為**內文 CSV 下載連結**（變數 `{{REPORT_CSV_URL}}`）；新增 FR-ET-US14-11（需登入、教師限自己課程 / 管理者全域、內容即時產生、不設連結有效期）與 T164（下載端點）。已傳播至 spec / spec_us14 / contracts / tasks / issues。
  - ~~**影片覆蓋率無分母欄位**~~ ✅ **已補**：覆蓋率公式 `÷ VIDEO_DURATION` 原無任何表可存 → `ET_MATERIAL_VIDEO.DURATION_SEC`（必填，上傳時自 metadata 取得；取不到不得存檔）。
  - ~~**「已用重考次數歸 0」與 attempt 永久保留互斥**~~ ✅ **已補**：新增 `ET_QUIZ_RETRY_RESET`（append-only 基準表）+ `ET_QUIZ_ATTEMPT_M.ATTEMPT_NO`；已用次數 = max(0, COUNT(attempt) − MAX(基準) − 1)，重置**不刪任何 attempt**。已更新 FR-ET-US9-06 / T093。
  - ~~**S4**：`ET_MATERIAL` 多支影片 / 多份 DM 文件 1:N 拆表~~ ✅ **已補**：正式拆為 `ET_MATERIAL_VIDEO` / `ET_MATERIAL_DOC`。**連帶修正**影片進度層級——原 `ET_PROGRESS` / `ET_PROGRESS_INTERVAL` 掛 `ITEM_ID`，多支影片時無法分別判定 80%，改為新增 `ET_PROGRESS_VIDEO` + 區段改掛 `VIDEO_ID`。
  - ~~**外模組 table 清單未列**~~ ✅ **已補**：spec.md 新增 §外模組 table 引用清單（A 唯讀 JOIN：`DP_USER`；B 經 `app/services` Service：`ParamService` / `NotifyService` / `AuditLogService`），滿足 `sti-backend-boundaries` 之明文要求；做法比照 DM 之 `author_name` 唯讀 join。
  - ~~**稽核 `FUNC_NAME` 語意碼未定義**~~ ✅ **已補**：spec.md 新增 §稽核來源功能碼，定義 6 個語意碼（`ET-ROLES` / `ET-COURSE` / `ET-OWNER` / `ET-ENROLL` / `ET-QUIZ-RESET` / `ET-APPROVAL`），格式對齊平台既有慣例（`DM-CATALOG` / `DP-AUTH`）。
  - ~~**tasks / issues 未隨 2026-07-08 集中化裁減**~~ ✅ **已補**：廢除 9 項任務（T033 / T036 / T038 ~ T040 登入註冊、T097 ~ T099 / T101 個資）；T045 / T130 改寫為 **DP 後台轉接層 provider**（比照 DM `DmAssignProvider` / `CatalogAdapter`）、T151 改為範本 seed 與啟停檢查；Issue #1 / #2 / #10 / #17 整段重寫。總任務數 158 → **154**（另新增 T164 ~ T168）。ET 業務表 25 → **29** 張。

  - ~~**plan.md §技術背景陳舊**~~ ✅ **已修**：整表對齊 CLAUDE.md 與平台實況——前端 React 19 + MUI 7 + React Router v7 + TanStack Query v5、後端 FastAPI + SQLAlchemy 2 + Alembic、PostgreSQL 17、認證改平台 DP 對稱 JWT；新增 §程式碼落點（`backend/app/et/{功能}/` + `deps` / `bootstrap` / `provider`，比照 DM）；T001 / issues #0 之 `controllers / repositories / templates` 目錄改為專案實際結構。
  - ~~**「session」措辭與平台機制矛盾**~~ ✅ **已修**（連帶修正）：平台 DP 明訂**不採 Refresh Token / 伺服器端 session**（登出＝前端丟棄 token），故原 spec 之「寫入 session」「強制當前 session 登出」為平台做不到的動作。已改為「DP 核發 JWT」「須以新 Email 重新登入（既有 JWT 失效方式由平台 DP 定義）」——涉 spec.md、spec_us2（AC1 / FR-01）、spec_us10（AC3 / FR-03）、tasks T026、issues #0 驗收 4。
  - ~~**SC-004 陳舊**~~ ✅ **已修**：改為「經平台唯一發信服務寄送（`DP_EMAIL_LOG` outbox）」。**連帶** SC-002 去技術詞（原寫「以 HTML5 video player 提供」，與本清單「Success criteria are technology-agnostic」打勾不符）。

- **2026-08-19 第二輪補正（#181，比對規格與已上線程式碼）**：
  - ~~**標籤歸屬 spec 與 data-model 自相矛盾**~~ ✅ **已修**：`spec.md` 原寫「受訓單位標籤庫清單存平台 `DP_PARAM`」，與 `data-model.md` 之 `ET_TAG` 自持表互斥。經三項佐證確認自持表為正（DP #171 附帶發現、DP `roles/service.py` `group_options()` 模組無關且不讀 `DP_PARAM`、DM 2026-08-06 #127 先例），已修 `spec.md` §跨模組共用規則與 `spec_us1.md`。DP 側文件對齊見 #182。
  - ~~**DM 契約依賴陳述 stale**~~ ✅ **已修**：兩份契約原引用「DM #169 仍為 OPEN」，該 issue 已於 2026-08-19 07:07 關閉且屬 DM US5（非本服務所屬之 US12）。改指 **#183**（DM US12），並註明其前置為 #178。
  - ~~**倍速參數語意誤導**~~ ✅ **已修**：`ET_VIDEO_PLAYBACK_MAX_RATE` 原讀起來像可自由調整，實際上前端選項清單寫死、只能往下限縮（此即 DP #171 判其為 `READONLY` 之理由）。已於 `data-model.md` / `plan.md` / `spec_us5.md` / `research.md` 補註。
  - ~~**缺 ET → DP 回呼契約**~~ ✅ **已補**：新增 `contracts/srv-et-dp-module-callbacks.md`，回填 **SRVET001 ~ SRVET006** 編碼、定案 ET 端簽章與 `ET_TAG` 受控主檔語意、「全體」保護落點；並於 `docs/ref/error-codes.md` §ET 登記 5 個 error code（`ET_AUTH_001` / `ET_ROLE_001~003` / `ET_TAG_001`）。

- **2026-08-20 開工前裁決**：
  - ~~**Lookup 代碼表機制不存在**~~ ✅ **已定案**：原 T021 要求「建立 9 類 Lookup 代碼初始資料」，但本專案無 lookup 表機制（DM 之狀態欄位為 `String(20)`，無 lookup 表 / CHECK / Enum，代碼以模組層常數表達）。裁決為**比照 DM，純應用層常數、不建表不 seed**；已更新 `data-model.md` §Lookup 代碼定義（含理由與落地方式）、`tasks.md` T021 / T156、`issues.md` Issue #0 涵蓋任務與驗收條件 2。避免 ET 平白多出 9 張表並與 DM / DP 做法分歧。

- **待補（不擋 SD 開發、建議補強）**：
  - **訊息類型表之 Bootstrap class 標註**（spec.md §Requirements）：ET / DM / DP **三模組 spec 用字完全相同**，屬跨模組共用慣例。ET 單方改為 MUI 會破壞一致性，故本次**不動**；若要更新應三模組同批處理（獨立議題）。
  - ET → DP 之參數唯讀查詢與排程註冊（`DP_SCHEDULE` job handler 介面）無獨立契約檔（spec.md §跨模組介接總覽有列，DP 端已上線可直接參照實作）。
  - `ET_INVITATION` 未定義同一課程重複邀請同一 Email 之行為（無 (COURSE_ID, EMAIL) 唯一約束）。
  - JSON 字串欄位（`QUESTION_ORDER` / `OPTIONS_SNAPSHOT` 等）與「`ET_PROGRESS_INTERVAL` 刻意不用 JSON」原則不一致；專案為 PostgreSQL 17，JSONB 可用，建議 plan 階段統一表態。
  - wireframe：空資料狀態偏少；側欄殘留「系統設定」死連結（該畫面已移交 DP）；plan.md 之 wireframe 描述與 checklists「待產出」標註陳舊。
- **2026-07-17 客戶線下核可需求**已傳播至 spec（US16 / US17 索引、§線下核可規則、7 類範本、SC-013）、spec_us16 / spec_us17（新）、spec_us3（REQUIRE_APPROVAL 欄位 + FR-16）、spec_us9 / spec_us15（交叉引用 / 7 類）、data-model（ET_APPROVAL、ET_COURSE.REQUIRE_APPROVAL、ET_APPROVAL_RESULT）、plan / tasks（Phase 18、T156~T163）/ issues（#18 / #19）/ research（#23 走法 A）/ contracts（APPROVAL_PASSED）/ RQET / usecases（UCET016 / UCET017）/ wireframe（ET03 核可欄 + ET10 查詢）。核可為獨立維度，不影響完課率 / 問卷 / 週報。
- 來源可追溯：spec 內容對應 requirements/RQET.md、use-cases/et/usecases.md、_refs/10-教育訓練文件管理模組.md（source of truth），無新增未授權範圍。
