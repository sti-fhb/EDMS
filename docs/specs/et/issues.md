# 開發 Issues 清單：教育訓練文件管理模組（Education & Training）

**模組代碼**: ET | **日期**: 2026-06-09（2026-07-02 依客戶 6 項需求變更更新）
**來源**: [plan.md](plan.md) §功能分群與開發順序 | [tasks.md](tasks.md) | [spec.md](spec.md)

> 每張 Issue 為一個**功能畫面之垂直切割**（DB + API + UI + 驗收條件），可獨立開發、測試與交付。
> Issue #0 為基礎建設，其餘依 plan.md 之 P1 / P2 / P3 階段排序。
> **2026-07-02 變更**：既有 Issue 編號不重排、內容就地改寫（#2 / #3 / #4 / #5 / #6 / #7 / #8 / #9 / #11 / #13 / #14）；新增 **#15 課後問卷、#16 排程統計與提醒、#17 ET09 通知範本維護**。新任務見 tasks.md Phase 17（T125 起）。

---

## Issue 總覽

| # | 標題 | 對應 | 階段 | 涵蓋 Tasks | 主要前置 |
|---|------|------|------|-----------|---------|
| 0 | 專案建置與基礎建設 | — | Setup + Foundational | T001 ~ T032 + T125 ~ T129（37 任務）| 無 |
| 1 | ET 登入後角色導向與學員角色自動授予 | US2 / UCET012 | P1-核心 | T034, T035, T037（3 任務；T033 / T036 / T038 ~ T040 廢除）| #0 |
| 2 | ET 權限與標籤指派轉接層（DP 後台呼叫）| US1 / UCET010 | P1-核心 | T041 ~ T045 + T130（6 任務；T045 / T130 改寫為轉接層）| #0 |
| 3 | ET02 課程建立與編輯（含標籤 / 起訖 / 問卷建立）| US3 / UCET002 | P1-核心 | T046 ~ T057 + T131, T138, T142（15 任務）| #2 |
| 4 | ET04 我的課程與加入新課程 | US4 / UCET007 | P1-核心 | T058 ~ T062（5 任務）| #3 |
| 5 | ET05 章節學習 | US5 / UCET008 | P1-核心 | T063 ~ T072（10 任務）| #3, #4 |
| 6 | ET06 線上測驗作答（含歷次明細回看）| US6 / UCET009 | P1-核心 | T073 ~ T083 + T150（12 任務）| #3, #5 |
| 7 | ET01 課程列表瀏覽 | US7 / UCET001 | P2-延伸 | T084 ~ T085（2 任務）| #3 |
| 8 | ET02 邀請學員（標籤自動邀請＋寄信）| US8 / UCET004 | P2-延伸 | T086 ~ T090, T136, T137（7 任務；T091 廢除）| #3, #2 |
| 9 | ET03 學員學習狀況追蹤（含作答明細 / 問卷結果）| US9 / UCET005 | P2-延伸 | T092 ~ T096 + T144, T149（7 任務）| #3, #4, #5, #6, #15 |
| 10 | 個人資料維護導向連結 | US10 / UCET011 | P2-延伸 | T100（1 任務；T097 ~ T099 / T101 廢除）| — |
| 11 | ET02 課程關閉與再開課 | US11 / UCET003 | P3-輔助 | T102 ~ T106（5 任務）| #3, #6 |
| 12 | ET03 待加入邀請追蹤 | US12 / UCET006 | P3-輔助 | T107 ~ T111（5 任務）| #8 |
| 13 | 跨 US 補強：章節更新通知 + 擁有者轉讓 | — | 補強 | T112 ~ T115（4 任務）| #3, #2 |
| 14 | 整合測試 + 安全 + 部署 | — | 收尾 | T116 ~ T124 + T152 ~ T155（13 任務）| 全部 |
| 15 | 課後問卷（建立 / 填寫）| US13 / UCET013（建立屬 US3）| P2-延伸 | T141 ~ T143（3 任務）| #3, #5 |
| 16 | 排程統計與提醒（SCHET001 / SCHET002）| US14 / UCET014 | P2-延伸 | T139, T145 ~ T148, T164（6 任務）| #4, #5, #17 |

> **2026-08-19 交付前自檢調整**：(1) #1 / #2 / #10 / #17 依 2026-07-08 集中化**大幅裁減或改寫**——登入 / 註冊 / 忘記密碼、個人資料維護、權限管理 UI、通知範本 UI 皆已由平台 DP 上線提供，ET 改為「轉接層 provider + 業務規則」；共廢除 9 項任務。(2) Issue #0 新增 4 張表（T165 ~ T168）。(3) Issue #16 新增週報 CSV 下載端點（T164，取代郵件附件）。
| 17 | ET 通知範本 seed 與啟停檢查 | US15 / UCET015 | P3-輔助 | T151（1 任務，改寫）| #0 |
| 18 | ET03 學員線下考核核可 | US16 / UCET016 | P2-延伸 | T156 ~ T161, T163（7 任務）| #3, #6, #17 |
| 19 | ET10 核可查詢 | US17 / UCET017 | P2-延伸 | T162（1 任務）| #18 |

---

## Issue #0：專案建置與基礎建設

**對應規格**：plan.md §文件結構、§技術背景、§系統參數與初始化；data-model.md
**階段**：Setup + Foundational（為所有 Issue 之前置）
**前置條件**：
- PostgreSQL 已建置；應用伺服器環境就緒
- `DP_USER` 由平台模組 DP 建立與定義（ET 以 USER_ID 引用、不自建帳號表）
- 平台 DP 已上線並**已為 ET 備妥掛鉤**（fail-closed，等 ET 註冊）：`module_admin_gate` / `module_provisioning_gate`（`dp/user/activation.py` 已在呼叫）/ `module_assign_registry` / `module_role_gate`；排程引擎白名單已含 `app.et.`、`DP_SCHEDULE` 已預留 SCHET001 / SCHET002 兩列（`IS_ENABLED=false`）
- ~~SMTP 伺服器資訊就緒~~ **不需要**：ET 不自建 SMTP 連線與寄件佇列，寄信一律經平台 `NotifyService`（2026-07-08 集中化）

**涵蓋 Tasks**：
- T001 建立 ET 模組專案結構（`backend/app/et/{功能}/` router / service / repository / schemas / models + deps / bootstrap / provider；migration 於 `backend/alembic/versions/`；前端 `frontend/src/et/{功能}/`）（2026-08-19 對齊專案實際結構）
- T002 ~ T020、T165 ~ T168 建立 ET 22 張表 Migration（帳號主檔 `DP_USER` 由平台模組 DP 建立、ET 引用不自建；T004 / T005 為 ET_TAG / ET_USER_TAG，2026-07-02 改寫）
- T125 ~ T129 建立 2026-07-02 新增表 Migration（ET_COURSE_TAG、ET_SURVEY 五表、ET_WEEKLY_STAT）；通知範本改 seed 至平台 `DP_NOTIFY_TEMPLATE`（`MODULE=ET`，7 類可維護範本〔2026-07-17 增列 APPROVAL_PASSED〕；表由平台 DP 建，ET 不自建，2026-07-08 集中化）
  > 線下核可表 ET_APPROVAL 與 ET_COURSE.REQUIRE_APPROVAL 欄位之 Migration（T156）於 Issue #18 建立（2026-07-17）
