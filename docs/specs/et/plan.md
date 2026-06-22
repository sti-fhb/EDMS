# 實作計畫：教育訓練文件管理模組（Education & Training）

**分支**: `main` | **日期**: 2026-06-09 | **規格**: [spec.md](spec.md)
**輸入**: 依據 [spec.md](spec.md) 與 [spec_us1.md](spec_us1.md) ~ [spec_us12.md](spec_us12.md) 功能規格產出實作計畫，定義技術背景、文件結構、跨模組依賴與開發順序。

---

## 摘要

教育訓練文件管理模組（ET）為血液中心**內部人員線上教育訓練平台**，核心功能涵蓋課程建立與編輯（章節編排、教材管理、測驗建立、發布與停課、邀請學員）、學員學習（章節學習、強制完成、線上測驗作答）、學員管理（學習狀況追蹤、待加入邀請追蹤）、權限管理與個人資料維護。教材文件統一引用文件管理模組（DM）之「訓練教材」分類，避免教材與規範文件重複維護；DM 端發布新版時 ET 教材自動取得最新版。

本模組**獨立於主系統 TBMS 部署**，與 DM 採 SSO（Single Sign-On）共用 user table（USER_ID / 帳號 / 密碼 / 姓名），但兩模組各自管理自己的角色與業務模組對應；與主系統各業務模組之帳號完全切開、不依賴 DP 模組之參數機制（影片格式 / 大小上限等系統參數由 ET 內部 `ET_PARAM` 自行維護）。

外部介接僅有 Email Server（寄發課程邀請信、密碼重設信、帳號變更驗證信）；跨模組僅有 DM 文件查詢（讀取「訓練教材」分類之有效文件清單與內容）。

---

## 技術背景

| 項目 | 內容 |
|------|------|
| 介接方式 | RESTful API（前後端）+ 與 DM 共用之 user table |
| 前端 | Web 應用程式（教師 / 學員 / 管理者三套介面，需支援 Chrome、Edge、Firefox）；採 Bootstrap 樣式風格 |
| 影片播放 | HTML5 video player（不串接 YouTube / Vimeo 等外部影音平台）|
| 資料庫 | PostgreSQL（per CLAUDE.md 規範）|
| 認證機制 | 與 DM SSO 共用帳號；密碼採雜湊儲存；登入採 session 機制 |
| 認證範圍 | 僅涵蓋 ET + DM 兩系統；與主系統 TBMS 各業務模組之帳號**完全切開** |
| 安全性 | 所有操作留存稽核日誌（建立者 / 異動者、建立時間 / 異動時間）|
| 可用性 | 內部訓練系統，營業時段內運作；無 24×7 高可用性要求 |
| 部署 | **獨立部署**（不隨主系統 TBMS 各業務模組共構），與 DM 共構或獨立部署皆可（部署策略由維運決定）|
| 模組代碼 | ET（教育訓練文件管理）|

---

## Constitution 檢查

Constitution 尚未設定（仍為模板），無違規項目。

---

## 文件結構

### 設計文件（本功能）

```text
specs/et/
├── spec.md              # 功能規格總檔
├── spec_us1.md          # User Story 1：權限管理（ET07 / UCET010）
├── spec_us2.md          # User Story 2：登入 / 註冊 / 忘記密碼（UCET012）
├── spec_us3.md          # User Story 3：課程建立與編輯（ET02 / UCET002）
├── spec_us4.md          # User Story 4：我的課程與加入新課程（ET04 / UCET007）
├── spec_us5.md          # User Story 5：章節學習（ET05 / UCET008）
├── spec_us6.md          # User Story 6：線上測驗作答（ET06 / UCET009）
├── spec_us7.md          # User Story 7：課程列表瀏覽（ET01 / UCET001）
├── spec_us8.md          # User Story 8：邀請學員（ET02 / UCET004）
├── spec_us9.md          # User Story 9：學員學習狀況追蹤（ET03 / UCET005）
├── spec_us10.md         # User Story 10：個人資料維護（ET08 / UCET011）
├── spec_us11.md         # User Story 11：課程停課（ET02 / UCET003）
├── spec_us12.md         # User Story 12：待加入邀請追蹤（ET03 / UCET006）
├── plan.md              # 本文件（實作計畫）
├── research.md          # Phase 0 研究成果（設計決策紀錄）
├── data-model.md        # Phase 1 資料模型（ERD + DD）
├── contracts/           # Phase 1 介面契約
│   ├── srv-et-dm-document-list.md        # 查詢 DM「訓練教材」分類有效文件清單（ET → DM）
│   ├── srv-et-dm-document-content.md     # 取得 DM 文件最新版內容（ET → DM）
│   └── ext-et-email-server.md            # 寄送邀請信 / 密碼重設信 / 帳號變更驗證信（ET → Email Server）
├── checklists/
│   └── requirements.md  # 規格品質檢核（待產出）
└── tasks.md             # Phase 2 開發任務清單
```

