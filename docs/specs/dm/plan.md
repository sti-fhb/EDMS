# 實作計畫：文件管理模組（Document Management）

**分支**: `main` | **日期**: 2026-06-24 | **規格**: [spec.md](spec.md)
**輸入**: 依據 [spec.md](spec.md) 與 spec_us1~12.md 產出實作計畫；對齊 [_refs/11-文件管理模組.md](../../_refs/11-文件管理模組.md)、[requirements/RQDM.md](../../requirements/RQDM.md)、[use-cases/dm/usecases.md](../../use-cases/dm/usecases.md)、[wireframes/dm/index.html](../../wireframes/dm/index.html) 與交付確認書

---

## 摘要

文件管理模組（DM）提供院方 SOP、系統操作手冊、訓練教材、其他等文件之集中儲存、版本管控、單層簽核發布與線上閱覽。本模組**獨立於主系統 TBMS 部署**，與教育訓練模組（ET）共用同一帳號系統與資料庫（SSO）；ET 之訓練教材統一引用 DM 文件（依 DOC_ID 取最新發布版）。

DM 自身持有 14 張表：共用 `USER`（與 ET 共用）、角色 `DM_USER_ROLE` + 異動紀錄 `DM_USER_ROLE_LOG`、受控資料 `DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG`、文件 `DM_DOCUMENT` + 版本 `DM_DOC_VERSION` + 標籤關聯 `DM_DOC_TAG`、送審 `DM_REVIEW`、公開變更歷程 `DM_CHANGE_LOG`、通知範本 `DM_NOTIFY_TEMPLATE`、系統參數 `DM_PARAM`。核心作業對應 12 個 User Story（UCDM01~12）。

---

## 技術背景

**介接方式**: DM 後端對前端提供 RESTful API；對 ET 提供內部服務（依 DOC_ID 取文件當前發布版）；對外寄送經 Email Server（SMTP）
**前端**: Web 應用程式；PDF / 圖片內嵌預覽、檔案上傳（單檔 ≤ 50 MB）、多條件檢索、版本歷程抽屜
**資料庫**: PostgreSQL（命名 / 型別遵循 CLAUDE.md；不使用 JSONB；檔案存檔案系統 / 物件儲存，DB 僅存 metadata）
**認證**: SSO，與 ET 共用 user table；**獨立於主系統 DP**（無 DP RBAC、無站點 / 院區）；DM 僅管理自己之 4 角色
**保留**: 版本、公開變更歷程、角色異動紀錄**永久保留**（不可竄改 / 刪除）
**專案類型**: Web 應用程式（文件協作與簽核）+ 對 ET 之內部服務
**模組代碼**: DM（文件管理）

---

## Constitution 檢查

Constitution 尚未設定（`.specify/memory/constitution.md` 仍為模板），無違規項目。

---

## 文件結構

### 設計文件（本功能）

```text
specs/dm/
├── spec.md              # 模組總覽（US 索引、Clarifications×7、訊息類型、Key Entities、業務規則、SC、Assumptions、RQ 矩陣）
├── spec_us1.md          # US1 系統設定（UCDM11）
├── spec_us2.md          # US2 登入 / 註冊 / 忘記密碼（UCDM01）
├── spec_us3.md          # US3 文件庫與檢索（UCDM03）
├── spec_us4.md          # US4 文件詳細頁瀏覽（UCDM04）
├── spec_us5.md          # US5 文件新增與編輯（UCDM06）
├── spec_us6.md          # US6 簽核處理（UCDM07）
├── spec_us7.md          # US7 系統儀表板（UCDM02）
├── spec_us8.md          # US8 文件廢止申請（UCDM05）
├── spec_us9.md          # US9 個人專區（UCDM09）
├── spec_us10.md         # US10 已廢止文件查詢（UCDM08）
├── spec_us11.md         # US11 文件變更歷程查詢（UCDM10）
├── spec_us12.md         # US12 跨模組教材引用（UCDM12）
├── plan.md              # 本文件
├── research.md          # Phase 0 研究（10 項決策，含 DP 獨立之稽核欄位調整）
├── data-model.md        # Phase 1 資料模型（ERD + DD，14 張表）
├── contracts/
│   └── document-service.md  # DM→ET 文件取用內部服務（SRVDM001 / SRVDM002）
├── checklists/
│   └── requirements.md  # 規格品質檢核
└── tasks.md             # Phase 2 開發任務清單（待 /speckit.tasks）
```

### 相關目錄

```text
use-cases/dm/usecases.md   # 使用案例（UCDM01~12 + RQ 追蹤矩陣）
wireframes/dm/index.html   # 畫面原型（DM00 儀表板 / DM01 文件庫 / DM02 詳細頁 / DM03 新增編輯 / DM04 簽核 / DM06 已廢止 / DM07 個人專區 / DM08 變更歷程 / DM09 系統設定）
requirements/RQDM.md       # 需求清單
_refs/11-文件管理模組.md   # 分析資料（source of truth）
docs/deliverables/需求規格確認書/交付版本/需求規格確認書_文件管理模組.docx  # 交付確認書
```

---

## 跨模組依賴摘要

DM 與主系統 TBMS 各業務模組**帳號完全切開**，僅與 ET 共用帳號系統並提供文件取用服務：