- T021 定義 Lookup 代碼**應用層常數**（9 類，**不建表、不 seed**——2026-08-20 定案，比照 DM 之模組層常數作法）；T022 ET_TAG 種子 5 筆（全體 / 護理師 / 行政人員 / 軍人 / 醫檢師）；T023 ET 系統參數（前綴 `ET_`）seed 至平台 `DP_PARAM`（ET 不自建參數表）
- T024 系統初始化第一個管理者 Seed Script
- T025 ~ T032 共用元件（**2026-08-19 裁減後為 6 項**）：
  - T025 **ET 模組存取閘與啟動註冊**（比照 DM `deps.py` + `bootstrap.py`）：重用平台 `get_jwt_payload`、查 `ET_USER_ROLE` 要求至少一個 ET 角色；啟動期註冊四個聚合閘 checker / provider
  - T026 細粒度角色檢核工具（比照 DM `roles/authz.has_role`）
  - T028 樂觀鎖檢核工具（`WHERE VERSION = ?`）
  - T029 DM Service Client（⚠️ **被 #183 阻塞**，見下方注意事項）
  - T031 邀請 token 產生器（≥ 32 bytes CSPRNG）
  - T032 邀請碼產生器（8 碼純數字、全域唯一）
  - ~~T027 ET 參數載入工具~~ **廢除**：直接用平台 `ParamService`（`get_param_value` / `get_int_param` / `get_param_list`）
  - ~~T030 平台發信服務 Client~~ **廢除**：直接用平台 `NotifyService.send_email`

**驗收條件**：
1. **28 張** ET 業務表全部建立（線下核可 ET_APPROVAL 於 Issue #18 建立，**ET 業務表共 29 張**；另引用平台 DP 之 `DP_USER` / `DP_PARAM` / `DP_NOTIFY_TEMPLATE`，ET 不自建）；標準稽核欄位（CREATED_USER / CREATED_DATE / UPDATED_USER / UPDATED_DATE）齊備
   > **2026-08-19 新增 4 張**：`ET_MATERIAL_VIDEO`（含 **DURATION_SEC**，覆蓋率分母）、`ET_MATERIAL_DOC`（`DOC_ID` VARCHAR(20)）、`ET_PROGRESS_VIDEO`（逐支影片覆蓋率）、`ET_QUIZ_RETRY_RESET`（重考次數重置基準，append-only）——對應 T165 ~ T168
2. 9 類 Lookup 代碼以**應用層常數**定義完成（**不建表、不 seed**，比照 DM）；5 筆 ET_TAG 種子載入成功；ET 系統參數（平台 `DP_PARAM` 前綴 `ET_`）、7 類通知範本（平台 `DP_NOTIFY_TEMPLATE` `MODULE=ET`；含 APPROVAL_PASSED）seed 由平台 DP 載入成功
3. IT 透過 Seed Script 寫入 `DP_USER` + ET_USER_ROLE（ROLE=ADMIN）後，第一位管理者可登入
4. ET 模組存取閘可驗證平台 DP 之 JWT（重用 `get_jwt_payload`）並注入 USER_ID 與 ET 角色清單；未具任何 ET 角色者回 403
5. 樂觀鎖工具於版本不符時回傳明確衝突訊息
6. DM Service Client 可成功呼叫 SRVDM001 / SRVDM002 取得文件清單與 metadata ⚠️ **本條被 #183 阻塞**（DM 端 T057 / T058 尚未實作，且 DM Service 尚未自 `app/services/__init__.py` 匯出）——交付時以 stub 開發並標外部阻塞，待 #183 完成後回歸驗證
7. 經平台 `NotifyService.send_email` 可寄送一封測試信（傳 `template_code` + 變數，寫入 `DP_EMAIL_LOG` outbox 由平台 worker 寄出）；**ET 不直接連 SMTP**
8. Token 產生器產出之 token 至少 32 bytes 且 cryptographically secure

**Labels**：`priority:P0`, `ET-教育訓練文件管理`（比照 DM Foundation #127）

---

## Issue #1：ET 登入後角色導向與學員角色自動授予（2026-08-19 大幅裁減）

**對應規格**：[spec_us2.md](spec_us2.md)、UCET012、畫面：**無（登入頁由平台 DP 提供，畫面碼 DP01–DP03）**
**階段**：P1-核心
**前置條件**：
- Issue #0 完成（ET_USER_ROLE 表 + ET 模組存取閘就緒）
- 平台 DP 之登入 / 註冊 / 忘記密碼已上線（DP Issue #31 / #39 / #47 / #56，**均已完成**）

> **2026-08-19 裁減說明**：本 issue 原名「登入頁（登入 / 註冊 / 忘記密碼）」、涵蓋 T033 ~ T040 共 8 項，要求 ET 自建登入頁與帳密驗證 / 註冊 / 忘記密碼 endpoint。2026-07-08 集中化後規格已改為「由平台 DP 提供」，但任務與 issue 未同步裁減；交付前自檢確認 **DP 對應功能皆已上線**，故本 issue 縮為 ET 專屬的兩項業務規則。

**涵蓋 Tasks**：
- T034 ET_USER_ROLE Repository（依 USER_ID 查角色清單、寫入新角色）
- T035 ET 登入後角色導向（管理者 → ET07、教師 → ET01、學員 → ET04；多重角色預設教師 ET01）
- T037 ET 端自動授予「學員」角色（帳號建立當下寫入 ET_USER_ROLE，受訓單位標籤預設「未指派」）
- ~~T033 / T036 / T038 / T039 / T040~~ — 廢除（登入頁 UI、帳密驗證、忘記密碼、密碼重設頁與信件範本皆由平台 DP 提供）

**驗收條件**：
1. 使用者於**平台 DP 登入頁**登入成功後進入 ET，依 ET 角色導向預設首頁（管理者 → ET07、教師 → ET01、學員 → ET04）
2. 具多重角色者預設導向教師首頁（ET01），其餘角色首頁可由 ET 側邊選單切換
3. 新帳號建立（DP 自助註冊或管理者代建）後，ET_USER_ROLE 自動出現一筆 ROLE=STUDENT，受訓單位標籤為「未指派」
4. 未具任何 ET 角色之已登入使用者存取 ET 端點時被 ET 模組存取閘擋下（403）
5. **不驗收**帳密驗證 / 防帳號列舉 / 密碼雜湊 / 重設連結 TTL —— 屬平台 DP 職責，已於 DP Issue #31 / #47 驗收

**Labels**：`P1-核心`, `US2`, `UCET012`, `backend`

---

## Issue #2：ET 權限與標籤指派轉接層（2026-08-19 改寫）

**對應規格**：[spec_us1.md](spec_us1.md)、UCET010、畫面：**平台 DP 後台「權限管理」＋「系統參數與清單」**（ET07 為文件層對照碼；ET 不自建系統設定畫面）
**階段**：P1-核心
**前置條件**：
- Issue #0 完成（ET_USER_ROLE / ET_TAG / ET_USER_TAG 表 + 啟動期 registry 註冊就緒）
- 平台 DP 後台已上線（DP Issue #140 dp-roles 權限管理、#68 dp-params 系統參數與清單，**均已完成**）

> **2026-08-19 改寫說明**：本 issue 原要求 ET 自建「系統設定」3 分頁（參數設定 / 權限管理 / 通知範本，比照 DM09）。2026-07-08 集中化後維護介面已移至平台 DP 後台並按模組過濾，且 DP 側已上線。ET 端**改為提供轉接層 provider**（比照 DM `DmAssignProvider` / `CatalogAdapter`）——`app/core/module_assign.py` 之 registry 註解已明文預留「ET＝受訓單位標籤」。**「誰配誰」之業務判定（貼標追溯、自動邀請）仍留 ET**。

