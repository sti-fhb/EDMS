# 開發 Issues 清單：教育訓練文件管理模組（Education & Training）

**模組代碼**: ET | **日期**: 2026-06-09
**來源**: [plan.md](plan.md) §功能分群與開發順序 | [tasks.md](tasks.md) | [spec.md](spec.md)

> 每張 Issue 為一個**功能畫面之垂直切割**（DB + API + UI + 驗收條件），可獨立開發、測試與交付。
> Issue #0 為基礎建設，其餘依 plan.md 之 P1 / P2 / P3 階段排序。

---

## Issue 總覽

| # | 標題 | 對應 | 階段 | 涵蓋 Tasks | 主要前置 |
|---|------|------|------|-----------|---------|
| 0 | 專案建置與基礎建設 | — | Setup + Foundational | T001 ~ T032（32 任務）| 無 |
| 1 | 登入頁（登入 / 註冊 / 忘記密碼）| US2 / UCET012 | P1-核心 | T033 ~ T040（8 任務）| #0 |
| 2 | ET07 權限管理 | US1 / UCET010 | P1-核心 | T041 ~ T045（5 任務）| #1 |
| 3 | ET02 課程建立與編輯 | US3 / UCET002 | P1-核心 | T046 ~ T057（12 任務）| #2 |
| 4 | ET04 我的課程與加入新課程 | US4 / UCET007 | P1-核心 | T058 ~ T062（5 任務）| #3 |
| 5 | ET05 章節學習 | US5 / UCET008 | P1-核心 | T063 ~ T072（10 任務）| #3, #4 |
| 6 | ET06 線上測驗作答 | US6 / UCET009 | P1-核心 | T073 ~ T083（11 任務）| #3, #5 |
| 7 | ET01 課程列表瀏覽 | US7 / UCET001 | P2-延伸 | T084 ~ T085（2 任務）| #3 |
| 8 | ET02 邀請學員 | US8 / UCET004 | P2-延伸 | T086 ~ T091（6 任務）| #3, #2 |
| 9 | ET03 學員學習狀況追蹤 | US9 / UCET005 | P2-延伸 | T092 ~ T096（5 任務）| #3, #4, #5, #6 |
| 10 | ET08 個人資料維護 | US10 / UCET011 | P2-延伸 | T097 ~ T101（5 任務）| #1 |
| 11 | ET02 課程停課 | US11 / UCET003 | P3-輔助 | T102 ~ T106（5 任務）| #3, #6 |
| 12 | ET03 待加入邀請追蹤 | US12 / UCET006 | P3-輔助 | T107 ~ T111（5 任務）| #8 |
| 13 | 跨 US 補強：章節更新通知 + 擁有者轉讓 | — | 補強 | T112 ~ T115（4 任務）| #3, #2 |
| 14 | 整合測試 + 安全 + 部署 | — | 收尾 | T116 ~ T124（9 任務）| 全部 |

---

## Issue #0：專案建置與基礎建設

**對應規格**：plan.md §文件結構、§技術背景、§系統參數與初始化；data-model.md
**階段**：Setup + Foundational（為所有 Issue 之前置）
**前置條件**：
- PostgreSQL 已建置；應用伺服器環境就緒
- 與 DM 模組已協調共用 USER 主檔之 schema 定義
- SMTP 伺服器資訊就緒

**涵蓋 Tasks**：
- T001 建立 ET 模組專案結構（controllers / services / repositories / models / migrations / templates）
- T002 ~ T020 建立 19 份 Migration（共用 USER + ET 18 張表）
- T021 ~ T023 建立 Lookup 代碼、ET_MODULE（7 筆業務模組）、ET_PARAM（8 筆系統參數）初始資料
- T024 系統初始化第一個管理者 Seed Script
- T025 ~ T032 共用元件（8 項）：SSO 認證中介層、角色權限檢查、ET_PARAM 載入工具、樂觀鎖檢核、DM Service Client、Email Server Client、Token 產生器、邀請碼產生器

