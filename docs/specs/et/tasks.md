# 開發任務清單：教育訓練文件管理模組（Education & Training）

**模組代碼**: ET | **日期**: 2026-06-09（2026-07-02 依客戶 6 項需求變更更新）
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md) | **資料模型**: [data-model.md](data-model.md) | **研究**: [research.md](research.md)

> **2026-07-02 變更**：既有任務編號不重排；受變更影響之任務**就地改寫**（如 T004/T005 改建標籤表、T102~T106 改為關閉/再開課）；全新工作以 **T125 起附加於 Phase 17**。變更內容：受訓單位標籤（取代業務模組）、發布標籤自動邀請＋寄信、課程起訖時間與可逆關閉、課後問卷、排程統計與提醒、每次作答明細、通知範本、影片倍速。

---

## Phase 1: 專案設定

- [ ] T001 建立 ET 模組專案結構，依 plan.md 文件結構建立 et/ 目錄與子目錄（controllers / services / repositories / models / migrations / templates）
- [ ] T002 [P] **(移除／改由平台 DP 負責)** 帳號主檔 migration：ET **不建立**帳號表 migration；`DP_USER`（帳號 Email / 密碼雜湊 / 姓名 / 狀態 / Email 變更 PENDING 等欄位）由**平台模組 DP** 建立與維護，ET 各表一律以 USER_ID（VARCHAR(20)）FK 引用；原「協調 DM 模組共識定義」改由平台 DP 統一定義
- [ ] T003 [P] 建立資料庫 Migration：**ET_USER_ROLE** 使用者角色，含 (USER_ID, ROLE) 邏輯唯一索引
- [ ] T004 [P] 建立資料庫 Migration：**ET_TAG** 受訓單位標籤（TAG_NAME 唯一、IS_ACTIVE / IS_ALL / IS_BUILTIN）（2026-07-02 改寫，原 ET_USER_MODULE 廢除）
- [ ] T005 [P] 建立資料庫 Migration：**ET_USER_TAG** 使用者標籤對應，含 (USER_ID, TAG_ID) 邏輯唯一索引（2026-07-02 改寫，原 ET_MODULE 廢除）
- [ ] T006 [P] 建立資料庫 Migration：**ET_COURSE** 課程主檔，含 VERSION 樂觀鎖欄位、INVITATION_CODE 唯一索引、OPEN_START_AT / OPEN_END_AT / URGENT_REMIND_SENT（2026-07-02 增欄）
- [ ] T007 [P] 建立資料庫 Migration：**ET_CHAPTER** 章節，含 (COURSE_ID, SORT_ORDER) 邏輯唯一索引
- [ ] T008 [P] 建立資料庫 Migration：**ET_ITEM** 章節項目，含 (CHAPTER_ID, SORT_ORDER) 邏輯唯一索引；ITEM_TYPE / MATERIAL_ID / QUIZ_ID 互斥 CHECK constraint
- [ ] T009 [P] 建立資料庫 Migration：**ET_MATERIAL** 教材內容
- [ ] T010 [P] 建立資料庫 Migration：**ET_QUIZ** 測驗主檔
- [ ] T011 [P] 建立資料庫 Migration：**ET_QUESTION** 題目
- [ ] T012 [P] 建立資料庫 Migration：**ET_OPTION** 選項
- [ ] T013 [P] 建立資料庫 Migration：**ET_ENROLLMENT** 選課關聯，含 (USER_ID, COURSE_ID) 邏輯唯一索引
- [ ] T014 [P] 建立資料庫 Migration：**ET_PROGRESS** 學習進度，含 (USER_ID, ITEM_ID) 邏輯唯一索引
- [ ] T015 [P] 建立資料庫 Migration：**ET_PROGRESS_INTERVAL** 影片觀看區段，含 (USER_ID, ITEM_ID) 索引
- [ ] T016 [P] 建立資料庫 Migration：**ET_QUIZ_ATTEMPT_M** 測驗作答主檔（含 QUESTION_ORDER / OPTION_ORDER / 規則快照欄位）
- [ ] T017 [P] 建立資料庫 Migration：**ET_QUIZ_ATTEMPT_D** 作答明細（含題目 / 選項 / 配分快照欄位）
- [ ] T018 [P] 建立資料庫 Migration：**ET_INVITATION** 邀請紀錄，含 TOKEN 唯一索引
- [ ] T019 [P] 建立資料庫 Migration：**ET_OWNER_TRANSFER** 擁有者轉讓稽核紀錄
- [ ] T020 [P] ~~建立 ET_PARAM 系統參數 Migration~~ **廢除**：系統參數集中於平台 `DP_PARAM`（前綴 `ET_`），由平台 DP 建表；ET 不建 param migration（2026-07-08 集中化）
- [ ] T021 建立 Lookup 代碼初始資料（ET_USER_ROLE_TYPE、ET_COURSE_STATUS（DRAFT / PUBLISHED / CLOSED，PENDING_CLOSE 已移除）、ET_ENROLLMENT_SOURCE（含 TAG_DEFAULT）、ET_INVITATION_STATUS、ET_ATTEMPT_STATUS、ET_QUESTION_TYPE、ET_ITEM_TYPE、ET_COMPLETION_STATUS 共 8 類），參照 data-model.md Lookup 表
- [ ] T022 建立 ET_TAG 初始資料（5 筆：全體（IS_ALL）/ 護理師 / 行政人員 / 軍人 / 醫檢師，皆 IS_BUILTIN），參照 data-model.md（2026-07-02 改寫，原 ET_MODULE 7 筆廢除）
- [ ] T023 建立 ET 系統參數 seed（於平台 `DP_PARAM`，前綴 `ET_`：ET_VIDEO_ALLOWED_FORMATS / ET_VIDEO_MAX_SIZE_MB / ET_VIDEO_PLAYBACK_MAX_RATE / ET_INVITATION_CODE_LENGTH / ET_WEEKLY_STAT_DAY_TIME / ET_URGENT_REMIND_DAYS），參照 data-model.md（2026-07-08 集中化：ET 不自建參數表；密碼重設 TTL 改平台級 `DP_` 參數；EMAIL_NOTIFY_* 已移至 `DP_NOTIFY_TEMPLATE`）
- [ ] T024 建立**系統初始化第一個管理者** Migration / Seed Script：寫入 `DP_USER`（帳號主檔由平台模組 DP 定義；IT 部署時提供 Email / 初始密碼 hash）+ ET_USER_ROLE（ROLE=ADMIN）

---