**涵蓋 Tasks**：
- T041 ET_USER_TAG Repository
- T042 角色變更 Service（含自我保護檢核）
- T043 標籤對應變更 Service（新增 = 補加入已發布未關閉課程＋彙整信；移除 = 既有 enrollment 不變動）
- T044 權限管理 Endpoint（GET / POST + 稽核 log）
- T045 ET07 權限管理頁面（使用者清單 + 搜尋 / 標籤篩選 + 角色核取 + 受訓單位標籤 + 最後修改）
- T130 ET_TAG Repository + 標籤庫維護 Service / UI

**驗收條件**：
1. 管理者可勾選 / 取消勾選任一帳號之三角色（管理者 / 教師 / 學員），可複選
2. 管理者勾選後立即生效並寫入稽核 log
3. 當前登入者嘗試停用自己之管理者角色 → 系統阻擋並提示
4. 新增使用者×標籤 → 自動補加入該標籤所有「已發布且未關閉」課程，並寄彙整一封通知信（列出所有新加入課程）
5. 移除使用者×標籤 → 既有 ET_ENROLLMENT 不變動；之後新發布之該標籤課程不自動邀請
6. 標籤庫維護：可新增 / 修改 / 停用 / 啟用；TAG_NAME 唯一；「全體」不可停用刪除；停用標籤不可掛新課程、既有課程不受影響
7. 新使用者於帳號建立後自動列於本頁，預設僅「學員」角色勾選、標籤未指派
8. 使用者離職由共用 `DP_USER` 停用該帳號，DM / ET 同步生效
9. 標籤對應變更 / 角色變更均寫入「最後修改」欄（修改者、時間）

**Labels**：`P1-核心`, `US1`, `UCET010`, `admin`, `permission`, `frontend`, `backend`

---

## Issue #3：ET02 課程建立與編輯

**對應規格**：[spec_us3.md](spec_us3.md)、UCET002、畫面：ET02
**階段**：P1-核心
**前置條件**：
- Issue #2 完成（教師角色已可指派）
- DM Service Client 已實作（SRVDM001 / SRVDM002）

**涵蓋 Tasks**：
- T046 ET_COURSE Repository（含樂觀鎖、狀態流轉）
- T047 ET_CHAPTER Repository（拖拉順序 batch 更新、軟刪除）
- T048 ET_ITEM Repository（互斥檢核 MATERIAL_ID / QUIZ_ID）
- T049 ET_MATERIAL Repository（影片上傳整合、DM 文件引用清單）
- T050 ET_QUIZ / ET_QUESTION / ET_OPTION Repository（配分總和、多選題至少 1 正確選項檢核）
- T051 影片上傳 Service（格式 / 大小檢核 per 平台 `DP_PARAM.ET_VIDEO_ALLOWED_FORMATS` / `ET_VIDEO_MAX_SIZE_MB`）
- T052 發布檢核 Service（≥1 章節 + 1 教材、≥1 標籤、起訖時間已填、各測驗配分 = 100、無引用廢止 DM 文件；通過後觸發 T136 標籤自動邀請）
- T053 ET02 課程編輯頁面（基本資料（標籤多選＋起訖時間）+ 章節編排 + 教材視窗 + 測驗視窗 + 問卷區塊 + 草稿 / 發布按鈕）
- T054 教材編輯視窗（影片 / DM 文件下拉 / WYSIWYG 說明文字；廢止文件警告）
- T055 測驗編輯視窗（設定 + 題目編輯 + 配分總和檢核）
- T056 樂觀鎖衝突 UI
- T057 章節 / 題目刪除（軟刪除本體 + 學員紀錄 hard delete）
- T131 ET_COURSE_TAG Repository + 課程標籤掛載 Service（已發布可加不可移）
- T138 課程起訖時間欄位與檢核（發布必填、學員可見性判定）
- T142 問卷建立 UI（→ Issue #15 之教師端建立部分）

**驗收條件**：
1. 教師可建立新課程：填寫名稱、**受訓單位標籤（多選）**、**起訖時間**、描述；草稿階段標籤可自由增刪、起訖可留空
2. 發布檢核：至少 1 章節 + 1 教材 + **至少 1 個標籤** + **起訖時間已填**；未通過阻擋並提示缺漏
3. 已發布課程可**新增**標籤（觸發該標籤人員補邀請＋寄信）、**不可移除**既有標籤
4. 章節編排支援拖拉調整順序；章節下可放任意數量教材與測驗項目
5. 教材項目支援三類媒材組合：影片本地上傳（mp4 / webm，≤ 500 MB）、DM 訓練教材文件引用、說明文字 WYSIWYG
6. 引用之 DM 文件被廢止時，教材視窗顯示警告；發布檢核阻擋
7. 測驗各題配分總和必須等於 100；多選題至少需 1 個正確選項
8. 「儲存草稿」寫入草稿狀態，學員端不顯示
9. 「發布」檢核通過後寫入首次發布時間，並觸發標籤自動邀請＋寄通知信（→ Issue #8）；起始時間前學員不可見
10. 多裝置同時編輯時，樂觀鎖偵測版本衝突並顯示「內容已被其他裝置變更，請重新整理後再儲存」
11. 刪除章節 / 題目 → 本體軟刪除；學員 ET_PROGRESS / ET_QUIZ_ATTEMPT_D 連帶 hard delete
12. 已發布課程再次編輯後儲存即生效，不需重新發布

**Labels**：`P1-核心`, `US3`, `UCET002`, `teacher`, `course`, `frontend`, `backend`, `db`

---

## Issue #4：ET04 我的課程與加入新課程

**對應規格**：[spec_us4.md](spec_us4.md)、UCET007、畫面：ET04
**階段**：P1-核心
**前置條件**：
- Issue #3 完成（課程已可發布）

**涵蓋 Tasks**：
- T058 ET_ENROLLMENT Repository（含 IS_REMOVED 過濾）
- T059 我的課程查詢 Service（依學習狀態分區）
- T060 完課狀態即時計算邏輯
- T061 邀請碼加入 Service（驗證 + 錯誤分流）
- T062 ET04 我的課程頁面（分區總數 + 課程卡片（標籤 badges / 起訖時間）+ 加入新課程按鈕）

**驗收條件**：
1. 學員登入後預設導向 ET04，顯示已加入課程清單
2. 上方依學習狀態分區呈現總數：進行中 / 未開始 / 已完成
3. 課程卡片含標籤 badges、起訖時間、當前進度（不依模組分組；2026-07-02 更新）
4. **起始時間未到之課程不顯示**；**已關閉課程顯示「已關閉」標示，點擊可唯讀回看**（2026-07-02 新增）
5. 學員輸入 8 碼純數字邀請碼 → 系統驗證後加入課程
6. 無效邀請碼 → 顯示錯誤訊息
7. 關閉中課程之邀請碼 → 顯示「此課程目前關閉中」（再開課後恢復有效；2026-07-02 更新）
8. 已加入之課程再次輸入邀請碼 → 直接跳轉至 ET05
9. 學員不可主動退出課程（無「退選」入口）；如需移除由教師於 US9 執行

**Labels**：`P1-核心`, `US4`, `UCET007`, `student`, `enrollment`, `frontend`, `backend`

---

## Issue #5：ET05 章節學習

