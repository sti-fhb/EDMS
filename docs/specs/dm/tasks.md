# 開發任務清單：文件管理模組（Document Management）

**模組代碼**: DM | **日期**: 2026-06-24
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md) | **資料模型**: [data-model.md](data-model.md) | **研究**: [research.md](research.md) | **契約**: [contracts/document-service.md](contracts/document-service.md)

> DM **權限自管（自己的 4 角色）**、與平台模組 DP 只共用帳號與認證，與 ET 共用 `DP_USER`（SSO）；自身 14 張業務表（含 `DM_USER_TAG` 可見對象授權、`DM_DOC_READ` 閱讀紀錄）+ 排程 `SCHDM001`。**系統參數 / 通知範本 / 寄件佇列 / 排程集中於平台 DP（2026-07-08）**：DM 不建 `DM_PARAM` / `DM_NOTIFY_TEMPLATE` / `DM_NOTIFY_QUEUE` migration，改用平台 `DP_PARAM`（前綴 `DM_`）/ `DP_NOTIFY_TEMPLATE`（`MODULE=DM`）/ outbox `DP_EMAIL_LOG`，`SCHDM001` 於 `DP_SCHEDULE` 註冊由平台引擎執行（job handler 由 DM 提供）。標準欄位省略 SITE / HOSPITAL（對齊平台 DP，research §1）。檔案存檔案系統 / DB 存 metadata。

---

## Phase 1: 專案設定

- [ ] T001 建立文件管理模組專案結構，依 plan.md 文件結構建立 dm/ 目錄與子目錄
- [ ] T002 [P] 建立資料庫 Migration：`USER` 共用使用者主檔（USER_ID PK、EMAIL UNIQUE、PASSWORD_HASH、USER_NAME、EMAIL_PENDING_*）；**與 ET 共用，schema 需與 ET 協調**，參照 data-model.md
- [ ] T003 [P] 建立資料庫 Migration：`DM_USER_ROLE`（USER_ID×ROLE_CODE，唯一約束）與 `DM_USER_ROLE_LOG`（append-only 角色異動），參照 data-model.md
- [ ] T004 [P] 建立資料庫 Migration：`DM_CATEGORY`（CATEGORY_CODE PK、IS_BUILTIN、IS_ENABLED），參照 data-model.md
- [ ] T005 [P] 建立資料庫 Migration：`DM_FUNC`（FUNC_CODE PK、IS_ENABLED），參照 data-model.md
- [ ] T006 [P] 建立資料庫 Migration：`DM_TAG_GROUP`（含 `GROUP_TYPE` AUDIENCE/RETRIEVAL）與 `DM_TAG`（FK→TAG_GROUP、IS_ENABLED），參照 data-model.md
- [ ] T006a [P] 建立資料庫 Migration：`DM_USER_TAG`（閱覽者可見對象授權，USER_ID×TAG_ID 明細、唯一約束、TAG 限 AUDIENCE 組），參照 data-model.md
- [ ] T007 [P] 建立資料庫 Migration：`DM_DOCUMENT`（DOC_ID PK、CATEGORY_CODE/FUNC_CODE/CURRENT_VERSION_ID FK、STATUS）+ **部分唯一索引**（FUNC_CODE where CATEGORY='MANUAL' AND STATUS='PUBLISHED'，research §5），參照 data-model.md
- [ ] T008 [P] 建立資料庫 Migration：`DM_DOC_VERSION`（VERSION_ID PK、FK→DOCUMENT、VERSION_NO、CHANGE_SUMMARY、FILE_*、STATUS、APPROVER、PUBLISHED_DATE），參照 data-model.md
- [ ] T009 [P] 建立資料庫 Migration：`DM_DOC_TAG`（DOC×TAG 明細，唯一約束），參照 data-model.md
- [ ] T009b [P] 建立資料庫 Migration：`DM_DOC_READ`（append-only 閱讀紀錄：DOC_ID/VERSION_ID + 標準 CREATED_USER/CREATED_DATE〔即下載者/下載時間，不另設 USER_ID/READ_TIME〕、省 UPDATED_*/DELETED、唯一約束 (DOC_ID,VERSION_ID,CREATED_USER)），參照 data-model.md
- [ ] T010 [P] 建立資料庫 Migration：`DM_REVIEW`（送審週期：REVIEW_TYPE、ASSIGNED_REVIEWER、APPROVER、STATUS、SUBMIT/COMPLETE_DATE、REASON、**廢止附件 OBSOLETE_FILE_NAME/PATH/SIZE/MIME**），參照 data-model.md
- [ ] T011 [P] 建立資料庫 Migration：`DM_CHANGE_LOG`（append-only 公開變更歷程：OPERATION、APPLICANT、APPROVER、NOTE），參照 data-model.md
- [ ] T012 ~~建立 `DM_NOTIFY_TEMPLATE` / `DM_PARAM` Migration~~ **已廢除（2026-07-08 集中化）**：通知範本改存平台 `DP_NOTIFY_TEMPLATE`（`MODULE=DM`）、系統參數改存平台 `DP_PARAM`（`PARAM_ID` 前綴 `DM_`），由平台 DP 建 migration；DM 不建此二表。維護 / 編輯 UI 於平台 DP 系統管理後台（按模組過濾，DM 不自設系統設定畫面）。
- [ ] T012a ~~建立 `DM_NOTIFY_QUEUE` Migration~~ **已廢除（2026-07-08 集中化）**：非同步寄送改用平台 outbox `DP_EMAIL_LOG`（呼叫平台唯一發信服務、傳 `template_code`）；DM 不建佇列表。
- [ ] T013 建立種子資料：4 內建分類（SOP/MANUAL/TRAINING/OTHER + 分類碼）、4 標籤組（**AUDIENCE（權限）/MODULE/NATURE/LEGAL（檢索）；原 ROLE 移除**）、可見對象預設值（全體/護理師/軍人/醫檢師/行政人員）為 DM 業務種子。**通知範本 / 參數種子改由平台 DP 建（2026-07-08 集中化）**：9 通知範本寫入 `DP_NOTIFY_TEMPLATE`（`MODULE=DM`；`DOC_PUBLISH`＝撰寫者+相符閱覽者、含 `KPI_WEEKLY` / `UNREAD_REMIND`＝EMAIL_ONLY）、DM 參數寫入 `DP_PARAM`（前綴 `DM_`：`DM_REMIND_THRESHOLD`=7、`DM_FILE_MAX_MB`=50、`DM_FILE_TYPES`、`DM_WEEKLY_SCHED_DAY_TIME`=`週一,10:00`）；發信引擎調校參數（重試 / 限流 / 重試間隔）屬平台級 `MAIL` 參數組（`RETRY_MAX`=5、`RATE_PER_MIN`=60、`RETRY_INTERVAL_MIN`=2；無失敗告警參數——失敗率由 IT 監控負責，2026-07-09 對齊平台），由 DP 種子建立。參照 data-model.md 代碼表與平台 DP 規格