## Phase 2: 基礎共用元件

- [ ] T025 [P] 實作 SSO 認證中介層：登入 session 管理、密碼雜湊（建議 bcrypt 或 argon2）、與 DM 共用 `DP_USER` 主檔之 read / write 邏輯
- [ ] T026 [P] 實作角色權限檢查中介層：依登入 session 之 ET_USER_ROLE 判斷 endpoint 存取權（2026-07-02：ET_USER_MODULE 改 ET_USER_TAG，標籤僅供邀請不涉權限）
- [ ] T027 [P] 實作 ET 參數載入工具：透過平台 `DP_PARAM` 唯讀查詢服務讀取前綴 `ET_` 參數，應用啟動時 cache，提供 get(key) 介面；變更後可手動 reload（ET 不自建參數表）
- [ ] T028 [P] 實作樂觀鎖檢核工具：寫入時 WHERE VERSION = ?，不等則回傳衝突訊息
- [ ] T029 [P] 實作 DM Service Client：呼叫 SRVDM001 查詢訓練教材分類文件清單；呼叫 SRVDM002 取得文件最新版內容與廢止狀態（參照 contracts/srv-et-dm-document-*.md；DM 編碼待對齊）
- [ ] T030 [P] 實作平台發信服務 Client：呼叫平台唯一發信服務（傳 `template_code` + 變數），經平台 outbox `DP_EMAIL_LOG` 非同步寄送、回報寄送結果；ET 不自建 SMTP 連線 / 寄件佇列（2026-07-08 集中化；參照 contracts/ext-et-email-server.md）
- [ ] T031 [P] 實作 Token 產生器：邀請 token / 密碼重設 token / Email 變更驗證 token，cryptographically secure random（≥ 32 bytes）
- [ ] T032 [P] 實作邀請碼產生器：8 碼純數字、全域唯一檢核（碰撞時重產）

---

## Phase 3: US2 — UCET012 登入 / 註冊 / 忘記密碼（P1）

> **Story 目標**: 使用者註冊、登入、忘記密碼自助回復
> **獨立測試**: 正確 / 錯誤帳號密碼登入、新註冊自動授予學員角色、忘記密碼信 30 分鐘有效
> **規格子檔**: [spec_us2.md](spec_us2.md) | **驗收情境**: 10 條
> **前置**: Phase 1-2 完成；Email Server 已配置

- [ ] T033 [US2] 實作 `DP_USER` Repository（CRUD、依 EMAIL 查詢、PASSWORD_RESET_* 欄位寫入）
- [ ] T034 [US2] 實作 ET_USER_ROLE Repository（依 USER_ID 查角色清單、寫入新角色）
- [ ] T035 [US2] 實作登入 Endpoint：驗證帳號 / 密碼、產生 session、依角色導向預設首頁（管理者 → ET07、教師 → ET01、學員 → ET04）
- [ ] T036 [US2] 實作登入頁前端（et/login）：登入 / 註冊 / 忘記密碼三項動作；錯誤訊息分流（查無此帳號 / 密碼錯誤）
- [ ] T037 [US2] 實作註冊 Endpoint：檢核 EMAIL 未存在、密碼兩次一致、雜湊儲存；ET_USER_ROLE 自動授予 STUDENT
- [ ] T038 [US2] 實作忘記密碼 Endpoint：寄送密碼重設信至 Email（30 分鐘有效，TTL 由平台級 `DP_PARAM.DP_PASSWORD_RESET_TTL_MIN` 控制，認證由平台 DP 提供）；token 寫入 `DP_USER.PASSWORD_RESET_TOKEN` / EXPIRES_AT
- [ ] T039 [US2] 實作密碼重設頁面（et/reset-password）：驗證 token 有效性、輸入新密碼、雜湊更新 `DP_USER.PASSWORD_HASH`
- [ ] T040 [US2] 忘記密碼 Email 為**平台系統信**（`DP_NOTIFY_TEMPLATE`，`MODULE=DP`；含 user_name、reset_link、ttl_min 變數）——由平台 DP 提供與維護，不在 ET `MODULE=ET` 清單、ET 不開放 UI 編輯（2026-07-08 集中化；ET 寄信呼叫平台發信服務傳 template_code）

---

## Phase 4: US1 — UCET010 權限管理（P1）

> **Story 目標**: 管理者設定其他帳號之角色與受訓單位標籤
> **獨立測試**: 管理者勾選 / 取消角色與受訓單位標籤儲存，使用者下次登入依新角色導向；自我保護與貼標追溯變更規則
> **規格子檔**: [spec_us1.md](spec_us1.md) | **驗收情境**: 15 條
> **前置**: US2 完成（使用者主檔已建立）

- [ ] T041 [US1] 實作 ET_USER_TAG Repository（依 USER_ID 查標籤對應、新增 / 移除對應）（2026-07-02 改寫）
- [ ] T042 [US1] 實作角色變更 Service：寫入 ET_USER_ROLE；自我保護檢核（當前登入管理者不可停用自己之管理者角色）
- [ ] T043 [US1] 實作標籤對應變更 Service（2026-07-02 改寫）：
  - **新增對應**：自動將使用者補加入該標籤所有「已發布且未關閉」課程（寫入 ET_ENROLLMENT，加入來源 = TAG_DEFAULT），並寄**彙整一封**通知信（範本 COURSE_INVITE_DIGEST，列出所有新加入課程）
  - **移除對應**：既有 ET_ENROLLMENT **不變動**；之後新發布之該標籤課程不自動邀請
- [ ] T044 [US1] 實作權限管理 Endpoint（GET / POST）：列出所有使用者 + 角色 + 受訓單位標籤；變更紀錄寫入稽核 log
- [ ] T045 [US1] 實作 ET07 權限管理頁面：使用者清單（含搜尋、標籤篩選）、角色核取方塊、受訓單位標籤展開設定（核取方塊多選）、最後修改欄位顯示

---

## Phase 5: US3 — UCET002 課程建立與編輯（P1）

> **Story 目標**: 教師核心作業：建立 / 編輯課程、章節、教材、測驗、發布 / 草稿
> **獨立測試**: 完整建立一門課程（含章節 / 教材 / 測驗）並發布，學員可加入學習；多裝置編輯衝突偵測
> **規格子檔**: [spec_us3.md](spec_us3.md) | **驗收情境**: 31 條
> **前置**: US1 完成（教師角色已指派）；DM Service Client 已實作