**對應規格**：[spec_us5.md](spec_us5.md)、UCET008、畫面：ET05
**階段**：P1-核心
**前置條件**：
- Issue #3 完成（課程 / 章節 / 教材已建立）
- Issue #4 完成（學員已加入課程）

**涵蓋 Tasks**：
- T063 ET_PROGRESS Repository
- T064 ET_PROGRESS_INTERVAL Repository（影片觀看區段）
- T065 章節學習頁面（左側章節導覽 + 中間內容區）
- T066 HTML5 影片播放器整合（事件監聽 + INSERT INTERVAL + onbeforeunload normalize）
- T067 影片覆蓋率計算 Service（區段聯集去重）
- T068 ET_PROGRESS_INTERVAL normalize Service
- T069 章節解鎖判定 Service
- T070 DM 文件嵌入（PDF 預覽 / 非 PDF 下載 / 廢止標籤）
- T071 上次觀看位置恢復
- T072 關閉唯讀處理（2026-07-02 改寫）

**驗收條件**：
1. 學員進入 ET05 後自動定位至上次觀看位置（依 ET_PROGRESS.LAST_POSITION_SEC）
2. 影片累計覆蓋率達 80% 時解鎖下一章節（聚合 ET_PROGRESS_INTERVAL 區段聯集後計算）
3. 故意快轉跳過 80% 範圍不解鎖（直接拉到結尾不產生觀看區段、不算看過）
4. 播放器提供倍速選項 0.75 / 1 / 1.25 / 1.5 / 2（上限依 `DP_PARAM.ET_VIDEO_PLAYBACK_MAX_RATE`）；**2 倍速實際看完全片 = 覆蓋率 100%（照算）**（2026-07-02 新增）
5. 文件章節 / 說明文字章節純記錄學習，不強制完成
6. PDF 文件於頁內直接預覽；非 PDF 提供「下載原檔」連結
7. 引用之 DM 文件被廢止時，學員端章節顯示「此文件已廢止」標籤，仍可閱讀廢止前最後版本
8. 學員離開頁面或瀏覽器當機時，ET_PROGRESS_INTERVAL 仍保留已寫入區段；下次進入時 normalize 合併
9. 課程被關閉（到期 / 手動）時內容轉**唯讀回看**：可重看已學內容，不再累積進度 / 作答 / 解鎖（2026-07-02 更新）
10. 完課後（若課程有問卷）章節導覽列顯示「填寫課後問卷」入口（→ Issue #15）
11. 章節含測驗者，需通過測驗（→ Issue #6）方解鎖下一章節

**Labels**：`P1-核心`, `US5`, `UCET008`, `student`, `learning`, `video`, `frontend`, `backend`

---

## Issue #6：ET06 線上測驗作答

**對應規格**：[spec_us6.md](spec_us6.md)、UCET009、畫面：ET06
**階段**：P1-核心
**前置條件**：
- Issue #3 完成（測驗已建立）
- Issue #5 完成（章節學習進度判定）

**涵蓋 Tasks**：
- T073 ET_QUIZ_ATTEMPT_M / D Repository（含快照欄位）
- T074 Attempt 開始 Service（題目 / 選項 / 配分 / 順序快照）
- T075 測驗引導頁
- T076 答題介面（題號進度 + 倒數計時 + 題目導覽 + 自動暫存）
- T077 timeout 自動提交
- T078 onbeforeunload 防誤離
- T079 自動閱卷 Service（單選全有全無 + 多選部分計分）
- T080 答題明細頁（強制顯示正確答案）
- T081 重考流程（未及格立即重考）
- T082 最高分為結業成績計算
- T083 並發處理（教師修改測驗 / 課程關閉 / 移除學員不影響當前 attempt）
- T150 學員端歷次作答明細回看（2026-07-02 新增）

**驗收條件**：
1. 學員按「開始測驗」後系統建立 Attempt 並凍結題目 / 選項 / 配分 / 順序快照
2. 題目順序與選項順序由系統自動洗牌（每次 attempt 獨立洗牌）
3. 倒數計時歸零自動以當前作答狀態提交（status = TIMEOUT）
4. 切換瀏覽器頁面 / 關閉視窗時瀏覽器跳 native confirm
5. 提交後系統即時自動閱卷並顯示總分、是否及格、答題明細
6. 單選題採全有全無；多選題採部分計分公式：`max(0, (答對正確選項數 − 誤選數) ÷ 應選正確數 × 該題配分)`
7. 答題明細強制顯示正確答案（無教師設定關閉選項）
8. 未及格且剩餘重考次數 > 0 → 顯示「重新作答」按鈕；點擊立即建立新 attempt 並重新洗牌（無 cooldown）
9. 學員作答中教師修改測驗 → 當前 attempt 沿用快照不受影響
10. 學員作答中課程被關閉（到期 / 手動）→ 當前 attempt 沿用快照可完成並計分；之後不可開新作答（2026-07-02 更新）
11. 結業成績取該 `DP_USER` × QUIZ 之最高分 attempt
12. 每次 attempt 完整保留於歷史紀錄；學員可回看自己**每一次** attempt 之成績與逐題明細（依快照渲染，不限最近一次）（2026-07-02 更新）

**Labels**：`P1-核心`, `US6`, `UCET009`, `student`, `quiz`, `auto-grading`, `frontend`, `backend`

---

## Issue #7：ET01 課程列表瀏覽

**對應規格**：[spec_us7.md](spec_us7.md)、UCET001、畫面：ET01
**階段**：P2-延伸
**前置條件**：
- Issue #3 完成

**涵蓋 Tasks**：
- T084 課程列表查詢 Service（分頁切換 + 標籤篩選 + 多條件篩選；不分組）
- T085 ET01 課程列表頁面

**驗收條件**：
1. 「我建立的」分頁僅顯示當前使用者建立之課程
2. 「我建立的」顯示本人全部狀態課程（草稿 / 已發布 / 已關閉）；「全部課程」僅顯示所有教師之「已發布」課程（草稿與已關閉不列入；2026-07-02 更新）
3. 搜尋條件：關鍵字（課程名稱）、**受訓單位標籤**；「全部課程」分頁額外提供「建立者」篩選（2026-07-02 更新）
4. 課程以卡片網格呈現（不分組）；卡片含標籤 badges（多個）、起訖時間、狀態 pill（2026-07-02 更新）
5. 他人建立之課程卡片右上顯示「檢視」標籤；進入後為唯讀模式
6. 已關閉課程顯示「已關閉」狀態標示；自己建立者進入後可執行「再開課」（→ Issue #11）（2026-07-02 更新）
7. 點擊搜尋區右側「新增課程」進入 ET02 新增模式

**Labels**：`P2-延伸`, `US7`, `UCET001`, `teacher`, `course`, `frontend`, `backend`

---

## Issue #8：ET02 邀請學員（標籤自動邀請＋寄信）（2026-07-02 更新）

**對應規格**：[spec_us8.md](spec_us8.md)、UCET004、畫面：ET02（邀請學員視窗）
**階段**：P2-延伸
**前置條件**：
- Issue #3 完成（課程已發布、已掛標籤）
- Issue #2 完成（標籤庫與使用者×標籤對應）
- Issue #17 之範本 seed 可用（Email Server 已配置）