**驗收條件**：
1. 19 張資料表全部建立；標準稽核欄位（CREATED_USER / CREATED_DATE / UPDATED_USER / UPDATED_DATE）齊備
2. 8 類 Lookup 代碼資料、7 筆 ET_MODULE、8 筆 ET_PARAM 載入成功
3. IT 透過 Seed Script 寫入 USER + ET_USER_ROLE（ROLE=ADMIN）後，第一位管理者可登入
4. SSO 認證中介層可驗證 session 並注入 USER_ID 與角色清單
5. 樂觀鎖工具於版本不符時回傳明確衝突訊息
6. DM Service Client 可成功呼叫 SRVDM001 / SRVDM002 取得文件清單與內容
7. Email Server Client 可寄送一封測試信至指定信箱（TLS 連線、模板渲染）
8. Token 產生器產出之 token 至少 32 bytes 且 cryptographically secure

**Labels**：`foundational`, `setup`, `db`, `infra`, `priority:P0`

---

## Issue #1：登入頁（登入 / 註冊 / 忘記密碼）

**對應規格**：[spec_us2.md](spec_us2.md)、UCET012、畫面：登入頁
**階段**：P1-核心
**前置條件**：
- Issue #0 完成（USER / ET_USER_ROLE 表 + SSO 認證中介層 + Email Server Client 就緒）

**涵蓋 Tasks**：
- T033 USER Repository（含 PASSWORD_RESET_* 欄位）
- T034 ET_USER_ROLE Repository
- T035 登入 Endpoint（驗證 + session + 角色導向預設首頁）
- T036 登入頁前端（登入 / 註冊 / 忘記密碼三項；錯誤訊息分流）
- T037 註冊 Endpoint（EMAIL 唯一檢核、密碼雜湊、自動授予 STUDENT）
- T038 忘記密碼 Endpoint（寄送 30 分鐘有效之重設信）
- T039 密碼重設頁面（驗證 token + 雜湊更新）
- T040 忘記密碼 Email 模板（ET_PASSWORD_RESET）

**驗收條件**：
1. 正確帳號 / 密碼登入成功，依角色（管理者 → ET07、教師 → ET01、學員 → ET04）導向預設首頁
2. 錯誤帳號顯示「查無此帳號，請先註冊」；錯誤密碼顯示「密碼錯誤」（不洩漏帳號存在性）
3. 註冊成功後自動授予「學員」角色；跳回登入頁並預填新 Email
4. 重複註冊既有 Email 系統阻擋並提示
5. 忘記密碼後 30 分鐘內點擊重設連結可重設成功
6. 重設連結逾 30 分鐘失效，顯示「連結已失效，請重新申請」
7. 密碼採雜湊儲存（bcrypt 或 argon2）
8. 防帳號列舉：忘記密碼對不存在之 Email 仍回應正常訊息

**Labels**：`P1-核心`, `US2`, `UCET012`, `auth`, `frontend`, `backend`

---

## Issue #2：ET07 權限管理

**對應規格**：[spec_us1.md](spec_us1.md)、UCET010、畫面：ET07
**階段**：P1-核心
**前置條件**：
- Issue #1 完成（使用者主檔已建立）
- 當前登入者具備管理者角色

**涵蓋 Tasks**：
- T041 ET_USER_MODULE Repository
- T042 角色變更 Service（含自我保護檢核）
- T043 業務模組對應變更 Service（新增 = 加入過去課程；移除 = 既有 enrollment 不變動）
- T044 權限管理 Endpoint（GET / POST + 稽核 log）
- T045 ET07 權限管理頁面（使用者清單 + 搜尋 + 角色核取 + 業務模組對應 + 最後修改）