---

## Phase 2: 基礎共用元件

> 為所有 User Story 之阻斷性前置（SSO 認證、授權、檔案、DOC_ID、通知、狀態機）。

- [ ] T014 [P] 實作 SSO 認證接入 + **DM 存取閘** dm/middleware/auth：重用平台 DP 之登入 JWT（共用 `DP_USER`）、未登入擋下、**無任何 DM 角色者拒絕進入**（含直接呼叫 API；原「首次登入自動授予閱覽者」已作廢，DM 角色一律由管理者開通）；**DM 權限自管、與平台 DP 只共用帳號與認證**，對應 spec_us2 FR-001（存取閘；登入 / 註冊 / 忘記密碼由 DP 提供）
- [ ] T015 [P] 實作角色授權工具 dm/util/authz：4 角色（DM_ADMIN/EDITOR/REVIEWER/VIEWER）複選聯集判定；提供「指定審核者排除本人」與「管理者自我保護」共用檢核，對應 spec_us1 FR-005/006、spec_us5 FR-006
- [ ] T016 [P] 實作檔案儲存服務 dm/service/file_store：上傳至檔案系統 / 物件儲存、DB 存 metadata（FILE_*）、單檔上限讀平台 `DP_PARAM.DM_FILE_MAX_MB`（前綴 `DM_`，經平台唯讀查詢服務）、依 MIME 判定可預覽（PDF/圖片）/ 僅下載（Office），參照 research §3/§10
- [ ] T017 [P] 實作 DOC_ID 產生器 dm/util/docid：`DM-{分類碼}-{6 位流水號}`、流水號依分類各自獨立、草稿建立時配號，參照 research §2
- [ ] T018 [P] 實作通知服務 dm/service/notify：呼叫平台唯一發信服務（傳 `template_code`，範本存 `DP_NOTIFY_TEMPLATE` MODULE=DM）；站內訊息由 DM 自理，依 CHANNEL 發送（EMAIL_MSG＝Email+站內、MSG_ONLY＝僅站內、EMAIL_ONLY＝僅 Email）；停用範本不發，對應 spec_us1 FR-007、research §9
- [ ] T018a ~~實作 outbox 背景寄送 worker~~ **改由平台承載（2026-07-08 集中化）**：非同步寄送統一由平台 outbox `DP_EMAIL_LOG` + 平台發信引擎執行（輪詢待寄、批次寄送、標記狀態、最大重試 / 重試間隔 / 限流之韌性均為平台級 `MAIL` 參數；失敗率告警由 IT 監控負責）；平台發信服務**寄送時依 `template_code` + 收件人即時組信**（未讀提醒算未看清單、KPI 週報算統計+CSV，需業務資料時反向 import DM service）。DM 端僅需呼叫平台發信服務並傳 `template_code` + 收件名單，與核准發布交易解耦，對應 spec_us6 FR-008、spec_us13 FR-006/007、research §9b/§9d
- [ ] T019 [P] 實作送審週期 / 狀態機服務 dm/service/review：DM_REVIEW 建立 / 核准 / 退回 / 撤回；約束「同一文件不可同時兩種送審」（單一 PENDING_*），參照 research §4
- [ ] T020 [P] 實作受控資料維護共用 dm/service/catalog：分類 / func_name / 標籤之新增 / 改名 / 啟用停用、**不開放刪除**、停用後既有引用保留、僅影響後續下拉；**AUDIENCE 組之停用採 soft-retire**（不收回既有可見性、僅擋後續指派、停用時回傳受影響文件 / 閱覽者數），對應 spec_us1 FR-001/FR-010、research §參數維護
- [ ] T020a [P] 實作標籤式可見性判定共用 dm/util/visibility：給定使用者回傳其可見文件之查詢條件——文件掛「全體」 OR（文件 `DM_DOC_TAG` 之 AUDIENCE 標籤 ∩ 使用者 `DM_USER_TAG` ≠ 空）；閱覽者套用、編輯者/審核者/管理者略過，對應 spec_us3 FR-008、research §5b

