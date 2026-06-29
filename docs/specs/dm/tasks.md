# 開發任務清單：文件管理模組（Document Management）

**模組代碼**: DM | **日期**: 2026-06-24
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md) | **資料模型**: [data-model.md](data-model.md) | **研究**: [research.md](research.md) | **契約**: [contracts/document-service.md](contracts/document-service.md)

> DM **獨立於主系統 DP** 部署，與 ET 共用 user table（SSO）；自身 14 張表。標準欄位省略 SITE / HOSPITAL（research §1）。檔案存檔案系統 / DB 存 metadata。

---

## Phase 1: 專案設定

- [ ] T001 建立文件管理模組專案結構，依 plan.md 文件結構建立 dm/ 目錄與子目錄
- [ ] T002 [P] 建立資料庫 Migration：`USER` 共用使用者主檔（USER_ID PK、EMAIL UNIQUE、PASSWORD_HASH、USER_NAME、EMAIL_PENDING_*）；**與 ET 共用，schema 需與 ET 協調**，參照 data-model.md
- [ ] T003 [P] 建立資料庫 Migration：`DM_USER_ROLE`（USER_ID×ROLE_CODE，唯一約束）與 `DM_USER_ROLE_LOG`（append-only 角色異動），參照 data-model.md
- [ ] T004 [P] 建立資料庫 Migration：`DM_CATEGORY`（CATEGORY_CODE PK、IS_BUILTIN、IS_ENABLED），參照 data-model.md
- [ ] T005 [P] 建立資料庫 Migration：`DM_FUNC`（FUNC_CODE PK、IS_ENABLED），參照 data-model.md
- [ ] T006 [P] 建立資料庫 Migration：`DM_TAG_GROUP` 與 `DM_TAG`（FK→TAG_GROUP、IS_ENABLED），參照 data-model.md
- [ ] T007 [P] 建立資料庫 Migration：`DM_DOCUMENT`（DOC_ID PK、CATEGORY_CODE/FUNC_CODE/CURRENT_VERSION_ID FK、STATUS）+ **部分唯一索引**（FUNC_CODE where CATEGORY='MANUAL' AND STATUS='PUBLISHED'，research §5），參照 data-model.md
- [ ] T008 [P] 建立資料庫 Migration：`DM_DOC_VERSION`（VERSION_ID PK、FK→DOCUMENT、VERSION_NO、CHANGE_SUMMARY、FILE_*、STATUS、APPROVER、PUBLISHED_DATE），參照 data-model.md
- [ ] T009 [P] 建立資料庫 Migration：`DM_DOC_TAG`（DOC×TAG 明細，唯一約束），參照 data-model.md
- [ ] T010 [P] 建立資料庫 Migration：`DM_REVIEW`（送審週期：REVIEW_TYPE、ASSIGNED_REVIEWER、APPROVER、STATUS、SUBMIT/COMPLETE_DATE、REASON），參照 data-model.md
- [ ] T011 [P] 建立資料庫 Migration：`DM_CHANGE_LOG`（append-only 公開變更歷程：OPERATION、APPLICANT、APPROVER、NOTE），參照 data-model.md
- [ ] T012 [P] 建立資料庫 Migration：`DM_NOTIFY_TEMPLATE`（TEMPLATE_CODE PK、SUBJECT/BODY、CHANNEL、IS_ENABLED）與 `DM_PARAM`（PARAM_ID PK，前綴 DM_），參照 data-model.md
- [ ] T013 建立種子資料：4 內建分類（SOP/MANUAL/TRAINING/OTHER + 分類碼）、4 標籤組（MODULE/ROLE/NATURE/LEGAL）、7 通知範本、DM_PARAM（`DM_REMIND_THRESHOLD`=7、`DM_FILE_MAX_MB`=50、`DM_FILE_TYPES`），參照 data-model.md 代碼表

---

## Phase 2: 基礎共用元件