- [ ] T046 [US3] 實作 ET_COURSE Repository（CRUD、樂觀鎖版本檢核、依擁有者查詢、狀態流轉）
- [ ] T047 [US3] 實作 ET_CHAPTER Repository（CRUD、依 COURSE_ID 查詢、拖拉順序 batch 更新、軟刪除）
- [ ] T048 [US3] 實作 ET_ITEM Repository（CRUD、依 CHAPTER_ID 查詢、互斥檢核 MATERIAL_ID / QUIZ_ID）
- [ ] T049 [US3] 實作 ET_MATERIAL Repository（CRUD、影片上傳整合、DM 文件引用清單）
- [ ] T050 [US3] 實作 ET_QUIZ / ET_QUESTION / ET_OPTION Repository（CRUD、配分總和檢核、軟刪除、多選題至少 1 正確選項檢核）
- [ ] T051 [US3] 實作影片上傳 Service：格式檢核（per `DP_PARAM.ET_VIDEO_ALLOWED_FORMATS`）、大小檢核（per `DP_PARAM.ET_VIDEO_MAX_SIZE_MB`）、本地儲存 / OSS 路徑寫入 ET_MATERIAL
- [ ] T052 [US3] 實作課程發布檢核 Service：「至少 1 章節 + 1 教材」+「**至少 1 個受訓單位標籤**」+「**起訖時間已填**」+「各測驗配分總和 = 100」+「無引用之廢止 DM 文件」（呼叫 SRVDM002 判定廢止狀態）；檢核通過後觸發標籤自動邀請（→ T136）（2026-07-02 更新）
- [ ] T053 [US3] 實作 ET02 課程編輯頁面：基本資料區（**受訓單位標籤多選 + 起訖時間**；已發布標籤可加不可移）+ 章節編排（拖拉式 sortable）+ 教材編輯視窗 + 測驗編輯視窗 + 課後問卷區塊（→ T142）+ 儲存草稿 / 發布按鈕（2026-07-02 更新）
- [ ] T054 [US3] 實作教材編輯視窗：三類媒材組合（影片上傳、DM 文件下拉 from SRVDM001、WYSIWYG 說明文字）；廢止文件警告顯示
- [ ] T055 [US3] 實作測驗編輯視窗：測驗設定（及格分數 / 時間限制 / 重考次數）+ 題目編輯（單選 / 多選、題幹、選項、配分）+ 配分總和檢核
- [ ] T056 [US3] 實作樂觀鎖衝突 UI：寫入失敗時跳出「內容已被其他裝置變更，請重新整理後再儲存」提示
- [ ] T057 [US3] 實作章節 / 題目刪除 Service：軟刪除本體（DELETED=1）；學員 ET_PROGRESS / ET_QUIZ_ATTEMPT_D 連帶 hard delete

---

## Phase 6: US4 — UCET007 我的課程與加入新課程（P1）

> **Story 目標**: 學員預設首頁；以邀請碼加入課程
> **獨立測試**: 學員登入 ET04 看到已加入課程；輸入有效 / 無效 / 已加入 / 已停課之邀請碼分別行為
> **規格子檔**: [spec_us4.md](spec_us4.md) | **驗收情境**: 13 條
> **前置**: US3 完成（課程已可發布）

- [ ] T058 [US4] 實作 ET_ENROLLMENT Repository（CRUD、依 USER_ID 查課程清單、依 COURSE_ID 查學員清單、IS_REMOVED 過濾）
- [ ] T059 [US4] 實作我的課程查詢 Service：依 USER_ID 列出已加入課程（過濾 IS_REMOVED）；依學習狀態分區（NOT_STARTED / IN_PROGRESS / COMPLETED）
- [ ] T060 [US4] 實作完課狀態即時計算邏輯：依 ET_PROGRESS 與 ET_QUIZ_ATTEMPT_M 判定 NOT_STARTED / IN_PROGRESS / COMPLETED
- [ ] T061 [US4] 實作邀請碼加入 Service：驗證 INVITATION_CODE 存在、課程狀態為 PUBLISHED、學員未加入；寫入 ET_ENROLLMENT（來源 = INVITATION_CODE）；錯誤分流（無效 / **關閉中（可逆）** / 已加入）（2026-07-02 更新）
- [ ] T062 [US4] 實作 ET04 我的課程頁面：學習狀態分區（總數）+ 課程卡片（含標籤 badges、起訖時間、當前進度、章節數；**不依模組分組**）+ 加入新課程按鈕；**起始前課程不顯示、已關閉課程標示可唯讀回看**（2026-07-02 更新）

---

## Phase 7: US5 — UCET008 章節學習（P1）

> **Story 目標**: 學員依章節順序學習；影片 80% 累計覆蓋率解鎖規則；上次觀看位置自動恢復
> **獨立測試**: 影片播放至 80% 解鎖下一章節；故意快轉跳過 80% 仍鎖定；返回課程定位至上次位置
> **規格子檔**: [spec_us5.md](spec_us5.md) | **驗收情境**: 24 條
> **前置**: US3 完成；US4 完成（學員已加入課程）

- [ ] T063 [US5] 實作 ET_PROGRESS Repository（CRUD、依 USER_ID + COURSE_ID 查進度、依 USER_ID + ITEM_ID 更新）
- [ ] T064 [US5] 實作 ET_PROGRESS_INTERVAL Repository（依 USER_ID + ITEM_ID INSERT / SELECT / DELETE）
- [ ] T065 [US5] 實作章節學習頁面（ET05）：左側章節導覽列（已完成 / 進行中 / 未解鎖狀態標示）+ 中間內容區（影片播放器 / DM 文件預覽 / WYSIWYG 顯示）
- [ ] T066 [US5] 實作 HTML5 影片播放器整合：暫停 / 跳轉 / 結束事件監聽 → INSERT ET_PROGRESS_INTERVAL；onbeforeunload 觸發 normalize；**倍速控制（0.75–2x，上限依 `DP_PARAM.ET_VIDEO_PLAYBACK_MAX_RATE`）**（2026-07-02 更新）
- [ ] T067 [US5] 實作影片覆蓋率計算 Service：聚合 ET_PROGRESS_INTERVAL 之區段聯集去重；更新 ET_PROGRESS.COVERAGE_PCT
- [ ] T068 [US5] 實作 ET_PROGRESS_INTERVAL normalize Service：SELECT → 排序 → 合併重疊 / 鄰近區段 → DELETE → INSERT（學員離開頁面或補做時呼叫）
- [ ] T069 [US5] 實作章節解鎖判定 Service：依章節組成（含影片 / 僅文件 / 含測驗）判定解鎖條件；上一章節未通過時下一章節阻擋
- [ ] T070 [US5] 實作 DM 文件嵌入：PDF 頁內預覽（呼叫 SRVDM002 取得 content_url）；非 PDF 提供「下載原檔」連結；廢止文件顯示「此文件已廢止」標籤
- [ ] T071 [US5] 實作上次觀看位置恢復：依 ET_PROGRESS.LAST_POSITION_SEC 與 ITEM_ID 自動定位
- [ ] T072 [US5] 實作關閉唯讀處理（2026-07-02 改寫）：課程已關閉時學員仍可開啟並**唯讀回看**已學內容；禁止累積進度 / 作答 / 解鎖 / 填問卷；起始時間未到之課程不可進入