**涵蓋 Tasks**：
- T086 ET_INVITATION Repository（含狀態流轉）
- T087 Email 邀請 Service（token 產生 + 寄信 + status_code 紀錄）
- T088 邀請信寄送（平台範本 `DP_NOTIFY_TEMPLATE` `MODULE=ET` / `TEMPLATE_CODE=COURSE_INVITE`；統一範本，經平台發信服務）
- T089 邀請連結驗證 Endpoint（自動加入 + 跳轉）
- T090 邀請學員 UI（Email 視窗（預覽唯讀）+ 邀請碼視窗）
- T136 標籤自動邀請 Service（發布時聯集去重批次加入＋每人寄信）
- T137 貼標追溯補加入 Service（彙整一封）
- ~~T091~~（廢除，併入 T136）

**驗收條件**：
1. 課程僅 PUBLISHED 狀態顯示「邀請學員」按鈕（已關閉隱藏、再開課恢復）
2. **發布時**：系統取課程標籤對應人員（限學員角色；「全體」= 全部學員角色者）聯集去重，批次加入（來源 = TAG_DEFAULT），**每人寄一封**通知信（統一範本；非同步、失敗不回滾加入）
3. **貼標追溯**：管理者新增人×標籤 → 補加入該標籤所有已發布未關閉課程 → 寄**彙整一封**（列出所有新加入課程）
4. **已發布課程新增標籤** → 對該標籤人員補邀請＋寄信（既有學員不重複加入）
5. Email 邀請：教師輸入多筆 Email → 統一範本信件**預覽（不可編輯主旨 / 內文）** → 寄出；寄送失敗寫入 status_code，待加入清單可再寄
6. 邀請碼：8 碼純數字，發布時自動產生寫入 ET_COURSE.INVITATION_CODE，不可重新產生 / 手動指定；**課程關閉期間失效、再開課恢復**
7. 邀請碼視窗提供複製連結與 QR Code
8. 學員點擊邀請連結後驗證 token 並自動加入課程（來源 = EMAIL_INVITE）
9. 已加入學員再次點擊邀請連結 → 直接跳轉至 ET05

**Labels**：`P2-延伸`, `US8`, `UCET004`, `teacher`, `invitation`, `email`, `frontend`, `backend`

---

## Issue #9：ET03 學員學習狀況追蹤

**對應規格**：[spec_us9.md](spec_us9.md)、UCET005、畫面：ET03（「已加入」頁籤分三區塊：已加入學員 / 作答明細 / 問卷結果；含 CSV 匯出）
**階段**：P2-延伸
**前置條件**：
- Issue #3, #4, #5, #6 完成

**涵蓋 Tasks**：
- T092 已加入學員查詢 Service（含完課狀態 / 進度 / 平均成績計算）
- T093 重置重考次數 Service（限上限已用且未及格時可重置；以 `ET_QUIZ_RETRY_RESET` 記基準，**不刪 attempt**）
- T094 移除學員 Service（IS_REMOVED + REMOVED_AT；IN_PROGRESS attempt 跳警告但允許完成）
- T095 匯出 CSV Service
- T096 ET03 學員頁面（課程下拉 + 學員清單 + 操作按鈕 + 匯出 CSV）
- T149 教師端每次作答明細 UI（2026-07-02 新增）
- T144 問卷結果區塊（統計 + 具名明細 + CSV；「已加入」頁籤之區塊 3）（2026-07-02 新增）

**驗收條件**：
1. 教師於頂部下拉切換課程後，系統列出該課程已加入學員清單（過濾 IS_REMOVED）
2. 學員清單欄位：學員、加入日期、完課狀態（已完成 / 進行中 / 未開始）、學習進度、平均成績、最後活動
3. 平均成績以已作答測驗之最高分平均（排除未作答測驗）
4. 教師點擊學員可展開其各測驗之**歷次 attempt 清單**（作答時間 / 總分 / 是否及格），點入單次檢視**逐題明細**（題目 / 學員作答 / 正確答案 / 對錯 / 得分，依快照渲染）（2026-07-02 新增）
5. 「問卷結果」區塊（「已加入」頁籤區塊 3）：各題選項分布統計（人數 / 百分比、已填未填人數）＋逐學員（具名）明細＋匯出 CSV；課程無問卷時本區塊隱藏（2026-07-02 新增）
6. 「重置重考次數」僅當該學員之測驗已用次數 = 上限且尚未及格時可用；重置後該學員可再作答，且**歷次 attempt 明細仍完整可回看**（重置不刪除任何作答紀錄）
7. 「移除學員」寫入 IS_REMOVED；若該學員有 IN_PROGRESS attempt 跳警告但允許完成
8. 移除後該學員 ET_ENROLLMENT 不再列入完課率統計，學習歷史保留
9. 「匯出 CSV」依當前篩選條件產生 CSV，含完整欄位
10. 課程已關閉時，仍可閱覽學員清單、作答明細與問卷結果，但不可再執行重置 / 移除（2026-07-02 更新）

**Labels**：`P2-延伸`, `US9`, `UCET005`, `teacher`, `tracking`, `csv-export`, `frontend`, `backend`

---

## Issue #10：個人資料維護導向連結（2026-08-19 大幅裁減）

**對應規格**：[spec_us10.md](spec_us10.md)、UCET011、畫面：**ET08（由平台 DP 提供，平台畫面碼 DP04）**
**階段**：P2-延伸
**前置條件**：
- 平台 DP 個人資料維護已上線（DP Issue #83 dp-profile，**已完成**）

> **2026-08-19 裁減說明**：本 issue 原涵蓋 T097 ~ T101 共 5 項，要求 ET 自建個資頁與 Email 雙信箱共存變更流程。該能力已由平台 DP 完整提供並上線，ET **無後端開發項**。

**涵蓋 Tasks**：
- T100 ET 側欄 / 右上選單之「個人資料」導向連結（指向平台 DP 個資頁）
- ~~T097 / T098 / T099 / T101~~ — 廢除（Email 變更、密碼變更、驗證信範本皆由平台 DP 提供）

**驗收條件**：
1. ET 側欄 / 右上個資選單提供「個人資料」入口，點擊後導向平台 DP 個資頁
2. 使用者於平台 DP 變更姓名 / Email / 密碼後，ET 端顯示之姓名同步更新（ET 唯讀引用 `DP_USER`）
3. **不驗收**雙信箱共存流程、驗證信 TTL、舊密碼檢核 —— 屬平台 DP 職責，已於 DP Issue #83 驗收

**Labels**：`P2-延伸`, `US10`, `UCET011`, `frontend`

---

## Issue #11：ET02 課程關閉與再開課（2026-07-02 全面改寫）

**對應規格**：[spec_us11.md](spec_us11.md)、UCET003、畫面：ET02（關閉課程 / 再開課按鈕）
**階段**：P3-輔助
**前置條件**：
- Issue #3 完成（含起訖時間欄位 T138）
- Issue #6 完成

**涵蓋 Tasks**：
- T102 手動關閉 Service（confirm 後立即 CLOSED；作答中 attempt 沿用快照可完成計分）
- T103 CLOSED 阻擋新作答（既有 IN_PROGRESS attempt 可提交）
- T104 關閉狀態之學員端 UI（ET04「已關閉」標示；ET05 唯讀回看）
- T105 關閉狀態之教師端 UI（編輯禁用＋「再開課」按鈕）
- T106 再開課 Service + UI（重設起訖時間、URGENT_REMIND_SENT 歸零）