### 相關目錄

```text
use-cases/et/            # 使用案例（已完成，含 12 條 UCET001 ~ UCET012）
wireframes/et/index.html # 畫面原型（ET01 ~ ET08 共 8 張畫面）
requirements/RQET.md     # 需求清單（已完成）
_refs/10-教育訓練文件管理模組.md  # 來源分析資料（source of truth）
```

---

## 跨模組依賴摘要

> 參考 [spec.md](spec.md) §跨模組介接總覽。

| 方向 | 介接對象 | 編碼 | 介接方式 | 說明 |
|------|---------|------|---------|------|
| ET ↔ DM | 文件管理模組（DM） | — | **共用 user table** | USER_ID / 帳號 / 密碼 / 姓名共用；但 ET / DM **各自管理自己的角色與業務模組對應**，互不影響 |
| ET → DM | 文件管理模組（DM） | SRVDM001 *(待 DM 編碼確認)* | 內部服務（主動呼叫） | 查詢「訓練教材」分類之有效文件清單（教師建立教材時下拉選取使用） |
| ET → DM | 文件管理模組（DM） | SRVDM002 *(待 DM 編碼確認)* | 內部服務（主動呼叫） | 取得指定文件之最新版內容（學員端 ET05 章節學習頁顯示文件預覽 / 下載原檔）|
| ET → DM | 文件管理模組（DM） | — | 內部事件 / 查詢 | 偵測 DM 文件廢止狀態（教師端 ET02 編輯頁顯示警告、學員端 ET05 顯示「此文件已廢止」標籤）|
| ET → Email Server | 外部郵件系統 | EXT-EMAIL | SMTP | 寄送課程邀請信（US8）、密碼重設信（US2）、帳號（Email）變更驗證信（US10）、章節更新通知信（US3）|

> 本模組**不依賴 DP 模組**（不讀取 DP 參數、不呼叫 DP Service）。影片格式 / 大小上限等系統參數由 ET 內部 `ET_PARAM` 自行維護，IT 直接於 DB 設定。

---

## 功能分群與開發順序

### 第一階段（P1 核心流程）

| 群組 | 對應 User Story | 對應 UC | 規格檔 | 說明 |
|------|----------------|---------|--------|------|
| 權限管理 | US1 | UCET010 | spec_us1.md | 管理者設定角色 / 業務模組對應；系統初始化第一個管理者由 IT 透過 DB 寫入 |
| 登入 / 註冊 / 忘記密碼 | US2 | UCET012 | spec_us2.md | 共用 user table 之 SSO 認證；註冊自動授予「學員」角色；登入依角色導向預設首頁；忘記密碼 30 分鐘有效之重設連結 |
| 課程建立與編輯 | US3 | UCET002 | spec_us3.md | 教師核心作業：基本資料 / 章節編排 / 教材管理 / 測驗建立 / 儲存草稿 / 發布；多裝置同時編輯採樂觀鎖 |
| 我的課程與加入新課程 | US4 | UCET007 | spec_us4.md | 學員入口頁；以邀請碼（純數字 8 碼）加入課程；學員無主動退出能力 |
| 章節學習 | US5 | UCET008 | spec_us5.md | 章節順序解鎖（影片累計覆蓋率 ≥ 80%）；文件 / 說明文字章節純記錄不強制；學員端影片觀看區段儲存於 `ET_PROGRESS_INTERVAL` 獨立 table |
| 線上測驗作答 | US6 | UCET009 | spec_us6.md | 引導頁 + 答題介面 + 自動閱卷 + 答題明細；多選題部分計分；題目與選項洗牌（Attempt Snapshot）；重考無冷卻；強制顯示正確答案 |