> 為所有 User Story 之阻斷性前置（SSO 認證、授權、檔案、DOC_ID、通知、狀態機）。

- [ ] T014 [P] 實作 SSO 認證接入 dm/middleware/auth：共用 user table 驗證帳密、未登入擋下、首次登入自動授予閱覽者；**獨立於 DP、不走 DP RBAC**，對應 spec_us2 FR-001~003
- [ ] T015 [P] 實作角色授權工具 dm/util/authz：4 角色（DM_ADMIN/EDITOR/REVIEWER/VIEWER）複選聯集判定；提供「指定審核者排除本人」與「管理者自我保護」共用檢核，對應 spec_us1 FR-005/006、spec_us5 FR-006
- [ ] T016 [P] 實作檔案儲存服務 dm/service/file_store：上傳至檔案系統 / 物件儲存、DB 存 metadata（FILE_*）、單檔上限讀 `DM_FILE_MAX_MB`、依 MIME 判定可預覽（PDF/圖片）/ 僅下載（Office），參照 research §3/§10
- [ ] T017 [P] 實作 DOC_ID 產生器 dm/util/docid：`DM-{分類碼}-{6 位流水號}`、流水號依分類各自獨立、草稿建立時配號，參照 research §2
- [ ] T018 [P] 實作通知服務 dm/service/notify：依 `DM_NOTIFY_TEMPLATE` 組信、經 Email Server（SMTP）+ 站內訊息發送；停用範本不發 Email、自動催辦僅站內，對應 spec_us1 FR-007、research §9
- [ ] T019 [P] 實作送審週期 / 狀態機服務 dm/service/review：DM_REVIEW 建立 / 核准 / 退回 / 撤回；約束「同一文件不可同時兩種送審」（單一 PENDING_*），參照 research §4
- [ ] T020 [P] 實作受控資料維護共用 dm/service/catalog：分類 / func_name / 標籤之新增 / 改名 / 啟用停用、**不開放刪除**、停用後既有引用保留、僅影響後續下拉，對應 spec_us1 FR-001、research §參數維護

---

## Phase 3: US2 — 登入 / 註冊 / 忘記密碼（P1）

> **Story 目標**: 使用者以共用帳號登入 DM、自行註冊、重設密碼
> **獨立測試**: 既有帳密登入導向 DM00；未註冊 Email 得提示；註冊後以新帳號登入；忘記密碼於連結有效期內重設
> **對應 FR**: spec_us2 FR-001~006

- [ ] T021 [US2] 實作登入頁與驗證 dm/login：帳密驗證共用 user table、錯誤分流（查無帳號 / 密碼錯誤）、成功寫 session 並導向 DM00，對應 FR-001~003
- [ ] T022 [US2] 實作註冊流程：Email 唯一檢核、兩次密碼一致、建立 user table 紀錄並授予閱覽者、跳回登入頁預填 Email，對應 FR-004
- [ ] T023 [US2] 實作忘記密碼：寄密碼重設連結至 Email（30 分鐘有效）、逾時拒絕、重設密碼頁，對應 FR-005

---

## Phase 4: US1 — 系統設定（P1）

> **Story 目標**: 管理者維護參數 / 權限 / 通知範本
> **獨立測試**: 新增自訂分類（唯一分類碼）、對使用者指派編輯者並即時生效、調整催辦門檻
> **對應 FR**: spec_us1 FR-001~008
> **前置**: Phase 2 授權（T015）、受控資料維護（T020）、通知（T018）

- [ ] T024 [US1] 實作參數設定頁 dm/admin/params：分類（含唯一分類碼、建立後鎖定）/ func_name / 標籤之共通維護（T020），對應 FR-001~003
- [ ] T025 [US1] 實作催辦門檻設定：值域 1–30 天（預設 7）、寫 `DM_PARAM.DM_REMIND_THRESHOLD`，對應 FR-004
- [ ] T026 [US1] 實作權限管理頁 dm/admin/roles：列共用 user table 使用者、4 角色複選即時生效、寫 `DM_USER_ROLE_LOG`、顯示「最後異動」欄、自我保護、不檢核 0 管理者，對應 FR-005/006/008
- [ ] T027 [US1] 實作通知範本維護 dm/admin/templates：7 內建事件主旨 / 內文編輯與啟用停用、自動催辦含門檻，對應 FR-007