**驗收條件**：
1. 教師於 ET02 編輯頁右上點擊「關閉課程」（僅已發布狀態顯示）＋ confirm modal
2. 確認後 STATUS **立即** = CLOSED、寫入 CLOSED_AT（無 PENDING_CLOSE 過渡）
3. 到達訖止時間（OPEN_END_AT）系統自動轉 CLOSED（SCHET002 排程＋應用層存取時即時判定雙保險，→ Issue #16）
4. 關閉當下作答中之 attempt 沿用快照**允許完成並計分**；提交後不可開新 attempt
5. 學員端：課程仍可見並**唯讀回看**已學內容；不能累積進度 / 作答 / 解鎖 / 填問卷；ET04 顯示「已關閉」
6. 邀請碼於關閉期間失效；每週統計與提醒（Issue #16）停止
7. 教師端（owner）：ET02 **課程內容仍可編輯**（非唯讀，供準備下次開課）、顯示「再開課」按鈕；關閉期間不可邀請學員、不可重置重考次數（2026-07-02 變更：教師端由唯讀改為可編輯）
8. 「再開課」須重設一組新起訖時間 → STATUS 回 PUBLISHED、URGENT_REMIND_SENT 歸 false、邀請碼與排程恢復；學員進度接續保留
9. 關閉 / 再開課可重複多次

**Labels**：`P3-輔助`, `US11`, `UCET003`, `teacher`, `course-lifecycle`, `frontend`, `backend`

---

## Issue #12：ET03 待加入邀請追蹤

**對應規格**：[spec_us12.md](spec_us12.md)、UCET006、畫面：ET03（待加入分頁）
**階段**：P3-輔助
**前置條件**：
- Issue #8 完成

**涵蓋 Tasks**：
- T107 待加入邀請查詢 Service
- T108 再次寄送 Service
- T109 撤回邀請 Service
- T110 邀請連結失效 UI
- T111 ET03 待加入分頁

**驗收條件**：
1. 教師於 ET03 頁面切至「待加入」分頁，系統列出 PENDING 狀態之邀請
2. 清單欄位：Email、寄送時間、邀請狀態
3. 「再次寄送」重新呼叫 Email Server 寄出並更新 LAST_SENT_AT
4. 「撤回邀請」狀態更新為 REVOKED + REVOKED_AT；token 失效
5. 學員點擊已撤回邀請 → 顯示「此邀請已撤回」訊息頁
6. 學員加入後自動從「待加入」移至「已加入」分頁

**Labels**：`P3-輔助`, `US12`, `UCET006`, `teacher`, `invitation`, `frontend`, `backend`

---

## Issue #13：跨 US 補強（章節更新通知 + 擁有者轉讓）

**對應規格**：plan.md §複雜度追蹤（章節更新通知 = US3 補強；擁有者轉讓 = US1 補強）
**階段**：補強（依各父 Issue 完成後追加）
**前置條件**：
- Issue #3 完成（章節更新通知依賴課程發布後新增章節之觸發）
- Issue #2 完成（擁有者轉讓由管理者執行）

**涵蓋 Tasks**：
- T112 章節更新通知 Service（教師於已發布課程新增章節時自動寄信給所有 enrollment；完課狀態回退為 IN_PROGRESS；已填問卷不失效）
- T113 章節更新通知寄送（平台範本 `DP_NOTIFY_TEMPLATE` `MODULE=ET` / `TEMPLATE_CODE=COURSE_UPDATE`，經平台發信服務）
- T114 擁有者轉讓 Service（寫 ET_OWNER_TRANSFER 稽核 + 更新 ET_COURSE.OWNER_ID）
- T115 擁有者轉讓 UI（管理者選擇課程 + 接收教師 + 原因 + 確認轉讓）

**驗收條件**：
1. 教師於已發布課程新增章節後，系統自動寄送 ET_NEW_CHAPTER 通知信給所有 enrollment（過濾 IS_REMOVED）
2. 章節更新後，該課程已完課之學員之 ET_ENROLLMENT.COMPLETION_STATUS 回退為 IN_PROGRESS
3. 管理者可於平台 DP 後台權限管理或 ET01 課程列表執行擁有者轉讓
4. 擁有者轉讓必填轉讓原因；系統寫入 ET_OWNER_TRANSFER 稽核紀錄
5. 一般教師不可主動轉讓（轉讓按鈕僅管理者可見）
6. 轉讓後新擁有者於 ET01「我建立的」分頁可見該課程；原擁有者僅可閱覽

**Labels**：`補強`, `US3-extension`, `US1-extension`, `notification`, `audit`, `backend`, `frontend`

---

## Issue #14：整合測試 + 安全 + 部署

**對應規格**：plan.md §技術背景、§複雜度追蹤；[research.md](research.md)
**階段**：上線前收尾
**前置條件**：
- Issue #1 ~ #13 全部完成

**涵蓋 Tasks**：
- T116 整合測試：完整教師作業流程（建立 → 編排 → 發布 → 邀請 → 追蹤）
- T117 整合測試：完整學員作業流程（註冊 → 登入 → 加入 → 學習 → 通過 → 完課）
- T118 整合測試：並發場景（多裝置同時編輯 / 學員作答中停課 / 學員作答中移除）
- T119 整合測試：影片 80% 累計覆蓋率與 normalize 機制（含瀏覽器當機補做）
- T120 整合測試：DM 文件廢止後之 UI 行為
- T121 整合測試：帳號（Email）變更雙信箱共存模式
- T122 效能驗證：大量學員加入課程之列表載入；影片觀看區段大量寫入與 normalize 效能
- T123 安全性檢查（密碼雜湊強度、SMTP TLS、token 隨機性、防帳號列舉）
- T124 部署文件撰寫（管理者初始化 / ET_TAG seed；ET 系統參數與通知範本 seed 由平台 DP 建於 `DP_PARAM`（前綴 `ET_`）/ `DP_NOTIFY_TEMPLATE`（`MODULE=ET`）/ 排程於平台 `DP_SCHEDULE` 註冊 / 發信走平台服務 / DM 整合說明）
- T152 整合測試：標籤自動邀請與貼標追溯（2026-07-02 新增）
- T153 整合測試：課程時窗與再開課（2026-07-02 新增）
- T154 整合測試：課後問卷全流程（2026-07-02 新增）
- T155 整合測試：排程週報與提醒（2026-07-02 新增）

**驗收條件**：
1. 教師端完整作業流程通過 E2E 測試（含標籤掛載、起訖設定、問卷建立、發布自動邀請）
2. 學員端完整作業流程通過 E2E 測試（含收到邀請信、完課後填問卷）
3. 並發場景測試通過（樂觀鎖衝突、Attempt Snapshot、作答中課程關閉可完成計分）
4. 影片覆蓋率計算驗證（含瀏覽器當機後 normalize 補做）
5. DM 文件廢止後教師端阻擋發布、學員端顯示「此文件已廢止」標籤
6. 帳號變更雙信箱共存模式驗證通過（驗證後切換、未驗證舊 Email 仍可登入）
7. 大量學員（≥ 500 人）加入課程之列表載入時間 < 2 秒
8. 影片觀看區段批次寫入與 normalize 效能達標
9. 密碼雜湊強度 ≥ bcrypt cost 12 或 argon2 等效；SMTP 採 TLS；所有 token 使用 cryptographically secure random（≥ 32 bytes）
10. 部署文件完整覆蓋第一個管理者寫入、ET_TAG seed；ET 系統參數（平台 `DP_PARAM` 前綴 `ET_`）與通知範本（平台 `DP_NOTIFY_TEMPLATE` `MODULE=ET`）seed 由平台 DP 初始化、排程於平台 `DP_SCHEDULE` 註冊、發信走平台服務、DM 整合步驟
11. 標籤自動邀請 / 貼標追溯、課程時窗與再開課、問卷全流程、排程週報與提醒之整合測試（T152 ~ T155）全數通過