**驗收條件**：
1. 管理者可勾選 / 取消勾選任一帳號之三角色（管理者 / 教師 / 學員），可複選
2. 管理者勾選後立即生效並寫入稽核 log
3. 當前登入者嘗試停用自己之管理者角色 → 系統阻擋並提示
4. 新增業務模組對應 → 該使用者自動加入過去所有該模組之已發布課程
5. 移除業務模組對應 → 既有 ET_ENROLLMENT 不變動；之後新建之該模組課程不自動邀請
6. 使用者首次登入後自動列於本頁，預設僅「學員」角色勾選
7. 使用者離職由共用 user table 停用該帳號，DM / ET 同步生效
8. 業務模組對應變更 / 角色變更均寫入「最後修改」欄（修改者、時間）

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
- T051 影片上傳 Service（格式 / 大小檢核 per ET_PARAM）
- T052 發布檢核 Service（≥1 章節 + 1 教材、各測驗配分 = 100、無引用廢止 DM 文件）
- T053 ET02 課程編輯頁面（基本資料 + 章節編排 + 教材視窗 + 測驗視窗 + 草稿 / 發布按鈕）
- T054 教材編輯視窗（影片 / DM 文件下拉 / WYSIWYG 說明文字；廢止文件警告）
- T055 測驗編輯視窗（設定 + 題目編輯 + 配分總和檢核）
- T056 樂觀鎖衝突 UI
- T057 章節 / 題目刪除（軟刪除本體 + 學員紀錄 hard delete）

**驗收條件**：
1. 教師可建立新課程：填寫名稱、關聯模組、描述；課程建立後關聯模組鎖定不可變更
2. 章節編排支援拖拉調整順序；章節下可放任意數量教材與測驗項目
3. 教材項目支援三類媒材組合：影片本地上傳（mp4 / webm，≤ 500 MB）、DM 訓練教材文件引用、說明文字 WYSIWYG
4. 引用之 DM 文件被廢止時，教材視窗顯示警告；發布檢核阻擋
5. 測驗各題配分總和必須等於 100；多選題至少需 1 個正確選項
6. 「儲存草稿」寫入草稿狀態，學員端不顯示
7. 「發布」檢核通過後寫入首次發布時間（開課日期），開放學員加入
8. 多裝置同時編輯時，樂觀鎖偵測版本衝突並顯示「內容已被其他裝置變更，請重新整理後再儲存」
9. 刪除章節 / 題目 → 本體軟刪除；學員 ET_PROGRESS / ET_QUIZ_ATTEMPT_D 連帶 hard delete
10. 已發布課程再次編輯後儲存即生效，不需重新發布

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
- T062 ET04 我的課程頁面（分區總數 + 模組分組卡片 + 加入新課程按鈕）

**驗收條件**：
1. 學員登入後預設導向 ET04，顯示已加入課程清單
2. 上方依學習狀態分區呈現總數：進行中 / 未開始 / 已完成
3. 下方依關聯模組分組呈現課程卡片
4. 學員輸入 8 碼純數字邀請碼 → 系統驗證後加入課程
5. 無效邀請碼 → 顯示錯誤訊息
6. 已停課課程之邀請碼 → 顯示「此課程已停止開放」
7. 已加入之課程再次輸入邀請碼 → 直接跳轉至 ET05
8. 學員不可主動退出課程（無「退選」入口）；如需移除由教師於 US9 執行

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
- T072 停課處理 UI

**驗收條件**：
1. 學員進入 ET05 後自動定位至上次觀看位置（依 ET_PROGRESS.LAST_POSITION_SEC）
2. 影片累計覆蓋率達 80% 時解鎖下一章節（聚合 ET_PROGRESS_INTERVAL 區段聯集後計算）
3. 故意快轉跳過 80% 範圍不解鎖
4. 文件章節 / 說明文字章節純記錄學習，不強制完成
5. PDF 文件於頁內直接預覽；非 PDF 提供「下載原檔」連結
6. 引用之 DM 文件被廢止時，學員端章節顯示「此文件已廢止」標籤，仍可閱讀廢止前最後版本
7. 學員離開頁面或瀏覽器當機時，ET_PROGRESS_INTERVAL 仍保留已寫入區段；下次進入時 normalize 合併
8. 課程於學習中被停課時顯示「此課程已停止開放」訊息頁
9. 章節含測驗者，需通過測驗（→ Issue #6）方解鎖下一章節

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
- T083 並發處理（教師修改測驗 / 停課 / 移除學員不影響當前 attempt）

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
10. 學員作答中課程被停課 → 當前 attempt 可完成並計入歷史
11. 結業成績取該 USER × QUIZ 之最高分 attempt
12. 每次 attempt 完整保留於歷史紀錄