---

## Phase 5: US3 — 文件庫與檢索（P1）

> **Story 目標**: 多條件檢索已發布文件、線上操作手冊檢索
> **獨立測試**: 關鍵字 + 標籤搜尋得已發布清單；選系統操作手冊出現 func_name 下拉得唯一手冊
> **對應 FR**: spec_us3 FR-001~006（原 FR-007 主系統反查已於 2026-06-26 移除）
> **前置**: Phase 2、US5（文件資料）

- [ ] T028 [US3] 實作文件庫搜尋 dm/library：多條件（關鍵字 / 分類 / 作者 / 標籤 AND / 發布日期區間）、僅顯示已發布目前版本（含廢止待簽核）、灰字標籤、分頁排序，對應 FR-001~003/005
- [ ] T029 [US3] 實作系統操作手冊檢索：分類為 MANUAL 時顯示 func_name 下拉、依作業項目得唯一手冊，對應 FR-004
- [ ] T030 [US3] 實作「新增文件」入口（依編輯者角色顯示）導向 DM03，對應 FR-006

---

## Phase 6: US4 — 文件詳細頁瀏覽（P1）

> **Story 目標**: 閱讀目前版本、預覽 / 下載、版本歷程、read-only
> **獨立測試**: 下載並預覽 PDF；展開版本歷程；舊版僅預覽；編輯者見編輯 / 廢止入口
> **對應 FR**: spec_us4 FR-001~006
> **前置**: Phase 2（檔案服務 T016）

- [ ] T031 [US4] 實作詳細頁版面 dm/detail：上方標題列（文件名稱 / DOC_ID / 版本 / 狀態）+ 右側文件資訊面板（不重複），對應 FR-001
- [ ] T032 [US4] 實作文件檔案區：PDF / 圖片內嵌預覽 + 下載、Office 僅下載、僅目前版本可下載，對應 FR-002/004
- [ ] T033 [US4] 實作版本歷程抽屜：列所有版本（版號 / 撰寫者 / 發布時間 / 核准者 / 變更摘要）、舊版僅預覽，對應 FR-003/004
- [ ] T034 [US4] 實作動作入口與 read-only 模式：編輯 / 廢止入口（角色、送審中失效）、自 DM06 進入之 read-only（隱藏檔案+資訊、版本歷程自動展開、僅預覽 + 廢止 banner），對應 FR-005/006

---

## Phase 7: US5 — 文件新增與編輯（P1）

> **Story 目標**: 新增 / 上傳新版本、送簽、存草稿
> **獨立測試**: 新增填妥上傳 PDF 送簽轉送審中；編輯新版本身份欄唯讀；Office 跳提醒；存草稿可續編
> **對應 FR**: spec_us5 FR-001~008
> **前置**: Phase 2（DOC_ID T017、檔案 T016、送審 T019、授權 T015）

- [ ] T035 [US5] 實作新增模式 dm/editor#create：DOC_ID 配號、必填（名稱 / 分類 / 摘要 / 審核者）、標籤選填、首版版號建議 v1.0，對應 FR-001
- [ ] T036 [US5] 實作編輯模式 dm/editor#edit：文件名稱 / 分類 / func_name 唯讀、版本號建議（+0.1 / Major / Minor），對應 FR-003/004
- [ ] T037 [US5] 實作 func_name 單選 + **唯一檢核**（送簽 / 發布前檢核同 func_name 無其他已發布手冊），對應 FR-002
- [ ] T038 [US5] 實作檔案上傳（單檔 ≤ 50MB、Office 跳預覽提醒 + 橘色警示條、PDF / 圖片不提醒），對應 FR-005
- [ ] T039 [US5] 實作指定審核者下拉（排除自己）+ 儲存為草稿 + 送交簽核（轉送審中、通知），對應 FR-006/007/008