---

## Phase 3: US2 — 存取閘（登入 / 註冊 / 忘記密碼由平台 DP 提供）（P1）

> **平台對齊（DP，2026-07-08 集中化）**：**登入 / 註冊 / 忘記密碼、帳密維護全由平台模組 DP 提供（UCDP001–004、SSO 共用 `DP_USER`），DM 不自建。** DM 於本 US 唯一之實作為**存取閘**（使用者經 DP 登入後、無任何 DM 角色者拒絕進入），已於 **Phase 2 T014** 實作；本 Phase 之 T021~T023 隨集中化廢除。
> **Story 目標**: 經 DP 登入後，DM 依 DM 角色控管存取（無角色者拒絕進入）
> **獨立測試**: 具 DM 角色者登入導向 DM00；無任何 DM 角色者被拒並提示洽管理者開通；直接以 URL 存取 DM 功能亦被後端擋下
> **對應 FR**: spec_us2 FR-001（存取閘）

- [ ] T021 [US2] ~~實作登入頁與驗證 dm/login~~ **已廢除（2026-07-08 集中化）**：登入由平台 DP 提供（UCDP001、簡單 JWT、共用 `DP_USER`），DM 不自建登入畫面；DM 端 SSO 接入 + 存取閘見 **T014**
- [ ] T022 [US2] ~~實作註冊流程~~ **已廢除（2026-07-08 集中化）**：註冊由平台 DP 提供（UCDP002）；「首次登入自動授予閱覽者」亦作廢——新帳號預設僅 ET 學員、DM 角色一律由管理者開通
- [ ] T023 [US2] ~~實作忘記密碼~~ **已廢除（2026-07-08 集中化）**：忘記密碼由平台 DP 提供（UCDP003）

---

## Phase 4: US1 — 系統設定（維護 UI 在平台 DP 後台）（P1）

> **平台對齊（DP，2026-07-08 集中化）**：**參數 / 權限 / 通知範本之維護 / 編輯 UI 統一於平台 DP 系統管理後台**（DM 管理者按模組過濾操作），DM 不自設系統設定畫面（原 DM09 作廢）。DM 於本 US 之實作為：① **業務規則落地**（分類碼鎖定 / func_name 唯一 / 標籤 soft-retire，catalog 邏輯見 T020）② **權限 / 可見對象之 DP 轉接層模組端**（DP dp-roles 呼叫 DM 回呼；指派 / 判定 + `DM_USER_ROLE(_LOG)` / `DM_USER_TAG` 落地屬 DM）③ **種子**（T013：分類 / 標籤 DM 業務種子；9 通知範本寫 `DP_NOTIFY_TEMPLATE(MODULE=DM)`、DM 參數寫 `DP_PARAM(DM_)`）。**精確的 DP 轉接層契約（呼叫介面 / DETAIL_LOCK 碼鎖定 / soft-retire 對應）於產 US1 issue 時以 `/sti-plan` 盤點 + 問 SA 確認。**
> **Story 目標**: DM 提供 US1 之業務規則落地 + 權限 / 可見對象轉接層模組端 + 種子（維護 UI 在 DP 後台）
> **獨立測試**: 於 DP 後台（DM 模組）新增自訂分類（唯一分類碼、建立後鎖定）→ DM03 下拉即現；對使用者指派編輯者 → 該使用者即具編輯權限；調整催辦門檻 → SCHDM001 依新值
> **對應 FR**: spec_us1 FR-001~010
> **前置**: Phase 2 授權（T015）、受控資料維護（T020）、通知（T018）；平台 DP US5（dp-params）/ US7（dp-roles）/ US9（dp-templates）維護 UI