**Labels**：`P1-核心`, `US6`, `UCET009`, `student`, `quiz`, `auto-grading`, `frontend`, `backend`

---

## Issue #7：ET01 課程列表瀏覽

**對應規格**：[spec_us7.md](spec_us7.md)、UCET001、畫面：ET01
**階段**：P2-延伸
**前置條件**：
- Issue #3 完成

**涵蓋 Tasks**：
- T084 課程列表查詢 Service（分頁切換 + 模組分組 + 多條件篩選）
- T085 ET01 課程列表頁面

**驗收條件**：
1. 「我建立的」分頁僅顯示當前使用者建立之課程
2. 「全部課程」分頁顯示所有教師建立之課程
3. 搜尋條件：關鍵字（課程名稱）、關聯模組；「全部課程」分頁額外提供「建立者」篩選
4. 課程依關聯模組分組呈現
5. 他人建立之課程卡片右上顯示「檢視」標籤；進入後為唯讀模式
6. 已停課課程顯示「已停課」狀態標示，進入後唯讀
7. 點擊搜尋區右側「新增課程」進入 ET02 新增模式

**Labels**：`P2-延伸`, `US7`, `UCET001`, `teacher`, `course`, `frontend`, `backend`

---

## Issue #8：ET02 邀請學員

**對應規格**：[spec_us8.md](spec_us8.md)、UCET004、畫面：ET02（邀請學員視窗）
**階段**：P2-延伸
**前置條件**：
- Issue #3 完成（課程已發布）
- Issue #2 完成（業務模組對應）
- Email Server 已配置

**涵蓋 Tasks**：
- T086 ET_INVITATION Repository（含狀態流轉）
- T087 Email 邀請 Service（token 產生 + 寄信 + status_code 紀錄）
- T088 邀請信模板（ET_INVITATION）
- T089 邀請連結驗證 Endpoint（自動加入 + 跳轉）
- T090 邀請學員 UI（Email 視窗 + 邀請碼視窗）
- T091 模組預設帶入 Service（課程發布時自動加入該模組所有使用者）

**驗收條件**：
1. 課程僅 PUBLISHED 狀態顯示「邀請學員」按鈕
2. Email 邀請：教師輸入多筆 Email → 系統產生邀請信預覽 → 教師可手動編輯主旨 / 內文 → 寄出
3. 邀請寄送失敗時 ET_INVITATION 寫入失敗 status_code，待加入清單仍可見供再次寄送
4. 邀請碼：8 碼純數字，課程發布時自動產生並寫入 ET_COURSE.INVITATION_CODE，不可重新產生 / 手動指定
5. 邀請碼視窗提供複製連結與 QR Code
6. 學員點擊邀請連結後驗證 token 並自動加入課程（來源 = EMAIL_INVITE）
7. 已加入學員再次點擊邀請連結 → 直接跳轉至 ET05
8. 課程發布時自動依 ET_USER_MODULE 對應加入該模組所有使用者（來源 = MODULE_DEFAULT）

**Labels**：`P2-延伸`, `US8`, `UCET004`, `teacher`, `invitation`, `email`, `frontend`, `backend`

---

## Issue #9：ET03 學員學習狀況追蹤

**對應規格**：[spec_us9.md](spec_us9.md)、UCET005、畫面：ET03（已加入分頁；含 CSV 匯出）
**階段**：P2-延伸
**前置條件**：
- Issue #3, #4, #5, #6 完成

**涵蓋 Tasks**：
- T092 已加入學員查詢 Service（含完課狀態 / 進度 / 平均成績計算）
- T093 重置重考次數 Service（限上限已用且未及格時可重置）
- T094 移除學員 Service（IS_REMOVED + REMOVED_AT；IN_PROGRESS attempt 跳警告但允許完成）
- T095 匯出 CSV Service
- T096 ET03 學員頁面（課程下拉 + 學員清單 + 操作按鈕 + 匯出 CSV）