| 方向 | 介接對象 | 編碼 | 介接方式 | 說明 | 契約位置 |
|------|----------|------|----------|------|---------|
| DM ↔ ET | 教育訓練模組（ET）| — | 共用 user table（SSO）| USER_ID / 帳號 / 密碼 / 姓名；DM / ET 各管自己角色 | DM 與 ET 共同維護 `USER` schema |
| DM → ET | 教育訓練模組（ET）| **SRVDM001** | 內部服務（ET 呼叫）| 依 DOC_ID 取文件當前發布版（CURRENT_VERSION_ID）之 metadata 與檔案位置 | [contracts/document-service.md](contracts/document-service.md) |
| DM → ET | 教育訓練模組（ET）| **SRVDM002** | 內部服務（ET 呼叫）| 取「訓練教材」分類之有效文件清單（ET 教材下拉用）| [contracts/document-service.md](contracts/document-service.md) |
| DM → Email Server | 外部郵件系統 | — | SMTP | 送審 / 退回 / 發布 / 廢止通知、密碼重設信、帳號變更驗證信 | 外部介接（部署設定）|

> **2026-06-26 變更**：移除原「DM → 主系統各畫面 func_name 反查」介接列；DM 與主系統 TBMS 各業務模組無業務介接。func_name 僅供 DM01 內部檢索。

> ET 端對 DM 文件廢止之 UI 行為（教材編輯標示、發布阻擋、學員端標籤）詳見 ET 模組 spec「DM 文件廢止之 UI 規則」；DM 端僅負責提供版本資料與廢止通知。

---

## 待定案技術決策（本計畫定案，詳見 [research.md](research.md)）

| 議題 | 決策 |
|------|------|
| 稽核標準欄位（DM 獨立於 DP）| 省略 CREATED_SITE / CREATED_HOSPITAL（無 DP_SITE / DP_HOSPITAL 來源）；採 CREATED_USER / DATE、UPDATED_USER / DATE、RES_ID、DELETED（research §1）|
| DOC_ID 產生 | `DM-{分類碼}-{6 位流水號}`、流水號依分類獨立、草稿建立時配號（research §2）|
| 檔案儲存 | 單版本單檔；檔案存檔案系統 / 物件儲存，DB 存 metadata（不存 BLOB）（research §3）|
| func_name 唯一性 | 部分唯一索引（MANUAL + PUBLISHED）+ 應用層檢核（research §5）|
| 發布 / 廢止原子性 | 單一交易完成版本切換 + 變更歷程 + 通知（research §6）|
| 永久保留 | 版本軟刪除永久保留；變更歷程 / 角色異動 append-only 永久保留（research §7）|
| 自動催辦 | 每日排程掃 DM_REVIEW 停留 ≥ 門檻，僅站內訊息（research §9）|

---

## 功能分群與開發順序

### 第一階段（P1 MVP — 設定 + 文件生命週期核心）

| 群組 | User Story | 對應作業 | 說明 |
|------|------------|---------|------|
| 登入與帳號 | US2 | 登入頁 | SSO 共用 user table、註冊授閱覽者、忘記密碼 |
| 系統設定 | US1 | DM09 | 分類 / func_name / 標籤 / 催辦門檻 / 角色指派（含異動紀錄）/ 通知範本 |
| 文件庫與檢索 | US3 | DM01 | 多條件 AND、僅顯示已發布、func_name 下拉檢索 |
| 文件詳細頁 | US4 | DM02 | 預覽 / 下載規則、版本歷程、read-only 模式 |
| 文件新增與編輯 | US5 | DM03 | DOC_ID 配號、身份欄唯讀、func_name 唯一檢核、單檔上傳、審核者排除自己 |
| 簽核處理 | US6 | DM04 | 三類送審核准 / 退回、原子發布 / 廢止、催辦、寫變更歷程 |

### 第二階段（P2 廢止 / 個人化 / 稽核查閱）

| 群組 | User Story | 對應作業 | 說明 |
|------|------------|---------|------|
| 系統儀表板 | US7 | DM00 | 各類型總數 + 近 30 天公告 |
| 文件廢止申請 | US8 | DM02 | 整份廢止、廢止待簽核仍對外、撤回 |
| 個人專區 | US9 | DM07 | 個人資料維護 / 草稿 / 撤回送審 / 我的文件動態 / 可見性 |
| 已廢止文件查詢 | US10 | DM06 | 管理者稽核查閱、CSV、read-only、URL 擋 |

### 第三階段（P3 跨文件稽核 / 跨模組）

| 群組 | User Story | 對應作業 | 說明 |
|------|------------|---------|------|
| 文件變更歷程查詢 | US11 | DM08 | 跨文件公開變更（發布 / 廢止）、CSV、永久保留 |
| 跨模組教材引用 | US12 | — | SRVDM001 / SRVDM002 供 ET；廢止通知 ET |

---

## 複雜度追蹤

> 無 Constitution 違規需要正當化說明。

| 設計決策 | 理由 | 備註 |
|----------|------|------|
| 標準欄位省略 SITE / HOSPITAL | DM 獨立於 DP、無站點 / 院區概念，FK 無對應來源 | 與 CLAUDE.md 標準欄位之差異已於 research §1 載明；CREATED_USER 指向共用 USER |
| 角色異動另立 append-only log（DM_USER_ROLE_LOG）| 滿足「完整異動歷史永久保留」；DM 獨立、無主系統 SRVDP003 / DP_AUDIT_LOG 可用 | 不提供查詢 UI；DM09 僅顯示「最後異動」欄 |
| 文件 / 版本雙層 STATUS | 支援「已發布 + 新版本送審中」並存之狀態表達 | 文件層 STATUS + 版本層 STATUS；單一送審週期由 DM_REVIEW 約束 |
| func_name 部分唯一索引 | DM01 依作業項目檢索須唯一手冊；DB 約束防並發雙發布 | 草稿 / 已廢止不佔用；應用層另給友善訊息 |
| 檔案存檔案系統而非 DB | 遵循型別規範、利備份效能 | DB 存 metadata + 路徑；單版本單檔 |