---

## Phase 8: US6 — UCET009 線上測驗作答（P1）

> **Story 目標**: 學員線上測驗作答、自動閱卷、強制顯示正確答案、重考機制
> **獨立測試**: 學員完成 attempt 驗證分數正確；多選題部分計分公式套用；未及格可立即重考且題目重新洗牌
> **規格子檔**: [spec_us6.md](spec_us6.md) | **驗收情境**: 28 條
> **前置**: US3 完成（測驗已建立）；US5 完成（章節學習進度判定）

- [ ] T073 [US6] 實作 ET_QUIZ_ATTEMPT_M / ET_QUIZ_ATTEMPT_D Repository（CRUD、寫入快照、依 USER_ID + QUIZ_ID 查最高分）
- [ ] T074 [US6] 實作 Attempt 開始 Service：建立 ET_QUIZ_ATTEMPT_M、寫入題目 / 選項 / 配分快照（snapshot）、題目順序與選項順序洗牌並寫入 QUESTION_ORDER / OPTION_ORDER；依 ET_QUIZ 之 PASS_SCORE / TIME_LIMIT_MIN 寫入快照
- [ ] T075 [US6] 實作測驗引導頁（ET06）：顯示測驗名稱、題數、及格分數、作答時間限制、剩餘重考次數、上次成績；TIME_LIMIT = 0 之測驗於章節學習頁直接隱藏
- [ ] T076 [US6] 實作答題介面：題號進度 + 倒數計時 + 提交按鈕；左側題目導覽列依快照順序呈現；單選 radio / 多選 checkbox；切換題目自動暫存
- [ ] T077 [US6] 實作 timeout 自動提交：倒數計時歸零時前端送出 status = TIMEOUT 之提交請求
- [ ] T078 [US6] 實作 onbeforeunload 防誤離：作答中切換頁面 / 關閉視窗時瀏覽器 native confirm
- [ ] T079 [US6] 實作自動閱卷 Service：依 ET_QUIZ_ATTEMPT_D 之 OPTIONS_SNAPSHOT 判定每題得分（單選：全有全無；多選：部分計分公式 `max(0, (對-誤)/應選×配分)`）；計算總分；判定 is_pass
- [ ] T080 [US6] 實作答題明細頁：顯示總分、是否及格、各題：題型 / 學員當次選擇 / 正確答案 / 結果 / 得分；強制顯示正確答案（無教師設定關閉）
- [ ] T081 [US6] 實作重考流程：未及格且剩餘重考次數 > 0 時顯示「重新作答」按鈕；點擊立即建立新 attempt 並重新洗牌（無 cooldown）
- [ ] T082 [US6] 實作以最高分為結業成績計算：查 ET_QUIZ_ATTEMPT_M 取該 USER_ID + QUIZ_ID 之 MAX(SCORE)；用於完課判定與平均成績
- [ ] T083 [US6] 實作並發處理：教師修改測驗時，已開啟 attempt 沿用快照（不影響 attempt）；學員作答中課程被**關閉**（到期 / 手動）時，attempt 沿用快照可完成並計分、之後不可開新作答；學員作答中被移除時，attempt 可完成並計入歷史（2026-07-02 更新）

---

## Phase 9: US7 — UCET001 課程列表瀏覽（P2）

> **Story 目標**: 教師檢視自己 / 全部課程；他人課程僅可閱覽
> **獨立測試**: 多名教師建立各自課程，於「我建立的」分頁見自己全部狀態、切「全部課程」僅見所有教師之已發布課程
> **規格子檔**: [spec_us7.md](spec_us7.md) | **驗收情境**: 10 條
> **前置**: US3 完成

- [ ] T084 [US7] 實作課程列表查詢 Service：分頁切換（我建立的＝本人全部狀態 / 全部課程＝僅已發布）、關鍵字 / **受訓單位標籤** / 建立者篩選（**不再分組**）（2026-07-02 更新）
- [ ] T085 [US7] 實作 ET01 課程列表頁面：分頁切換 + 搜尋區 + 課程卡片網格（標籤 badges、起訖時間、狀態 pill）；他人課程卡片右上顯示「檢視」標籤；**已關閉**狀態標示（自己課程進入可「再開課」）（2026-07-02 更新）

---

## Phase 10: US8 — UCET004 邀請學員（P2）

> **Story 目標**: 發布時標籤自動邀請＋寄信（主要）；Email 邀請 / 邀請碼補件（2026-07-02 更新）
> **獨立測試**: 掛多標籤課程發布後對應人員聯集去重自動加入且各收一封通知信；Email 邀請含有效與無效 Email，有效寄出、無效列入待加入清單
> **規格子檔**: [spec_us8.md](spec_us8.md)
> **前置**: US3 完成（課程已發布、已掛標籤）；US1 完成（標籤庫與人×標籤對應）；Email Server 已配置

- [ ] T086 [US8] 實作 ET_INVITATION Repository（CRUD、依 COURSE_ID + EMAIL 查詢、狀態流轉）
- [ ] T087 [US8] 實作 Email 邀請 Service：產生 token、建立 ET_INVITATION 紀錄（PENDING）、呼叫 Email Server 寄信；寄信成功 / 失敗皆寫 status_code
- [ ] T088 [US8] 實作邀請信寄送（平台範本 `DP_NOTIFY_TEMPLATE` `MODULE=ET` / `TEMPLATE_CODE=COURSE_INVITE`）：呼叫平台發信服務傳 template_code + 變數（課程名稱、起訖時間、邀請連結、邀請碼）；**統一範本，教師不可編輯主旨與內文**（2026-07-08 集中化）
- [ ] T089 [US8] 實作邀請連結驗證 Endpoint：驗證 token + ET_INVITATION 狀態；自動加入課程（寫 ET_ENROLLMENT，來源 = EMAIL_INVITE）；ET_INVITATION 狀態更新為 JOINED；已加入則跳轉至 ET05
- [ ] T090 [US8] 實作邀請學員 UI（ET02 右上按鈕，僅 PUBLISHED 狀態顯示）：Email 邀請視窗（多筆輸入 + 統一範本信件**預覽（唯讀）** + 寄出）+ 邀請碼視窗（複製 + QR Code；關閉期間失效提示）（2026-07-02 更新）
- [ ] T091 [US8] ~~模組預設帶入 Service~~ → 併入 T136 標籤自動邀請 Service（2026-07-02 廢除改寫；保留編號不再使用）