- [ ] T024 [US1] DM 端：分類（含唯一分類碼、建立後鎖定）/ func_name / 標籤之業務規則落地（catalog 共通維護見 T020）+ 種子（T013）；維護 UI 於平台 DP 後台「系統參數與清單」（按模組過濾），對應 FR-001~003
- [ ] T025 [US1] 實作催辦門檻設定：值域 1–30 天（預設 7）、寫平台 `DP_PARAM.DM_REMIND_THRESHOLD`（前綴 `DM_`，經平台參數服務），維護 UI 於平台 DP 系統管理後台（按模組過濾），對應 FR-004
- [ ] T026 [US1] DM 端權限轉接層：供平台 DP dp-roles 呼叫之模組端回呼（列 / 指派 DM 四角色）、4 角色複選即時生效、寫 `DM_USER_ROLE(_LOG)`、「最後異動」、自我保護、不檢核 0 管理者；維護 UI 於平台 DP 後台「權限管理」，對應 FR-005/006/008
- [ ] T027 [US1] DM 端：9 內建通知範本之種子與語意（「文件發布通知」＝撰寫者+相符閱覽者、含「KPI 週報」「未讀提醒」＝EMAIL_ONLY、自動催辦含門檻）寫平台 `DP_NOTIFY_TEMPLATE`（`MODULE=DM`）；主旨 / 內文編輯 UI 於平台 DP 後台「通知範本」（按模組過濾、只操作 MODULE=DM 的列），對應 FR-007
- [ ] T027b [US1] DM 端：KPI 週報 / 未讀提醒之「每週執行時間」（星期＋時間，兩者共用）存平台 `DP_PARAM.DM_WEEKLY_SCHED_DAY_TIME`（前綴 `DM_`，格式 `星期,HH:MM`，預設 `週一,10:00`），供 SCHDM001 讀取；設定 UI 於平台 DP 後台通知範本 detail，對應 spec_us13 FR-004a
- [ ] T027a [US1] DM 端可見對象授權轉接層：供平台 DP 呼叫之模組端（使用者 × AUDIENCE 標籤指派、即時生效、寫異動紀錄、「最後異動」）+ `DM_USER_TAG` 落地；AUDIENCE 值停用 soft-retire 提示受影響文件 / 閱覽者數；維護 UI 於平台 DP 後台，對應 FR-009/FR-010

---

## Phase 5: US3 — 文件庫與檢索（P1）

> **Story 目標**: 多條件檢索已發布文件、線上操作手冊檢索
> **獨立測試**: 關鍵字 + 標籤搜尋得已發布清單；選系統操作手冊出現 func_name 下拉得唯一手冊
> **對應 FR**: spec_us3 FR-001~006/008/009（原 FR-007 主系統反查已於 2026-06-26 移除）
> **前置**: Phase 2（含可見性判定 T020a）、US5（文件資料）

- [ ] T028 [US3] 實作文件庫搜尋 dm/library：多條件（關鍵字 / 分類 / 作者 / **檢索標籤 AND**（僅適用模組 / 文件性質 / 法規關聯）/ 發布日期區間）、僅顯示已發布目前版本（含廢止待簽核）、灰字標籤、分頁排序，對應 FR-001~003/005/009
- [ ] T028a [US3] 套用標籤式可見性過濾（T020a）：閱覽者僅得掛「全體」或可見對象相符（OR）之文件；編輯者 / 審核者 / 管理者不過濾；與其他搜尋條件 AND 結合，對應 FR-008
- [ ] T029 [US3] 實作系統操作手冊檢索：分類為 MANUAL 時顯示 func_name 下拉、依作業項目得唯一手冊，對應 FR-004
- [ ] T030 [US3] 實作「新增文件」入口（依編輯者角色顯示）導向 DM03，對應 FR-006

---

## Phase 6: US4 — 文件詳細頁瀏覽（P1）

> **Story 目標**: 閱讀目前版本、預覽 / 下載、版本歷程、read-only
> **獨立測試**: 下載並預覽 PDF；展開版本歷程；舊版僅預覽；編輯者見編輯 / 廢止入口
> **對應 FR**: spec_us4 FR-001~006
> **前置**: Phase 2（檔案服務 T016）

- [ ] T031 [US4] 實作詳細頁版面 dm/detail：上方標題列（文件名稱 / DOC_ID / 版本 / 狀態）+ 右側文件資訊面板（不重複），對應 FR-001
- [ ] T032 [US4] 實作文件檔案區：PDF / 圖片內嵌預覽 + 下載、Office 僅下載、僅目前版本可下載；**下載目前發布版時寫 `DM_DOC_READ`（已看，預覽不記、同人同版去重）**，對應 FR-002/004/007
- [ ] T033 [US4] 實作版本歷程抽屜：列所有版本（版號 / 撰寫者 / 發布時間 / 核准者 / 變更摘要）、舊版僅預覽，對應 FR-003/004
- [ ] T034 [US4] 實作動作入口與 read-only 模式：編輯 / 廢止入口（角色、送審中失效）、自 DM06 進入之 read-only（隱藏檔案+資訊、版本歷程自動展開、僅預覽 + 廢止 banner），對應 FR-005/006