**Labels**：`收尾`, `e2e-test`, `performance`, `security`, `deployment`, `documentation`

---

## Issue #15：課後問卷（建立 / 填寫）（2026-07-02 新增）

**對應規格**：[spec_us13.md](spec_us13.md)、UCET013、[spec_us3.md](spec_us3.md) §課後問卷建立、畫面：ET02（問卷區塊）/ ET05（填寫入口與問卷頁）
**階段**：P2-延伸
**前置條件**：
- Issue #3 完成（課程編輯頁可掛問卷區塊）
- Issue #5 完成（完課判定就緒）
- Issue #0 之 T126 / T127（問卷五表 Migration）完成

**涵蓋 Tasks**：
- T141 ET_SURVEY 五表 Repository（填答唯一約束、題目凍結檢核）
- T142 問卷建立 UI（ET02 區塊；單選題與選項編輯、凍結提示、停用）
- T143 問卷填寫 UI（ET05 入口＋問卷頁；具名送出、唯讀回看）

**驗收條件**：
1. 一門課程至多 1 份問卷（選配）；每題單選、選項由教師自訂（每題至少 2 個選項）
2. 無人填答前教師可自由編修題目與選項；**已有任何學員填答後題目與選項凍結**（僅可停用問卷）
3. 學員**完課後** ET05 顯示「填寫課後問卷」入口；未完課 / 無問卷 / 問卷停用不顯示
4. 全部題目作答後方可送出；送出寫入具名紀錄；(SURVEY_ID, USER_ID) 唯一防重複
5. 送出後不可修改；已填者入口顯示「已填寫」、點擊唯讀回看
6. 課程關閉後不可填寫（已填可回看）；再開課後未填之已完課學員恢復可填
7. 填寫問卷不是完課條件、不計入學習進度；完課狀態回退不影響已填問卷
8. 教師端統計與具名明細於 Issue #9「問卷結果」區塊驗收

**Labels**：`P2-延伸`, `US13`, `UCET013`, `survey`, `student`, `teacher`, `frontend`, `backend`, `db`

---

## Issue #16：排程統計與提醒（SCHET001 / SCHET002）（2026-07-02 新增）

**對應規格**：[spec_us14.md](spec_us14.md)、UCET014；spec.md §排程統計與提醒規則、§排程作業總覽
**階段**：P2-延伸
**前置條件**：
- Issue #4 / #5 完成（enrollment 與進度資料就緒）
- Issue #17 之範本 seed 可用；平台 `DP_SCHEDULE` 排程引擎就緒、SCHET001 / SCHET002 可於其註冊
- Issue #0 之 T128（ET_WEEKLY_STAT Migration）完成

**涵蓋 Tasks**：
- T145 SCHET001 統計快照 Service（開放中課程 → ET_WEEKLY_STAT，append-only；job handler 於平台 `DP_SCHEDULE` 註冊）
- T146 週報產生與寄送（教師自己課程 / 管理者全域；內文摘要＋逐學員明細 CSV **下載連結**＋與上週比較；經平台發信服務）
- T164 週報逐學員明細 CSV **下載端點**（需登入；教師限自己課程 / 管理者全域；內容即時產生）（2026-08-19 新增，取代原郵件附件設計）
- T147 每週未看提醒（進度 0% 者一人一信彙整）
- T139 到期自動關閉（SCHET002 內；→ Issue #11 驗收 3）
- T148 截止前加急提醒（訖止前 N 天、所有未完課者、每課一次）

**驗收條件**：
1. SCHET001 於每週一 10:00（`DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` 可調）由平台排程引擎執行（於 `DP_SCHEDULE` 註冊、`DP_SCHEDULE_LOG` 記錄）；僅統計開放中課程
2. 每門課程寫入一筆 ET_WEEKLY_STAT（課程×統計日期唯一；含平均進度%、三態人數、完課率、已加入數）
3. 教師收到自己開放中課程之週報、管理者收到全域週報；內文含平均進度%（與上週比較）、人數分布、完課率、距訖止天數、未開始名單，以及逐學員明細 **CSV 下載連結**（`{{REPORT_CSV_URL}}`；**非郵件附件**——平台唯一發信服務不支援附件）
4. 點擊週報之 CSV 下載連結需登入方可取得；教師僅能下載自己為擁有者之課程明細、管理者可下載全域；越權存取被擋
5. 首次統計（無上週快照）時「與上週比較」顯示「—」
6. 週提醒僅寄**進度 0%** 學員；一人一信彙整列出所有未開始課程；>0% / 已完課 / 已移除不寄
7. SCHET002 每日執行：到期課程自動轉 CLOSED；訖止前 3 天（`DP_PARAM.ET_URGENT_REMIND_DAYS` 可調）對所有未完課學員寄加急提醒（經平台發信服務）
8. 加急提醒每門課程只寄一次（URGENT_REMIND_SENT 防重複）；再開課重設起訖後歸零重計
9. 已關閉 / 未到起始課程不納入統計與提醒；寄送失敗寫入 log、不影響快照

**Labels**：`P2-延伸`, `US14`, `UCET014`, `schedule`, `report`, `notification`, `backend`

---

## Issue #17：ET 通知範本 seed 與啟停檢查（2026-08-19 改寫）

**對應規格**：[spec_us15.md](spec_us15.md)、UCET015、畫面：**平台 DP 後台「通知範本」**（ET09 為文件層對照碼；ET 不自建維護畫面）
**階段**：P3-輔助
**前置條件**：
- Issue #0 完成（平台 `DP_NOTIFY_TEMPLATE` 表由平台 DP 建立）
- 平台 DP 通知範本維護已上線（DP Issue #92 dp-templates，**已完成**）

> **2026-08-19 改寫說明**：本 issue 原要求 ET 自建 ET09 通知範本維護頁（範本清單、主旨 / 內文編輯、變數插入、樂觀鎖、排程參數調整）。該 UI 已由平台 DP 後台「通知範本」統一提供（按模組過濾，ET 管理者只見 `MODULE=ET` 的列），排程參數則於 DP 後台「系統參數與清單」調整。ET 端只剩 **seed 與寄送前檢查**。

**涵蓋 Tasks**：
- T151 ET 7 類通知範本之 seed（`MODULE=ET`）與各寄信點寄送前之 `IS_ACTIVE` 檢查

**驗收條件**：
1. 部署後平台 `DP_NOTIFY_TEMPLATE` 存在 `MODULE=ET` 之 7 類範本：COURSE_INVITE / COURSE_INVITE_DIGEST / COURSE_UPDATE / WEEKLY_REMIND / URGENT_REMIND / WEEKLY_REPORT / APPROVAL_PASSED；範本代碼固定、不可由 ET 新增或刪除
2. ET 管理者於**平台 DP 後台「通知範本」**可見且僅可編輯 `MODULE=ET` 之列；密碼重設 / 帳號變更驗證（`MODULE=DP`）不在其可編輯範圍
3. 各寄信點（T136 邀請 / T112 內容更新 / T146 週報 / T147 週提醒 / T148 加急 / T159 核可通過）於寄送前檢查對應範本之 `IS_ACTIVE`；停用時**不寄該類信件**，但觸發事件（自動加入學員、統計快照等）照常運作
4. 排程參數（`DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` / `ET_URGENT_REMIND_DAYS`）於 DP 後台「系統參數與清單」調整後，ET 排程於下次執行即套用
5. **不驗收**範本編輯 UI、變數插入、未定義變數警告、樂觀鎖 —— 屬平台 DP 職責，已於 DP Issue #92 驗收