---

## Phase 11: US9 — UCET005 學員學習狀況追蹤（P2）

> **Story 目標**: 教師追蹤學員完課狀態、進度、成績；重置重考次數 / 移除學員 / 匯出 CSV
> **獨立測試**: 多名學員加入課程後，教師於 ET03 看到各學員狀態；對符合條件之學員執行重置 / 移除
> **規格子檔**: [spec_us9.md](spec_us9.md) | **驗收情境**: 25 條
> **前置**: US3 / US4 / US5 / US6 完成

- [ ] T092 [US9] 實作已加入學員查詢 Service：依 COURSE_ID 列出 ET_ENROLLMENT（過濾 IS_REMOVED）；JOIN `DP_USER` 取姓名；計算完課狀態 / 學習進度（依 ET_PROGRESS 占比）/ 平均成績（已作答測驗最高分平均，排除未作答）/ 最後活動時間
- [ ] T093 [US9] 實作重置重考次數 Service：限定條件「該學員於該測驗已用重考次數 = 上限且尚未及格」；重置即新增允許之 attempt 額度（具體實作可用 ET_QUIZ_ATTEMPT_M 新增允許之計數欄位，或於 Service 端動態計算）。UI 按鈕位於區塊 2 作答明細之各測驗標題列（以測驗為單位；2026-07-02 移入 → T149）
- [ ] T094 [US9] 實作移除學員 Service：寫入 ET_ENROLLMENT.IS_REMOVED = true、REMOVED_AT；若該學員有 IN_PROGRESS attempt 跳警告但允許完成
- [ ] T095 [US9] 實作匯出 CSV Service：依當前篩選條件產生 CSV（含完整欄位）
- [ ] T096 [US9] 實作 ET03 學員頁面（「已加入」頁籤區塊 1 學員清單 + 「待加入」頁籤）：課程下拉 + 學員清單 + 個別操作**僅移除學員**（區塊 1）+ 匯出 CSV 按鈕（依條件啟用 / 禁用；課程已關閉時僅可閱覽）（2026-07-02 更新；作答明細 → T149 區塊 2、重置重考次數按鈕併入 T149 各測驗標題列、問卷結果 → T144 區塊 3）

---

## Phase 12: US10 — UCET011 個人資料維護（P2）

> **Story 目標**: 使用者編輯姓名 / Email / 密碼；Email 變更採雙信箱共存模式
> **獨立測試**: 變更密碼以新密碼登入；變更 Email 後 30 分鐘內點驗證生效、未點則舊 Email 仍可登入
> **規格子檔**: [spec_us10.md](spec_us10.md) | **驗收情境**: 10 條
> **前置**: US2 完成；Email Server 已配置

- [ ] T097 [US10] 實作 Email 變更 Service：寫入 `DP_USER.EMAIL_PENDING_CHANGE` / TOKEN / EXPIRES_AT；舊 EMAIL 不變；寄送驗證信至新 Email；舊請求被新請求取代
- [ ] T098 [US10] 實作 Email 變更驗證 Endpoint：驗證 token 與 expires_at；通過則 `DP_USER.EMAIL` 更新為新值、清除 PENDING；強制當前 session 登出
- [ ] T099 [US10] 實作密碼變更 Service：檢核舊密碼、新密碼兩次一致、雜湊更新 `DP_USER.PASSWORD_HASH`
- [ ] T100 [US10] 實作 ET08 個人資料頁面：姓名 / Email / 變更密碼三區塊；Email 變更後顯示「PENDING：請至新信箱點擊驗證連結」狀態
- [ ] T101 [US10] Email 變更驗證信為**平台系統信**（`DP_NOTIFY_TEMPLATE`，`MODULE=DP`；含 user_name、verify_link、old_email、new_email、ttl_min 變數）——由平台 DP 提供與維護，不在 ET `MODULE=ET` 清單、ET 不開放 UI 編輯（2026-07-08 集中化；ET 寄信呼叫平台發信服務傳 template_code）

---

## Phase 13: US11 — UCET003 課程關閉與再開課（P3）（2026-07-02 全段改寫）

> **Story 目標**: 到期自動關閉 / 教師手動關閉（學員端唯讀、教師端可編輯、可逆）；再開課重設起訖時間
> **獨立測試**: 到期課程自動轉 CLOSED；手動關閉立即 CLOSED、作答中 attempt 可完成計分；再開課重設起訖後學員可續學
> **規格子檔**: [spec_us11.md](spec_us11.md) | **前置**: US3 完成；US6 完成

- [ ] T102 [US11] 實作手動關閉 Service：confirm 後 STATUS 立即 = CLOSED、寫 CLOSED_AT；作答中 attempt 沿用快照允許完成計分（2026-07-02 改寫：PENDING_CLOSE 廢除）
- [ ] T103 [US11] 實作 CLOSED 阻擋新作答：學員嘗試開新 attempt 時拒絕並提示課程已關閉（既有 IN_PROGRESS attempt 可提交）（2026-07-02 改寫）
- [ ] T104 [US11] 實作關閉狀態之學員端 UI：ET04 顯示「已關閉」標示；ET05 轉唯讀回看（→ T072）（2026-07-02 改寫）
- [ ] T105 [US11] 實作關閉狀態之教師端 UI：ET02 編輯頁**課程內容仍可編輯**（owner；非唯讀）、隱藏「關閉課程」顯示「再開課」按鈕（2026-07-02 改寫：教師端由唯讀改為可編輯）
- [ ] T106 [US11] 實作再開課 Service + UI：重設起訖時間 modal（必填檢核）→ STATUS 回 PUBLISHED、URGENT_REMIND_SENT 歸 false；邀請碼恢復有效；可重複多次（2026-07-02 改寫）

---

## Phase 14: US12 — UCET006 待加入邀請追蹤（P3）