---

## Phase 8: US6 — 簽核處理（P1）

> **Story 目標**: 審核者核准 / 退回送審項目
> **獨立測試**: 待簽核清單僅顯示自己項目（無指定審核者欄）；核准並發布轉已發布並寫變更歷程；退回回草稿並通知
> **對應 FR**: spec_us6 FR-001~007
> **前置**: Phase 2（送審 T019、通知 T018）、US5（送審來源）

- [ ] T040 [US6] 實作待簽核清單 dm/review：僅顯示指定審核者 = 當前登入者之項目、欄位（文件 / 分類 / 版本 / 送審者 / 送審時間 / 停留天數）、無「指定審核者」欄，對應 FR-001
- [ ] T041 [US6] 實作簽核明細：下載送審檔案（不預覽）、新版本新舊版並列下載比對、廢止對象與原因，對應 FR-002
- [ ] T042 [US6] 實作核准並發布 / 廢止：**單一交易**完成版本切換（新版 PUBLISHED、舊版 SUPERSEDED、更新 CURRENT_VERSION_ID）/ 廢止下架、寫 `DM_CHANGE_LOG`、通知撰寫者，對應 FR-003/005、research §6
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

- [ ] T047 [US8] 實作廢止申請對話框：必填廢止原因、選指定審核者（排除自己）、轉 PENDING_OBSOLETE 並通知，對應 FR-001/002
- [ ] T048 [US8] 實作廢止待簽核行為：仍顯示於文件庫且可下載、阻擋同時新版本送審、撤回 / 核准 / 退回交由 US9 / US6，對應 FR-003/004/005

---

## Phase 11: US9 — 個人專區（P2）

> **Story 目標**: 個人資料 / 草稿 / 撤回送審 / 我的文件動態
> **獨立測試**: 改姓名 / Email 驗證 / 密碼驗舊；草稿續編刪除；撤回送審回狀態；動態依角色 tab；純閱覽者僅見個人資料
> **對應 FR**: spec_us9 FR-001~007
> **前置**: Phase 2、US5（草稿）、US6（送審撤回）

- [ ] T049 [US9] 實作個人資料維護 dm/profile：姓名直接存、Email 變更新信箱驗證後切換（30 分鐘）、密碼變更驗舊密碼並同步 user table，對應 FR-001~003
- [ ] T050 [US9] 實作文件草稿區（編輯者）：未送審 / 被退回 / 已撤回三類、續編進 DM03、刪除須確認不可復原，對應 FR-004
- [ ] T051 [US9] 實作撤回送審：回對應狀態（草稿 / 已發布）、站內訊息通知原審核者、可改選新審核者再送，對應 FR-005
- [ ] T052 [US9] 實作我的文件動態（撰寫者 / 審核者視角 tab、近 30 天）+ 分區可見性（純閱覽者 / 管理者僅個人資料維護），對應 FR-006/007

---

## Phase 12: US10 — 已廢止文件查詢（P2）

> **Story 目標**: 管理者稽核查閱已廢止文件
> **獨立測試**: 條件查詢得已廢止清單；點入 read-only 詳細頁；CSV 匯出；一般使用者 URL 被擋
> **對應 FR**: spec_us10 FR-001~005

- [ ] T053 [US10] 實作已廢止查詢頁 dm/obsolete：僅 DM_ADMIN（後端擋 URL）、搜尋（關鍵字 / 分類 / 廢止日期）、清單欄位，對應 FR-001~003
- [ ] T054 [US10] 實作進入 read-only 詳細頁（US4 FR-006）+ CSV 匯出，對應 FR-004/005

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

## Phase 15: 整合與收尾