---

## Phase 7: US5 — 文件新增與編輯（P1）

> **Story 目標**: 新增 / 上傳新版本、送簽、存草稿
> **獨立測試**: 新增填妥上傳 PDF 送簽轉送審中；編輯新版本身份欄唯讀；Office 跳提醒；存草稿可續編
> **對應 FR**: spec_us5 FR-001~009
> **前置**: Phase 2（DOC_ID T017、檔案 T016、送審 T019、授權 T015）

- [ ] T035 [US5] 實作新增模式 dm/editor#create：DOC_ID 配號、必填（名稱 / 分類 / 摘要 / 審核者 / **可見對象≥1，含「全體」**）、檢索標籤選填、**首版版號由撰寫者自行輸入（無系統建議）**，對應 FR-001
- [ ] T035a [US5] 實作可見對象必填檢核：送簽 / 發布前確認文件至少關聯 1 個 AUDIENCE 標籤，未掛則阻擋（DM-MSG-DM03-008），對應 FR-009
- [ ] T036 [US5] 實作編輯模式 dm/editor#edit：文件名稱 / 分類 / func_name 唯讀、**版本號由撰寫者自行輸入（自由文字，無自動建議 / Major / Minor）**、送簽 / 發布前檢核版本號非空且同文件內不重複（DM-MSG-DM03-009），對應 FR-003/004
- [ ] T037 [US5] 實作 func_name 單選 + **唯一檢核**（送簽 / 發布前檢核同 func_name 無其他已發布手冊），對應 FR-002
- [ ] T038 [US5] 實作檔案上傳（單檔 ≤ 50MB、Office 跳預覽提醒 + 橘色警示條、PDF / 圖片不提醒），對應 FR-005
- [ ] T039 [US5] 實作指定審核者下拉（排除自己）+ 儲存為草稿 + 送交簽核（轉送審中、通知），對應 FR-006/007/008

---

## Phase 8: US6 — 簽核處理（P1）

> **Story 目標**: 審核者核准 / 退回送審項目
> **獨立測試**: 待簽核清單僅顯示自己項目（無指定審核者欄）；核准並發布轉已發布並寫變更歷程；退回回草稿並通知
> **對應 FR**: spec_us6 FR-001~008
> **前置**: Phase 2（送審 T019、通知 T018、outbox T018a、可見性判定 T020a）、US5（送審來源）

- [ ] T040 [US6] 實作待簽核清單 dm/review：僅顯示指定審核者 = 當前登入者之項目、欄位（文件 / 分類 / 版本 / 送審者 / 送審時間 / 停留天數）、無「指定審核者」欄，對應 FR-001
- [ ] T041 [US6] 實作簽核明細：下載送審檔案（不預覽）、新版本新舊版並列下載比對、廢止對象與原因、**廢止附件下載（如有）**，對應 FR-002
- [ ] T042 [US6] 實作核准並發布 / 廢止：**單一交易**完成版本切換（新版 PUBLISHED、舊版 SUPERSEDED、更新 CURRENT_VERSION_ID）/ 廢止下架、寫 `DM_CHANGE_LOG`、通知撰寫者，對應 FR-003/005、research §6
- [ ] T042a [US6] 實作文件發布通知：核准並發布（新增首版 / 新版本，廢止不含）時，於**發布當下**組出收件名單＝**撰寫者 + 可見性判定（T020a）之相符閱覽者**（掛「全體」→全部；不排除兼編輯/審核者），以單一 `DOC_PUBLISH`（`DP_NOTIFY_TEMPLATE` MODULE=DM）呼叫平台唯一發信服務（傳 `template_code` + 收件名單快照），經平台 outbox `DP_EMAIL_LOG` 背景寄送，對應 FR-008、research §9b
- [ ] T043 [US6] 實作退回：必填退回原因、回對應狀態（草稿 / 已發布）、通知撰寫者，對應 FR-004
- [ ] T044 [US6] 實作自動催辦排程 + 「已完成」頁籤：每日掃 DM_REVIEW 停留 ≥ 門檻發站內訊息並標紅、已完成項目唯讀，對應 FR-006/007、research §9

---

## Phase 9: US7 — 系統儀表板（P2）

> **Story 目標**: 登入後落地頁掌握總數與近期動態
> **獨立測試**: 四類統計卡（僅已發布）+ 近 30 天公告；點公告進詳細頁
> **對應 FR**: spec_us7 FR-001~004

- [ ] T045 [US7] 實作各類型文件總數區 dm/dashboard：4 內建分類已發布目前版本數 + 總計、卡片不可點，對應 FR-001/002
- [ ] T046 [US7] 實作最新更新公告區：近 30 天已發布（新增 / 新版本兩類）、點入詳細頁 / 查看全部進文件庫、空狀態提示，對應 FR-003/004

---

## Phase 10: US8 — 文件廢止申請（P2）