> **Story 目標**: 教師追蹤已寄出未加入之邀請、再次寄送 / 撤回
> **獨立測試**: 對待加入邀請執行「再次寄送」觸發新 Email；執行「撤回邀請」使連結失效
> **規格子檔**: [spec_us12.md](spec_us12.md) | **驗收情境**: 7 條
> **前置**: US8 完成

- [ ] T107 [US12] 實作待加入邀請查詢 Service：依 COURSE_ID 列出 ET_INVITATION 狀態 = PENDING
- [ ] T108 [US12] 實作再次寄送 Service：重新呼叫 Email Server 寄出；更新 ET_INVITATION.LAST_SENT_AT
- [ ] T109 [US12] 實作撤回邀請 Service：ET_INVITATION 狀態更新為 REVOKED、寫入 REVOKED_AT；token 失效
- [ ] T110 [US12] 實作邀請連結失效之 UI：學員點擊已撤回邀請顯示「此邀請已撤回」訊息頁
- [ ] T111 [US12] 實作 ET03 待加入分頁：清單（Email / 寄送時間 / 邀請狀態）+ 再次寄送 / 撤回按鈕

---

## Phase 15: 章節更新通知與擁有者轉讓（跨 US 補強）

- [ ] T112 實作章節更新通知 Service：教師於已發布課程新增章節時自動寄信通知所有 ET_ENROLLMENT（過濾 IS_REMOVED）；同時將該課程已完課學員之完課狀態回退為 IN_PROGRESS（已填問卷不失效）
- [ ] T113 實作章節更新通知寄送（平台範本 `DP_NOTIFY_TEMPLATE` `MODULE=ET` / `TEMPLATE_CODE=COURSE_UPDATE`）：呼叫平台發信服務傳 template_code + 變數（user_name、course_name、new_chapter_name、course_link）（2026-07-08 集中化：範本存平台 `DP_NOTIFY_TEMPLATE`）
- [ ] T114 實作擁有者轉讓 Service：管理者執行；寫入 ET_OWNER_TRANSFER 稽核紀錄；更新 ET_COURSE.OWNER_ID
- [ ] T115 實作擁有者轉讓 UI（於 US1 權限管理頁或 US7 課程列表延伸）：管理者選擇課程與接收教師、填寫原因、確認轉讓

---

## Phase 16: 整合與收尾

- [ ] T116 整合測試：完整教師作業流程（建立課程 → 編排章節 / 教材 / 測驗 → 發布 → 邀請學員 → 追蹤學員）
- [ ] T117 整合測試：完整學員作業流程（註冊 → 登入 → 加入課程 → 章節學習 → 通過測驗 → 完課）
- [ ] T118 整合測試：並發場景（多裝置同時編輯 / 學員作答中課程關閉 / 學員作答中移除）（2026-07-02 更新）
- [ ] T119 整合測試：影片觀看 80% 累計覆蓋率與 normalize 機制（含瀏覽器當機補做）
- [ ] T120 整合測試：DM 文件廢止後之 UI 行為（教師端阻擋發布、學員端「此文件已廢止」標籤）
- [ ] T121 整合測試：帳號（Email）變更雙信箱共存模式（驗證後切換、未驗證舊 Email 仍可登入）
- [ ] T122 效能驗證：大量學員加入課程之列表載入（US7 / US9 / US3 邀請學員）；影片觀看區段大量寫入與 normalize 效能
- [ ] T123 安全性檢查：密碼雜湊強度、SMTP TLS、邀請 / 重設 / 變更 token 之 cryptographically secure random；avoid 帳號列舉攻擊（忘記密碼不存在之 Email 仍回應正常訊息）
- [ ] T124 撰寫部署文件：第一個管理者寫入 DB 步驟、ET_TAG seed；ET 系統參數（平台 `DP_PARAM` 前綴 `ET_`）與通知範本（平台 `DP_NOTIFY_TEMPLATE` `MODULE=ET`）seed 由平台 DP 建立、SCHET001 / SCHET002 於平台 `DP_SCHEDULE` 註冊、發信走平台服務（`DP_EMAIL_LOG`）之整合說明、DM 整合說明（2026-07-08 集中化更新）

---

## Phase 17: 2026-07-02 需求變更新增任務

> 對應客戶 6 項變更之全新工作；相依既有 Phase 之基礎元件。
> 編號 T132～T135、T140 **保留不使用**（維持文件內交叉引用穩定，不回頭重排）。

### Migrations 與 Seed（可平行）

- [ ] T125 [P] 建立資料庫 Migration：**ET_COURSE_TAG** 課程標籤對應，含 (COURSE_ID, TAG_ID) 邏輯唯一索引
- [ ] T126 [P] 建立資料庫 Migration：**ET_SURVEY**（含 COURSE_ID 唯一約束）/ **ET_SURVEY_QUESTION** / **ET_SURVEY_OPTION** 課後問卷三表
- [ ] T127 [P] 建立資料庫 Migration：**ET_SURVEY_RESPONSE_M**（含 (SURVEY_ID, USER_ID) 唯一約束）/ **ET_SURVEY_RESPONSE_D**（含 (RESPONSE_ID, SQ_ID) 唯一約束）
- [ ] T128 [P] 建立資料庫 Migration：**ET_WEEKLY_STAT** 週統計快照，含 (COURSE_ID, STAT_DATE) 唯一索引
- [ ] T129 [P] ~~建立 ET_NOTIFY_TEMPLATE 通知範本 Migration~~ **廢除建表**：通知範本表由平台 DP 建立（`DP_NOTIFY_TEMPLATE`）。本任務改為：seed ET **7 類**可維護範本至 `DP_NOTIFY_TEMPLATE`（`MODULE=ET`；COURSE_INVITE / COURSE_INVITE_DIGEST / COURSE_UPDATE / WEEKLY_REMIND / URGENT_REMIND / WEEKLY_REPORT / APPROVAL_PASSED〔2026-07-17 增列〕，皆預設啟用）；密碼重設 / 帳號變更驗證為平台系統信（`MODULE=DP`）由平台維護、不在 ET 清單（2026-07-08 集中化）

### 標籤（US1 / US3）

- [ ] T130 [US1] 實作 ET_TAG Repository 與標籤庫維護 Service + UI（系統設定「參數設定」分頁）：新增 / 修改 / 停用 / 啟用；「全體」不可停用刪除；TAG_NAME 唯一檢核
- [ ] T131 [US3] 實作 ET_COURSE_TAG Repository 與課程標籤掛載 Service：草稿自由增刪；已發布可新增（觸發 T136 補邀請）不可移除；僅可掛啟用中標籤