- [ ] T060 整合測試：P1 文件生命週期端到端（新增 → 送審 → 核准發布 → 文件庫檢索 → 詳細頁 → 編輯新版本 → 簽核 → 廢止申請 → 核准廢止）
- [ ] T061 整合測試：簽核分支（退回 / 撤回送審 / 自動催辦）與單一送審週期約束（不可兩種送審並存）
- [ ] T062 整合測試：跨模組 SRVDM001 / SRVDM002 與 DM 發布新版後 ET 取最新版（無快取延遲）
- [ ] T063 權限與職責分離驗證：指定審核者排除自審、角色複選聯集、已廢止 / 變更歷程 URL 僅管理者、純閱覽者 / 管理者可見性
- [ ] T064 永久保留驗證：版本軟刪除不可實體刪、`DM_CHANGE_LOG` / `DM_USER_ROLE_LOG` append-only 不可竄改 / 刪除
- [ ] T065 func_name 唯一性驗證：並發發布同 func_name 由部分唯一索引把關 + 友善訊息
- [ ] T066 安全性檢查：SSO 認證邊界、檔案上傳大小 / 類型限制、密碼雜湊、個資（Email / 姓名）處理
- [ ] T067 效能驗證：文件庫檢索（多條件 + 標籤 AND + 分頁）回應時間 **P95 ≤ 2 秒**，對應 spec.md SC-001

---

## 依賴關係

```
Phase 1 (設定) → Phase 2 (共用元件)
    ↓
Phase 3 (US2 登入) ── P1 ── 其他 US 之存取前置
    ↓
Phase 4 (US1 系統設定) ── P1 ── 受控資料 / 角色為其他 US 前置
    ↓
Phase 5 (US3 文件庫) ┐
Phase 6 (US4 詳細頁) ┤── P1（依 US5 文件資料；US3/US4 可部分平行）
Phase 7 (US5 新增編輯) ┤
Phase 8 (US6 簽核) ────┘（依 US5 送審來源）
    ↓
Phase 9 (US7 儀表板) / Phase 10 (US8 廢止) / Phase 11 (US9 個人專區) / Phase 12 (US10 已廢止) ── P2
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

**MVP 範圍**: US2 登入 + US1 系統設定 + US5 新增編輯 + US6 簽核（Phase 3/4/7/8）—— 編輯者可建立文件、送審核發布，閱讀者可登入，即構成最小可用文件簽核發布鏈；US3/US4 緊接補足檢索與閱讀。

**增量交付**:
1. Sprint 1: Phase 1-2（設定 + SSO / 授權 / 檔案 / DOC_ID / 通知 / 狀態機共用）
2. Sprint 2: Phase 3-4（US2 登入 + US1 系統設定）→ 可登入並完成基礎設定
3. Sprint 3: Phase 5-8（US3 文件庫 + US4 詳細頁 + US5 新增編輯 + US6 簽核）→ 文件生命週期 MVP 成形
4. Sprint 4: Phase 9-12（US7 儀表板 + US8 廢止 + US9 個人專區 + US10 已廢止查詢）
5. Sprint 5: Phase 13-15（US11 變更歷程 + US12 跨模組 + 整合收尾）→ 全功能交付

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總任務數 | 67 |
| Phase 1 設定 | 13 |
| Phase 2 共用 | 7 |
| US2 登入 / 註冊 / 忘記密碼 | 3 |
| US1 系統設定 | 4 |
| US3 文件庫與檢索 | 3 |
| US4 文件詳細頁瀏覽 | 4 |
| US5 文件新增與編輯 | 5 |
| US6 簽核處理 | 5 |
| US7 系統儀表板 | 2 |
| US8 文件廢止申請 | 2 |
| US9 個人專區 | 4 |
| US10 已廢止文件查詢 | 2 |
| US11 文件變更歷程查詢 | 2 |
| US12 跨模組教材引用 | 3 |
| 整合收尾 | 8 |
| 可平行機會 | Phase 1(11 組)、Phase 2(7 組)、US3+US4、P2 多畫面 |