> **Story 目標**: 編輯者發起整份廢止
> **獨立測試**: 填原因選審核者送出轉廢止待簽核且仍對外；新版本送審中不可廢止
> **對應 FR**: spec_us8 FR-001~005
> **前置**: US4（詳細頁入口）、US6（簽核處理）

- [ ] T047 [US8] 實作廢止申請對話框：必填廢止原因、**選填廢止附件（單檔，格式 / 大小比照文件上傳，沿用檔案儲存服務 T016，存 `DM_REVIEW.OBSOLETE_FILE_*`）**、選指定審核者（排除自己）、轉 PENDING_OBSOLETE 並通知，對應 FR-001/002
- [ ] T048 [US8] 實作廢止待簽核行為：仍顯示於文件庫且可下載、阻擋同時新版本送審、撤回 / 核准 / 退回交由 US9 / US6，對應 FR-003/004/005

---

## Phase 11: US9 — 個人專區（P2）

> **平台對齊（DP）**：**個人資料維護（姓名 / Email / 密碼）為另一功能、由平台 DP 提供（UCDP004、右上使用者選單），不屬本 US。** 個人專區為 DM 左側功能列之個人工作區，含**草稿匣 / 撤回送審 / 我的文件動態**（皆編輯者 / 審核者業務），入口僅對具編輯者或審核者角色者顯示。
> **Story 目標**: 編輯者 / 審核者之個人工作區——草稿匣 / 撤回送審 / 我的文件動態
> **獨立測試**: 具編輯者角色者草稿續編刪除；撤回送審回狀態並改選審核者再送；動態依角色 tab（近 30 天）；純閱覽者 / 純管理者左側不顯示個人專區入口
> **對應 FR**: spec_us9 FR-001~004
> **前置**: Phase 2、US5（草稿）、US6（送審撤回）

- [ ] T049 [US9] ~~實作個人資料維護 dm/profile~~ **已廢除（2026-07-08 集中化）**：姓名 / Email 延遲切換 / 密碼變更（驗舊）由平台 DP 提供（UCDP004、右上使用者選單、共用 `DP_USER`），DM 不自建個資維護畫面
- [ ] T050 [US9] 實作草稿匣 dm/personal#drafts（編輯者）：未送審 / 被退回 / 已撤回三類、續編進 DM03、刪除須確認不可復原，對應 FR-001
- [ ] T051 [US9] 實作撤回送審 dm/personal#withdraw：回對應狀態（草稿 / 已發布）、站內訊息通知原審核者、可改選新審核者再送，對應 FR-002
- [ ] T052 [US9] 實作我的文件動態 dm/personal#activity（撰寫者 / 審核者視角 tab、近 30 天）+ **個人專區入口可見性（僅具編輯者或審核者角色者顯示）**，對應 FR-003/004

---

## Phase 12: US10 — 已廢止文件查詢（P2）

> **Story 目標**: 管理者稽核查閱已廢止文件
> **獨立測試**: 條件查詢得已廢止清單；點入 read-only 詳細頁；CSV 匯出；一般使用者 URL 被擋
> **對應 FR**: spec_us10 FR-001~005

- [ ] T053 [US10] 實作已廢止查詢頁 dm/obsolete：僅 DM_ADMIN（後端擋 URL）、搜尋（關鍵字 / 分類 / 廢止日期）、清單欄位，對應 FR-001~003
- [ ] T054 [US10] 實作進入 read-only 詳細頁（US4 FR-006，廢止 banner 含廢止附件下載如有）+ CSV 匯出，對應 FR-004/005

---

## Phase 13: US11 — 文件變更歷程查詢（P3）

> **Story 目標**: 管理者跨文件查公開變更紀錄
> **獨立測試**: 條件查詢得發布 / 廢止紀錄；CSV 匯出；撰寫過程 / 閱讀 / 設定變更不出現
> **對應 FR**: spec_us11 FR-001~006

- [ ] T055 [US11] 實作變更歷程查詢頁 dm/changelog：僅 DM_ADMIN、搜尋（日期 / 申請人核准人 / 操作類型）、欄位（時間 / 申請人 / 核准人 / 操作 / 文件 / 版號 / 備註）、僅發布 / 廢止、排除撰寫過程 / 閱讀 / 設定變更，對應 FR-001~003/005
- [ ] T056 [US11] 實作 CSV 匯出 + 確保 `DM_CHANGE_LOG` append-only 永久保留不可竄改，對應 FR-004/006、research §7

---

## Phase 14: US12 — 跨模組教材引用（DM ↔ ET）（P3）

> **Story 目標**: 提供 ET 取用文件之內部服務
> **獨立測試**: ET 以 SRVDM002 取訓練教材清單、SRVDM001 取當前發布版；DM 發布新版 ET 自動取最新；廢止後仍回最後版並通知
> **對應 FR**: spec_us12 FR-001~005
> **前置**: US6（發布 / 廢止狀態）