**驗收條件**：
1. 教師於頂部下拉切換課程後，系統列出該課程已加入學員清單（過濾 IS_REMOVED）
2. 學員清單欄位：學員、加入日期、完課狀態（已完成 / 進行中 / 未開始）、學習進度、平均成績、最後活動
3. 平均成績以已作答測驗之最高分平均（排除未作答測驗）
4. 「重置重考次數」僅當該學員之測驗已用次數 = 上限且尚未及格時可用
5. 「移除學員」寫入 IS_REMOVED；若該學員有 IN_PROGRESS attempt 跳警告但允許完成
6. 移除後該學員 ET_ENROLLMENT 不再列入完課率統計，學習歷史保留
7. 「匯出 CSV」依當前篩選條件產生 CSV，含完整欄位
8. 課程已停課時，仍可閱覽學員清單，但不可再執行重置 / 移除

**Labels**：`P2-延伸`, `US9`, `UCET005`, `teacher`, `tracking`, `csv-export`, `frontend`, `backend`

---

## Issue #10：ET08 個人資料維護

**對應規格**：[spec_us10.md](spec_us10.md)、UCET011、畫面：ET08
**階段**：P2-延伸
**前置條件**：
- Issue #1 完成
- Email Server 已配置

**涵蓋 Tasks**：
- T097 Email 變更 Service（雙信箱共存模式：EMAIL_PENDING_CHANGE / TOKEN / EXPIRES_AT）
- T098 Email 變更驗證 Endpoint（驗證後切換 + 強制 session 登出）
- T099 密碼變更 Service（驗證舊密碼 + 雜湊更新）
- T100 ET08 個人資料頁面（姓名 / Email / 變更密碼三區塊 + PENDING 狀態）
- T101 Email 變更驗證信模板（ET_EMAIL_CHANGE）

**驗收條件**：
1. 使用者編輯姓名後直接儲存 → 同步寫入共用 user table，DM / ET 兩端皆生效
2. 變更帳號（Email）：系統寄發驗證信至新 Email，PASSWORD_RESET_TTL_MIN 內有效
3. Email 變更期間舊 Email 仍可登入（雙信箱共存）
4. 點擊驗證連結 → USER.EMAIL 更新為新值、清除 PENDING、強制當前 session 登出
5. 連結逾時或被新請求取代 → 該請求作廢，舊 Email 維持不變
6. 變更密碼：驗證舊密碼 → 新密碼兩次一致 → 雜湊更新；同步寫入共用 user table（DM 同步生效）
7. 舊密碼錯誤 → 顯示「舊密碼不正確」
8. 忘記密碼改走 Issue #1 之忘記密碼流程

**Labels**：`P2-延伸`, `US10`, `UCET011`, `profile`, `email-change`, `frontend`, `backend`

---

## Issue #11：ET02 課程停課

**對應規格**：[spec_us11.md](spec_us11.md)、UCET003、畫面：ET02（停課按鈕）
**階段**：P3-輔助
**前置條件**：
- Issue #3 完成
- Issue #6 完成

**涵蓋 Tasks**：
- T102 停課 Service（檢查 IN_PROGRESS attempt → 直接 CLOSED 或進 PENDING_CLOSE）
- T103 PENDING_CLOSE → CLOSED 自動轉換（事件觸發）
- T104 學員端停課狀態 UI
- T105 教師端停課狀態 UI
- T106 PENDING_CLOSE 阻擋新作答