### 第二階段（P2 延伸流程）

| 群組 | 對應 User Story | 對應 UC | 規格檔 | 說明 |
|------|----------------|---------|--------|------|
| 課程列表瀏覽 | US7 | UCET001 | spec_us7.md | 教師檢視自己 / 他人建立之課程；依關聯模組分組；他人課程僅可閱覽（唯讀）|
| 邀請學員 | US8 | UCET004 | spec_us8.md | Email 邀請 / 邀請碼 / 模組預設帶入；業務模組對應變更：移除不變動既有名單、新增自動加入過去課程 |
| 學員學習狀況追蹤 | US9 | UCET005 | spec_us9.md | 已加入學員之完課狀態 / 進度 / 平均成績；重置重考次數（限次數歸 0 時）；移除學員；支援 CSV 匯出 |
| 個人資料維護 | US10 | UCET011 | spec_us10.md | 編輯姓名 / 帳號（Email）/ 密碼；帳號變更採雙信箱共存模式（驗證後切換、舊 Email 變更期間仍可用）|

### 第三階段（P3 終態與輔助）

| 群組 | 對應 User Story | 對應 UC | 規格檔 | 說明 |
|------|----------------|---------|--------|------|
| 課程停課 | US11 | UCET003 | spec_us11.md | 已發布課程之終態變更；有學員作答中時進入 `PENDING_CLOSE` 過渡狀態，全部 attempt 提交後自動轉 `CLOSED` |
| 待加入邀請追蹤 | US12 | UCET006 | spec_us12.md | 已寄出未加入邀請之再寄送 / 撤回 |

---

## 系統參數與初始化

### ET_PARAM（系統參數）

ET 內部參數表，由 IT 直接於 DB 設定，**不依賴主系統 DP 模組**：

| 參數類別 | 用途 | 預設值 |
|---------|------|--------|
| `VIDEO_ALLOWED_FORMATS` | 教材影片允許之上傳格式 | `mp4,webm` |
| `VIDEO_MAX_SIZE_MB` | 教材影片單檔大小上限 | `500` |
| `PASSWORD_RESET_TTL_MIN` | 密碼重設連結 / Email 變更驗證連結有效時間（分鐘）| `30` |
| `INVITATION_CODE_LENGTH` | 邀請碼長度（純數字）| `8` |
| `EMAIL_NOTIFY_NEW_CHAPTER` | 新增章節通知信模板代碼 | `ET_NEW_CHAPTER` |
| `EMAIL_NOTIFY_INVITATION` | 課程邀請信模板代碼 | `ET_INVITATION` |
| `EMAIL_NOTIFY_PASSWORD_RESET` | 密碼重設信模板代碼 | `ET_PASSWORD_RESET` |
| `EMAIL_NOTIFY_EMAIL_CHANGE` | 帳號變更驗證信模板代碼 | `ET_EMAIL_CHANGE` |

> 參數類別與預設值由 plan / data-model 階段最終確認；本表為設計起點。

### 系統初始化

- **第一個管理者**：首次部署時由 IT 透過 DB 直接寫入 `USER` + `ET_USER_ROLE`（ROLE=管理者）
- **業務模組清單**：採血 / 成分 / 檢驗 / 供應 / 醫務 / 報表與標籤 / 其他七類，由系統內定於 `ET_MODULE`，不開放管理者新增

---

## 並發控制策略