- [ ] T057 [US12] 實作 SRVDM001（依 DOC_ID 取當前發布版 metadata 與檔案位置；廢止仍回最後版 + obsolete 旗標），參照 contracts/document-service.md、對應 FR-002/004
- [ ] T058 [US12] 實作 SRVDM002（取訓練教材分類有效文件清單，僅含已發布），參照 contracts/document-service.md、對應 FR-001
- [ ] T059 [US12] 實作 DM 文件廢止後通知 ET 教師檢視引用，對應 FR-003

---

## Phase 14b: US13 — 閱讀統計與 KPI（P2）

> **Story 目標**: 管理者 KPI 儀表板 + 每週排程寄 KPI 週報與未讀提醒
> **獨立測試**: 閱覽者下載→已看+1；DM10 逐文件見應看/已看/未看/百分比；發新版重置；排程寄管理者週報(內文+CSV)與未看閱覽者提醒(彙整、全部已發布文件；停用範本則不寄)
> **對應 FR**: spec_us13 FR-001~006
> **前置**: Phase 2（可見性判定 T020a、outbox T018a）、US4（下載記錄 T032）、US1（通知範本 T027，含「未讀提醒」啟用/停用）

- [ ] T059a [US13] 實作閱讀 KPI 計算 dm/service/kpi：依可見性名單（含「全體」、不排除任何人）× 目前發布版之 `DM_DOC_READ`（distinct CREATED_USER）算應看/已看/未看/百分比；發新版以新版計；**應看＝0 顯示「—（無對應閱覽者）」且不列入整體平均閱讀率**，對應 FR-001/003
- [ ] T059b [US13] 實作 KPI 儀表板 dm/kpi（DM10，**僅 DM_ADMIN、後端擋 URL**）：逐文件應看/已看/未看/百分比、關鍵字/分類查詢、CSV 匯出、空資料提示（DM-MSG-DM10-001），對應 FR-002
- [ ] T059c [US13] 實作排程 `SCHDM001` 之 **DM job handler**（於平台 `DP_SCHEDULE` 註冊、由平台引擎每週執行、`DP_SCHEDULE_LOG` 記錄；執行時間讀平台 `DP_PARAM.DM_WEEKLY_SCHED_DAY_TIME`，前綴 `DM_`，預設週一 10:00）：算全部已發布文件 KPI → KPI 週報（管理者，內文摘要 + CSV）+ 未讀提醒（未看閱覽者，一人一信彙整，**涵蓋全部已發布文件；「未讀提醒」範本停用則整批不寄**）呼叫平台唯一發信服務、經 outbox `DP_EMAIL_LOG` 背景寄送，對應 FR-004/004a/005/006、research §9c

---

## Phase 15: 整合與收尾

- [ ] T060 整合測試：P1 文件生命週期端到端（新增 → 送審 → 核准發布 → 文件庫檢索 → 詳細頁 → 編輯新版本 → 簽核 → 廢止申請 → 核准廢止）
- [ ] T061 整合測試：簽核分支（退回 / 撤回送審 / 自動催辦）與單一送審週期約束（不可兩種送審並存）
- [ ] T062 整合測試：跨模組 SRVDM001 / SRVDM002 與 DM 發布新版後 ET 取最新版（無快取延遲）
- [ ] T063 權限與職責分離驗證：指定審核者排除自審、角色複選聯集、已廢止 / 變更歷程 URL 僅管理者、純閱覽者 / 管理者分區可見性
- [ ] T063a 標籤式可見性驗證：閱覽者依可見對象授權（OR + 「全體」）只見允許文件、未授予者僅見「全體」、編輯者 / 審核者 / 管理者見全部；AUDIENCE 停用 soft-retire 不收回既有可見性；後端 API 亦套過濾（防繞過 UI），對應 spec.md SC-010
- [ ] T063b 閱讀 KPI 與排程驗證：下載記已看（預覽不記、同人同版去重）、發新版重置；DM10 應看/已看/未看/百分比正確；SCHDM001 於管理者設定之每週時間（預設週一 10:00、可改）寄管理者週報（內文+CSV）與未看閱覽者提醒（彙整、全部已發布文件；停用範本則不寄），經平台 outbox `DP_EMAIL_LOG` 非同步不阻塞，對應 spec.md SC-011
- [ ] T064 永久保留驗證：版本軟刪除不可實體刪、`DM_CHANGE_LOG` / `DM_USER_ROLE_LOG` append-only 不可竄改 / 刪除
- [ ] T065 func_name 唯一性驗證：並發發布同 func_name 由部分唯一索引把關 + 友善訊息
- [ ] T066 安全性檢查：SSO 認證邊界、檔案上傳大小 / 類型限制、密碼雜湊、個資（Email / 姓名）處理
- [ ] T067 效能驗證：文件庫檢索（多條件 + 標籤 AND + 分頁）回應時間 **P95 ≤ 2 秒**，對應 spec.md SC-001

---

## 依賴關係