### 標籤自動邀請（US8）

- [ ] T136 [US8] 實作標籤自動邀請 Service：發布時取 ET_COURSE_TAG × ET_USER_TAG 聯集去重（限學員角色；「全體」展開為全部學員角色者）批次寫入 ET_ENROLLMENT（來源 TAG_DEFAULT）；每人寄一封通知信（COURSE_INVITE，非同步、失敗不回滾加入）
- [ ] T137 [US8] 實作貼標追溯補加入 Service：新增人×標籤時補加入該標籤所有「已發布且未關閉」課程；寄彙整一封（COURSE_INVITE_DIGEST）；供 T043 呼叫

### 課程時窗（US3 / US11 / US14）

- [ ] T138 [US3] 實作課程起訖時間欄位與檢核：發布必填、起 < 迄；學員可見性判定（PUBLISHED 且 now ≥ OPEN_START_AT；now > OPEN_END_AT 視同關閉之應用層即時判定）
- [ ] T139 [US14] 實作到期自動關閉（SCHET002 job handler 內；於平台 `DP_SCHEDULE` 註冊、平台引擎執行）：每日掃描 OPEN_END_AT 已過之 PUBLISHED 課程轉 CLOSED

### 課後問卷（US3 / US13 / US9）

- [ ] T141 [US13] 實作 ET_SURVEY 五表 Repository（含填答唯一約束、題目凍結檢核：有任何 RESPONSE 時拒絕題目/選項寫入）
- [ ] T142 [US3] 實作問卷建立 UI（ET02 課後問卷區塊）：0～1 份 / 課程；單選題目與選項編輯（每題至少 2 選項）；凍結狀態提示；停用問卷
- [ ] T143 [US13] 實作問卷填寫 UI（ET05 入口 + 問卷頁）：完課後顯示入口；逐題單選、全答檢核、送出（具名）；已填→唯讀回看；課程關閉不可填
- [ ] T144 [US9] 實作問卷結果檢視（ET03「已加入」頁籤區塊 3）：各題選項分布統計（人數/百分比、已填未填）+ 逐學員具名明細 + 匯出 CSV；無問卷時本區塊隱藏

### 排程統計與提醒（US14）

- [ ] T145 [US14] 實作 SCHET001 統計快照 Service（job handler 於平台 `DP_SCHEDULE` 註冊、平台引擎執行、`DP_SCHEDULE_LOG` 記錄）：統計開放中課程（平均進度%、三態人數、完課率、已加入數）寫入 ET_WEEKLY_STAT（append-only）
- [ ] T146 [US14] 實作週報產生與寄送：教師（自己課程）/ 管理者（全域）各一封；內文摘要（含與上週比較、距訖止天數、未開始名單）+ CSV 逐學員明細；平台範本 WEEKLY_REPORT（`DP_NOTIFY_TEMPLATE` `MODULE=ET`），經平台發信服務寄送
- [ ] T147 [US14] 實作每週未看提醒：對進度 0% 學員一人一信彙整（平台範本 WEEKLY_REMIND，`MODULE=ET`）；>0% / 已完課 / 已移除不寄
- [ ] T148 [US14] 實作截止前加急提醒（SCHET002 job handler 內）：訖止前 N 天（`DP_PARAM.ET_URGENT_REMIND_DAYS`）對所有未完課學員寄信（平台範本 URGENT_REMIND，`MODULE=ET`）；URGENT_REMIND_SENT 防重複；再開課歸零

### 作答明細檢視（US6 / US9）

- [ ] T149 [US9] 實作教師端每次作答明細 UI：學員列展開歷次 attempt 清單（時間/總分/及格）→ 點入單次逐題明細（依快照渲染：題目/學員作答/正確答案/對錯/得分）
- [ ] T150 [US6] 實作學員端歷次作答明細回看：歷次 attempt 清單入口 + 單次逐題明細（依快照渲染，不限最近一次）

### 通知範本維護（US15）

- [ ] T151 [US15] 實作 ET09 通知範本維護頁（讀寫平台 `DP_NOTIFY_TEMPLATE`，僅 `MODULE=ET` 的列）：7 類範本清單（含 APPROVAL_PASSED；密碼重設 / 帳號變更驗證為平台系統信 `MODULE=DP`、不列入）、主旨/內文編輯（變數插入、未定義變數警告、樂觀鎖）、**啟用 / 停用開關（IS_ACTIVE；停用則該類信件不寄送）**、排程參數調整（平台 `DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` / `DP_PARAM.ET_URGENT_REMIND_DAYS`）；僅管理者可存取。各寄信點（T136 邀請 / T112 內容更新 / T146 週報 / T147 週提醒 / T148 加急 / T159 核可通過）寄送前檢查對應範本 IS_ACTIVE

### 整合測試（2026-07-02 新增情境）

- [ ] T152 整合測試：標籤自動邀請（多標籤聯集去重、全體標籤、每人一信）與貼標追溯（補加入 + 彙整信、移除不變動）
- [ ] T153 整合測試：課程時窗（起始前不可見、到期自動關閉、關閉唯讀、作答中關閉可完成計分、再開課續學、邀請碼失效恢復）
- [ ] T154 整合測試：課後問卷（完課後入口、一人一次、凍結檢核、關閉不可填、教師統計與具名明細）
- [ ] T155 整合測試：排程（週統計快照與上週比較、週報收件範圍、0% 週提醒彙整、加急提醒只寄一次與再開課重計）

---

## Phase 18: 2026-07-17 需求變更新增任務（線下核可 US16 / US17）

> 對應客戶線下核可需求；相依 Phase 5（US3 建課）、Phase 8（US6 完課判定）、Phase 17（範本 seed）。

### Migration 與欄位

- [ ] T156 [P] 建立資料庫 Migration：**ET_APPROVAL** 線下核可紀錄（含 (COURSE_ID, USER_ID) 邏輯唯一索引、VERSION 樂觀鎖）＋ **ET_COURSE.REQUIRE_APPROVAL** 欄位（BOOLEAN，預設 false）；Lookup 增列 `ET_APPROVAL_RESULT`（PASS / FAIL）

### 核可作業（US16）