**Labels**：`P3-輔助`, `US15`, `UCET015`, `notification`, `backend`

---

## Issue #18：ET03 學員線下考核核可（2026-07-17 新增）

**對應規格**：[spec_us16.md](spec_us16.md)、UCET016、畫面：ET03「已加入」頁籤（核可狀態欄與核可 / 撤銷操作）
**階段**：P2-延伸
**前置條件**：
- Issue #3（課程建立，含 `REQUIRE_APPROVAL` 開關 T161）、Issue #6（測驗，完課判定基礎）完成
- Issue #17 / #0（平台 `DP_NOTIFY_TEMPLATE` 之 `APPROVAL_PASSED` 範本 seed 已建）

**涵蓋 Tasks**：
- T156 [P] Migration：ET_APPROVAL（(COURSE_ID, USER_ID) 唯一）＋ ET_COURSE.REQUIRE_APPROVAL 欄位
- T157 [US16] ET_APPROVAL Repository + 核可 Service（前提檢核完課、通過 / 不通過寫入、批次、樂觀鎖）
- T158 [US16] 撤銷 Service（IS_REVOKED、撤銷原因必填、回「待核可」、可重核）
- T159 [US16] 核可通過寄信（平台範本 `APPROVAL_PASSED`；不通過 / 撤銷不寄）
- T160 [US16] ET03 核可 UI（核可狀態欄、通過 / 不通過、批次核可、撤銷 modal；未完課不顯示核可鈕；課程關閉唯讀）
- T161 [US3] ET02 「是否需線下核可」（REQUIRE_APPROVAL）開關
- T163 整合測試：線下核可（完課前提、通過寄信、不通過留紀錄、撤銷需原因、完課回退不失效、關閉唯讀、獨立於完課率）

**驗收條件**：
1. 僅 `REQUIRE_APPROVAL = true` 之課程於 ET03 顯示核可欄；未完課學員不顯示核可鈕（狀態「未達核可資格」）
2. 對已完課學員可核可通過 / 不通過（可批次）；通過寄 `APPROVAL_PASSED` 通知、不通過留紀錄不寄信
3. 撤銷須填原因，撤銷後回「待核可」可重核；核可 / 撤銷記錄執行者與時間
4. 核可為獨立維度：不影響完課率 / 平均成績 / 問卷 / 週報；完課回退不使核可失效
5. 課程 CLOSED 期間核可狀態可閱覽、不可新增核可 / 撤銷；再開課恢復
6. 非該課程 owner 之教師不顯示核可操作；(COURSE_ID, USER_ID) 唯一、樂觀鎖防並發

**Labels**：`P2-延伸`, `US16`, `UCET016`, `teacher`, `admin`, `approval`, `notification`, `frontend`, `backend`

---

## Issue #19：ET10 核可查詢（2026-07-17 新增）

**對應規格**：[spec_us17.md](spec_us17.md)、UCET017、畫面：ET10 核可查詢（教師 / 管理者 + 學員自查）
**階段**：P2-延伸
**前置條件**：Issue #18 完成（ET_APPROVAL 已有資料）

**涵蓋 Tasks**：
- T162 [US17] ET10 核可查詢：教師 / 管理者依姓名查全部學員（含通過 / 不通過 / 撤銷）；學員自查僅「已通過」；後端依身分控管查詢範圍

**驗收條件**：
1. 教師 / 管理者依學員姓名查得核可課程（課程、結果、核可時間、核可人；撤銷者標示與原因）
2. 學員僅見自己「已通過（有效未撤銷）」課程，查不到不通過 / 撤銷、亦查不到他人（後端控管，非僅前端隱藏）
3. 查無資料顯示空狀態；不提供核可證明 / 結業證書輸出

**Labels**：`P2-延伸`, `US17`, `UCET017`, `teacher`, `admin`, `student`, `approval`, `frontend`, `backend`

---

## 依賴關係圖

```
#0 基礎建設
    ↓
#1 登入頁（US2）
    ↓
#2 ET07 權限管理（US1）
    ↓
#3 ET02 課程建立與編輯（US3）
    ↓
    ├─→ #4 ET04 我的課程（US4）
    │      ↓
    │      ├─→ #5 ET05 章節學習（US5）
    │      │      ↓
    │      │      └─→ #6 ET06 線上測驗（US6）
    │      │             ↓
    │      │             └─→ #9 ET03 學員追蹤（US9，亦依賴 #15）
    │      │             └─→ #11 ET02 課程關閉與再開課（US11）
    │      │             └─→ #15 課後問卷（US13，依賴 #3, #5）
    │      │
    │      └─→ #5 / #7 / #8 / #10 可平行
    │
    ├─→ #7 ET01 課程列表（US7）
    ├─→ #8 ET02 邀請學員（US8，標籤自動邀請；依賴 #2 標籤、#17 範本）
    │      ↓
    │      └─→ #12 ET03 待加入追蹤（US12）
    └─→ #10 ET08 個人資料（US10，亦依賴 #1）

#17 ET09 通知範本維護（依賴 #0；範本 seed 先行可用）
#16 排程統計與提醒（依賴 #4, #5, #17）
#18 ET03 線下核可（依賴 #3, #6, #17）
    ↓
#19 ET10 核可查詢（依賴 #18）
#13 補強（依賴 #3, #2）
    ↓
#14 整合測試 + 安全 + 部署（依賴全部）
```

**可平行開發機會**：
- Issue #0 內 T002 ~ T032 可平行（不同 Table 之 Migration 與獨立工具）
- Issue #5 (US5) / #7 (US7) / #8 (US8) / #10 (US10) 完成 #3 / #4 後可平行
- Issue #9 (US9) / #10 (US10) 完成 #6 後可平行
- Issue #11 (US11) / #12 (US12) 完成 #8 後可平行

---

## Labels 使用約定

| Label 類別 | 範例 |
|----------|------|
| 階段 | `P1-核心`, `P2-延伸`, `P3-輔助`, `補強`, `收尾`, `priority:P0`（基礎建設）|
| User Story | `US1` ~ `US17` |
| Use Case | `UCET001` ~ `UCET017` |
| 角色 | `admin`, `teacher`, `student`, `auth`, `profile` |
| 技術領域 | `frontend`, `backend`, `db`, `email`, `video`, `quiz`, `auto-grading`, `csv-export`, `notification`, `audit`, `survey`, `schedule`, `report`, `course-lifecycle`, `approval` |
| 跨類 | `foundational`, `setup`, `infra`, `e2e-test`, `performance`, `security`, `deployment`, `documentation` |

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總 Issue 數 | 20（#0 ~ #19；#15 ~ #17 為 2026-07-02 新增、#18 ~ #19 為 2026-07-17 線下核可新增）|
| P1 核心 | 6（#1 ~ #6）|
| P2 延伸 | 8（#7 ~ #10, #15, #16, #18, #19）|
| P3 輔助 | 3（#11, #12, #17）|
| 補強 | 1（#13）|
| 收尾 | 1（#14）|
| 基礎建設 | 1（#0）|
| 涵蓋 Task 總數 | 158（T001 ~ T163；T091 廢除、T132 ~ T135 / T140 保留未用）|