**驗收條件**：
1. 教師於 ET02 編輯頁右上點擊「停課」（草稿與已停課狀態不顯示）
2. 系統跳 confirm modal 提醒停課不可逆
3. 無 IN_PROGRESS attempt → 直接 STATUS = CLOSED、寫入 CLOSED_AT
4. 有 IN_PROGRESS attempt → STATUS = PENDING_CLOSE、跳警告「N 位學員作答中」
5. PENDING_CLOSE 狀態下：學員嘗試開新 attempt 被拒絕並提示「此課程已停止接受新作答」
6. 既有 IN_PROGRESS attempt 提交後系統檢查該課程是否仍有 IN_PROGRESS；無則自動轉 CLOSED
7. 學員端：開啟已停課課程顯示「此課程已停止開放」訊息頁；ET04 我的課程顯示「已停課」狀態
8. 教師端：ET02 編輯頁顯示「停課中（等待 N 位學員提交）」提示；停課後進入唯讀模式
9. 已停課為終態，不可恢復為已發布

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
- T112 章節更新通知 Service（教師於已發布課程新增章節時自動寄信給所有 enrollment；完課狀態回退為 IN_PROGRESS）
- T113 章節更新通知 Email 模板（ET_NEW_CHAPTER）
- T114 擁有者轉讓 Service（寫 ET_OWNER_TRANSFER 稽核 + 更新 ET_COURSE.OWNER_ID）
- T115 擁有者轉讓 UI（管理者選擇課程 + 接收教師 + 原因 + 確認轉讓）

**驗收條件**：
1. 教師於已發布課程新增章節後，系統自動寄送 ET_NEW_CHAPTER 通知信給所有 enrollment（過濾 IS_REMOVED）
2. 章節更新後，該課程已完課之學員之 ET_ENROLLMENT.COMPLETION_STATUS 回退為 IN_PROGRESS
3. 管理者可於 ET07 權限管理頁或 ET01 課程列表執行擁有者轉讓
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
- T124 部署文件撰寫（管理者初始化 / SMTP 配置 / ET_PARAM 初始化 / DM 整合說明）

**驗收條件**：
1. 教師端完整作業流程通過 E2E 測試
2. 學員端完整作業流程通過 E2E 測試
3. 並發場景測試通過（樂觀鎖衝突、Attempt Snapshot、PENDING_CLOSE 過渡狀態）
4. 影片覆蓋率計算驗證（含瀏覽器當機後 normalize 補做）
5. DM 文件廢止後教師端阻擋發布、學員端顯示「此文件已廢止」標籤
6. 帳號變更雙信箱共存模式驗證通過（驗證後切換、未驗證舊 Email 仍可登入）
7. 大量學員（≥ 500 人）加入課程之列表載入時間 < 2 秒
8. 影片觀看區段批次寫入與 normalize 效能達標
9. 密碼雜湊強度 ≥ bcrypt cost 12 或 argon2 等效；SMTP 採 TLS；所有 token 使用 cryptographically secure random（≥ 32 bytes）
10. 部署文件完整覆蓋第一個管理者寫入、SMTP 配置、ET_PARAM 初始化、DM 整合步驟

**Labels**：`收尾`, `e2e-test`, `performance`, `security`, `deployment`, `documentation`

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
    │      │             └─→ #9 ET03 學員追蹤（US9）
    │      │             └─→ #11 ET02 課程停課（US11）
    │      │
    │      └─→ #5 / #7 / #8 / #10 可平行
    │
    ├─→ #7 ET01 課程列表（US7）
    ├─→ #8 ET02 邀請學員（US8）
    │      ↓
    │      └─→ #12 ET03 待加入追蹤（US12）
    └─→ #10 ET08 個人資料（US10，亦依賴 #1）

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
| User Story | `US1` ~ `US12` |
| Use Case | `UCET001` ~ `UCET012` |
| 角色 | `admin`, `teacher`, `student`, `auth`, `profile` |
| 技術領域 | `frontend`, `backend`, `db`, `email`, `video`, `quiz`, `auto-grading`, `csv-export`, `notification`, `audit` |
| 跨類 | `foundational`, `setup`, `infra`, `e2e-test`, `performance`, `security`, `deployment`, `documentation` |

---

## 摘要

| 項目 | 數量 |
|------|------|
| 總 Issue 數 | 15（#0 ~ #14）|
| P1 核心 | 6（#1 ~ #6）|
| P2 延伸 | 4（#7 ~ #10）|
| P3 輔助 | 2（#11, #12）|
| 補強 | 1（#13）|
| 收尾 | 1（#14）|
| 基礎建設 | 1（#0）|
| 涵蓋 Task 總數 | 124（T001 ~ T124）|