- [ ] T157 [US16] 實作 ET_APPROVAL Repository + 核可 Service：前提檢核（僅 COMPLETION_STATUS=COMPLETED 可核可）、通過 / 不通過寫入（(COURSE_ID, USER_ID) 唯一、樂觀鎖）、批次核可（未完課者跳過並回報）
- [ ] T158 [US16] 實作撤銷 Service：IS_REVOKED、撤銷原因必填檢核、寫 REVOKED_BY / REVOKED_AT、回「待核可」；撤銷後可重核（同筆更新）
- [ ] T159 [US16] 實作核可通過寄信：結果 PASS 且非撤銷時以平台範本 `APPROVAL_PASSED`（`MODULE=ET`）經平台發信服務寄送；FAIL / 撤銷不寄；寄前檢查 IS_ACTIVE（per T151）
- [ ] T160 [US16] 實作 ET03 核可 UI（「已加入」頁籤區塊 1）：核可狀態欄（未達核可資格 / 待核可 / 已通過 / 未通過）、通過 / 不通過鈕（未完課不顯示核可鈕）、批次核可、撤銷 modal（原因必填）；課程 CLOSED 時唯讀（不可核可 / 撤銷）；僅 owner / 管理者顯示操作
- [ ] T161 [US3] 實作 ET02 「是否需線下核可」（REQUIRE_APPROVAL）開關：課程基本資料可於任一狀態調整；不影響完課判定

### 核可查詢（US17）

- [ ] T162 [US17] 實作 ET10 核可查詢：教師 / 管理者依姓名查全部學員核可課程（含通過 / 不通過 / 撤銷紀錄）；學員自查僅「已通過（有效未撤銷）」；後端依登入身分控管查詢範圍（拒絕學員查他人 / 不通過 / 撤銷）

### 整合測試（2026-07-17 新增情境）

- [ ] T163 整合測試：線下核可（完課前提、通過寄信 / 不通過留紀錄不寄、撤銷需填原因並回待核可、完課回退不使核可失效、課程關閉唯讀、學員只見自己已通過、核可不計入完課率 / 週報）

---

## 依賴關係

```
Phase 1 (設定) → Phase 2 (共用元件)
    ↓
Phase 3 (US2 登入註冊) ←─────── 基礎入口
    ↓
Phase 4 (US1 權限管理) ←─────── 管理者 / 教師 / 學員角色
    ↓
Phase 5 (US3 課程建立與編輯) ←── 教師核心
    ↓
Phase 6 (US4 我的課程與加入) ←── 學員入口
    ↓
Phase 7 (US5 章節學習) ── 可平行 ── Phase 10 (US8 邀請學員) ── 可平行 ── Phase 9 (US7 課程列表)
    ↓
Phase 8 (US6 線上測驗) ←──────── 學員考核
    ↓
Phase 11 (US9 學員追蹤) ── 可平行 ── Phase 12 (US10 個資維護)
    ↓
Phase 13 (US11 關閉/再開課) ── 可平行 ── Phase 14 (US12 待加入追蹤)
    ↓
Phase 15 (跨 US 補強)
    ↓
Phase 17 (2026-07-02 變更：標籤 / 自動邀請 / 時窗 / 問卷 / 排程 / 明細 / 範本)
    ↓
Phase 18 (2026-07-17 線下核可：US16 核可作業 + US17 核可查詢；依賴 US3 / US6 / 範本 seed)
    ↓
Phase 16 (整合收尾，含 T152~T155、T163 新增情境)
```

> Phase 17 之 Migrations（T125~T129）與 Phase 18 之 Migration（T156）可與 Phase 1 同批執行；功能任務依所屬 US 之 Phase 順序插入開發。

**可平行開發機會**：

- Phase 1 內的 T002~T023 可平行執行（不同 Table 之 Migration）
- Phase 2 內的 T025~T032 可平行執行（獨立工具）
- Phase 7 (US5) / Phase 9 (US7) / Phase 10 (US8) 可平行
- Phase 11 (US9) / Phase 12 (US10) 可平行
- Phase 13 (US11) / Phase 14 (US12) 可平行
- 各 Phase 內標記 [P] 的任務可平行執行

---

## 實作策略

**MVP 範圍**: US2 + US1 + US3 + US4 + US5 + US6（Phase 3-8），覆蓋 P1 核心流程；學員可完整完成「註冊 → 加入課程 → 學習 → 通過測驗」之完整流程。

**增量交付**:

1. **Sprint 1**: Phase 1-2（設定 + 共用元件）→ 建立基礎建設
2. **Sprint 2**: Phase 3-4（US2 登入 + US1 權限管理）→ 入口可用
3. **Sprint 3**: Phase 5（US3 建課）→ 教師可建課並發布
4. **Sprint 4**: Phase 6-7（US4 加入 + US5 學習）→ 學員可加入並學習
5. **Sprint 5**: Phase 8（US6 測驗）→ 學員可完整考核（**MVP 完成**）
6. **Sprint 6**: Phase 9-12（P2 各支：US7 / US8 / US9 / US10）→ 教師端輔助功能
7. **Sprint 7**: Phase 13-15（P3 各支 + 跨 US 補強）→ 完整功能
8. **Sprint 8**: Phase 16（整合 + 安全 + 效能）→ 上線就緒

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總任務數 | 158（T001~T163，T091 廢除併入 T136；T132~T135、T140 保留未用）|
| Phase 1 設定（Migrations / Seed）| 24 |
| Phase 2 共用元件 | 8 |
| US2 登入 / 註冊 / 忘記密碼（P1）| 8 |
| US1 權限管理（P1）| 5 |
| US3 課程建立與編輯（P1）| 12 |
| US4 我的課程與加入（P1）| 5 |
| US5 章節學習（P1）| 10 |
| US6 線上測驗作答（P1）| 11 |
| US7 課程列表瀏覽（P2）| 2 |
| US8 邀請學員（P2）| 6 |
| US9 學員學習狀況追蹤（P2）| 5 |
| US10 個人資料維護（P2）| 5 |
| US11 課程關閉與再開課（P3）| 5 |
| US12 待加入邀請追蹤（P3）| 5 |
| 跨 US 補強（章節通知 / 擁有者轉讓）| 4 |
| 整合與收尾 | 9 |
| Phase 17：2026-07-02 變更新增 | 26（Migrations 5、標籤 2、自動邀請 2、時窗 2、問卷 4、排程 4、明細 2、範本 1、整測 4）|
| Phase 18：2026-07-17 線下核可（US16 / US17）| 8（Migration 1、核可作業 5、查詢 1、整測 1）|
| 可平行機會 | Phase 1（22 組 Migration）、Phase 2（8 組工具）、Phase 7+9+10、Phase 11+12、Phase 13+14 |