```
Phase 1 (設定) → Phase 2 (共用元件)
    ↓
Phase 3 (US2 存取閘＝Phase 2 T014；登入由 DP 提供) ── P1 ── 其他 US 之存取前置
    ↓
Phase 4 (US1 系統設定) ── P1 ── 受控資料 / 角色為其他 US 前置
    ↓
Phase 5 (US3 文件庫) ┐
Phase 6 (US4 詳細頁) ┤── P1（依 US5 文件資料；US3/US4 可部分平行）
Phase 7 (US5 新增編輯) ┤
Phase 8 (US6 簽核) ────┘（依 US5 送審來源）
    ↓
Phase 9 (US7 儀表板) / Phase 10 (US8 廢止) / Phase 11 (US9 個人專區) / Phase 12 (US10 已廢止) / Phase 14b (US13 閱讀 KPI) ── P2
    ↓
Phase 13 (US11 變更歷程) / Phase 14 (US12 跨模組) ── P3
    ↓
Phase 15 (整合收尾)
```

> **建置順序提醒**：Phase 編號依 **US 編號**排列，非嚴格建置順序。US3（檢索）/ US4（詳細頁）之完整測試需先有 US5（新增編輯）/ US6（簽核發布）產生並發布文件；故 P1 群組內建議 **US5 / US6 先行或與 US3 / US4 同步**開發（見實作策略 Sprint 3：Phase 5–8 同一 Sprint）。各 Phase 之「前置」欄已標明依賴。

**可平行開發的機會**：
- Phase 1 內 T002~T012 可平行（不同 Table）
- Phase 2 內 T014~T020 可平行（獨立中介層 / 服務 / 工具）
- US3（檢索）與 US4（詳細頁）在文件資料就緒後可部分平行
- P2 之 US7 / US8 / US9 / US10 多可平行（不同畫面）
- 各 Phase 內標記 [P] 的任務可平行執行

---

## 實作策略

**MVP 範圍**: US1 系統設定 + US5 新增編輯 + US6 簽核（Phase 4/7/8；US2 存取閘於 Phase 2 T014、登入由平台 DP 提供）—— 編輯者可建立文件、送審核發布，登入 / 存取控管就緒，即構成最小可用文件簽核發布鏈；US3/US4 緊接補足檢索與閱讀。

**增量交付**:
1. Sprint 1: Phase 1-2（設定 + SSO / 授權 / 檔案 / DOC_ID / 通知 / 狀態機共用）
2. Sprint 2: Phase 4（US1 系統設定；US2 存取閘已於 Phase 2 T014）→ 存取控管就緒、完成基礎設定
3. Sprint 3: Phase 5-8（US3 文件庫 + US4 詳細頁 + US5 新增編輯 + US6 簽核）→ 文件生命週期 MVP 成形
4. Sprint 4: Phase 9-12（US7 儀表板 + US8 廢止 + US9 個人專區 + US10 已廢止查詢）
5. Sprint 5: Phase 13-15（US11 變更歷程 + US12 跨模組 + 整合收尾）→ 全功能交付

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總任務數 | 75（82 − 3 集中化〔T012 範本/參數 migration、T012a 佇列 migration、T018a outbox worker 改由平台 DP 承載〕 − 4 認證/個資移 DP〔T021~T023 登入/註冊/忘記密碼、T049 個資維護，由平台 DP 提供〕）|
| Phase 1 設定 | 14（+T006a DM_USER_TAG、+T009b DM_DOC_READ；T012 範本/參數、T012a 佇列 migration 已廢除——集中於平台 DP）|
| Phase 2 共用 | 8（+T020a 可見性判定；T018a outbox worker 改由平台發信引擎承載，DM 僅呼叫平台發信服務）|
| US2 存取閘 | 存取閘＝T014（Phase 2）；登入/註冊/忘記密碼由平台 DP 提供，T021~T023 廢除 |
| US1 系統設定 | 5（+T027a 可見對象授權；DM 端＝轉接層模組端+業務規則+種子，維護 UI 在 DP 後台）|
| US3 文件庫與檢索 | 4（+T028a 可見性過濾）|
| US4 文件詳細頁瀏覽 | 4（T032 加下載記 DM_DOC_READ）|
| US5 文件新增與編輯 | 6（+T035a 可見對象必填）|
| US6 簽核處理 | 6（+T042a 文件發布通知：撰寫者+相符閱覽者）|
| US7 系統儀表板 | 2 |
| US8 文件廢止申請 | 2 |
| US9 個人專區 | 3（草稿匣 / 撤回送審 / 我的文件動態；T049 個資維護廢除——由平台 DP 提供）|
| US10 已廢止文件查詢 | 2 |
| US11 文件變更歷程查詢 | 2 |
| US12 跨模組教材引用 | 3 |
| US13 閱讀統計與 KPI | 3（T059a KPI 計算 / T059b DM10 儀表板 / T059c SCHDM001 排程）|
| 整合收尾 | 10（+T063a 可見性、+T063b KPI）|
| 可平行機會 | Phase 1(13 組)、Phase 2(8 組)、US3+US4、P2 多畫面 |