| 場景 | 策略 | 實作概要 |
|------|------|---------|
| 多裝置同時編輯課程 | 樂觀鎖 | 每實體（課程 / 章節 / 教材 / 測驗 / 題目）DB 維護 `VERSION` 欄位；寫入時檢核版本，不等則拒絕 |
| 學員作答中 + 教師修改測驗 | Attempt Snapshot | `ET_QUIZ_ATTEMPT_M` 於開始作答時凍結「題目 + 選項 + 配分 + 及格分數 + 作答時間限制 + 題目順序 + 選項順序」版本快照；該 attempt 完成前不受變更影響 |
| 學員作答中 + 教師停課 | Graceful Termination | 課程進入 `PENDING_CLOSE` 過渡狀態，新學員不可加入、不可開新 attempt；既有 attempt 完成後自動轉 `CLOSED` |
| 學員作答中 + 教師移除學員 | 保留當前 attempt | 立即標記 ET_ENROLLMENT 移除；當前 attempt 沿用快照完成並計入歷史；學員 next page navigation 被導至「您已被該課程移除」 |
| 影片觀看區段寫入 | 獨立 table INSERT | `ET_PROGRESS_INTERVAL` 每段播放 INSERT 一筆，避免 read-modify-write race；學員離開頁面時 normalize 合併重疊 / 鄰近區段 |

---

## 複雜度追蹤

> 無 Constitution 違規需要正當化說明。

| 設計決策 | 理由 | 備註 |
|----------|------|------|
| ET 與 DM 共用 user table 但角色分管 | 兩系統業務性質不同（教育訓練 vs. 文件管理），各自之角色與權限體系不互通；但同一使用者註冊一次即可登入兩系統，降低帳號管理負擔 | 與主系統 TBMS 各業務模組之帳號完全切開 |
| 影片本地上傳（不串外部影音平台）| 內部訓練教材有保密性考量，不適合上傳至 YouTube / Vimeo 等公開平台 | 影片格式與大小上限由 ET_PARAM 控制 |
| 教材文件統一由 DM 提供 | 避免訓練教材與規範文件兩處維護版本不一致 | DM 端發布新版時 ET 自動取得最新版；廢止後 ET 教師端阻擋發布 |
| 章節 / 題目本體軟刪除 + 學員紀錄 hard delete | 章節 / 題目本體保留供稽核；學員紀錄孤兒化無意義（完課率以當前章節數為分母重算） | 移除學員不同：學員 ET_ENROLLMENT 標記移除但學習歷史保留 |
| 多選題採 Moodle 部分計分公式 | 業界 LMS 標準；平衡「全有全無」過嚴與「比例給分」過鬆 | 公式：max(0, (對 − 誤) ÷ 應選 × 配分)；題目建立時強制至少 1 正確選項 |
| Attempt Snapshot | 學員作答中教師修改測驗不影響當前 attempt，避免吞分爭議 | DB 儲存題目 + 選項 + 配分 + 順序之版本快照 |
| 影片觀看區段獨立 table（非 JSON）| PostgreSQL 規範限用標準型別（無 JSONB）；獨立 table 避免 read-modify-write race；便於 SQL 直接聚合 | 學員離開頁面時 normalize 合併 |
| 邀請碼純數字 8 碼、不可重新產生 / 手動指定 | 簡化邀請碼管理；外洩風險可透過停課重建課程處理 | `ET_COURSE.INVITATION_CODE` 寫入後不可變更 |
| 帳號變更採雙信箱共存模式 | 避免變更未完成即無法登入；驗證信 30 分鐘有效，未點視為作廢 | `USER` 新增 EMAIL_PENDING_CHANGE / EMAIL_PENDING_TOKEN / EMAIL_PENDING_EXPIRES_AT |
| 課程擁有者轉讓由管理者代為執行 | 因課程擁有者欄位永久不可變更為原則，但需處理教師離職情境；以管理者代為轉讓為例外，並寫入 `ET_OWNER_TRANSFER` 稽核紀錄 | 一般教師不可主動轉讓 |
| 不設「至少保留 1 個管理者」之系統檢核 | 此情境極少，由 IT 透過 DB 寫入恢復即可，增加檢核增加系統複雜度 | 設計取捨：簡化邏輯 vs. 容錯能力 |
