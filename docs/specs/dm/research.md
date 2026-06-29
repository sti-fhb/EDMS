# 研究決策：文件管理模組（Document Management）

**日期**: 2026-06-24
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md)
**資料庫**: PostgreSQL（命名 / 型別遵循 CLAUDE.md）

> 本檔記錄 DM 設計階段之關鍵技術決策（Decision / Rationale / Alternatives）。多數來自 spec.md 之 7 條 Clarifications，部分為 plan 階段定案。

---

## §1 稽核標準欄位之調整（DM 獨立於 DP）

- **Decision**: DM 各表標準欄位採 `CREATED_USER` / `CREATED_DATE` / `UPDATED_USER` / `UPDATED_DATE` / `RES_ID` / `DELETED`，**省略 `CREATED_SITE` / `CREATED_HOSPITAL`**（及對應 UPDATED_*）。`CREATED_USER` / `UPDATED_USER` 指向共用 `USER.USER_ID`。
- **Rationale**: DM 與 ET **獨立部署、不依賴主系統 DP**（無 DP RBAC、登入不選站點 / 院區、無 DP_SITE / DP_HOSPITAL）。CLAUDE.md 標準欄位之 `CREATED_SITE`（FK→ DP_SITE）在 DM 無對應來源，強行加入將造成懸空 FK。DM 使用者經 SSO 登入、無站點隸屬概念。
- **Alternatives**: (a) 保留 CREATED_SITE 但填 null → 違反必填且 FK 無意義；(b) 自建 DM 站點表 → DM 無站點業務，過度設計。均否決。

## §2 DOC_ID 產生規則

- **Decision**: `DM-{分類碼}-{6 位零填補流水號}`（如 `DM-SOP-000123`）；流水號**依分類各自獨立**，**草稿建立時即配號**（分類於建立時已選定）。
- **Rationale**: DOC_ID 為「對外引用基準」需人可讀；分類碼於建立後鎖定故穩定。每分類一個序列來源（PG `SEQUENCE` 或計數表），草稿即配號利於前端顯示與引用。
- **Alternatives**: 全域流水（B）— 分類碼僅標籤、可讀性低；UUID — 不利人工引用。均否決（spec Clarify）。
- **註**: 草稿刪除造成之號碼跳號可接受（spec Assumptions）。

## §3 檔案儲存

- **Decision**: **每版本單一檔案**；檔案實體存於檔案系統 / 物件儲存，DB（`DM_DOC_VERSION`）僅存檔名 / 路徑 / 大小 / MIME 等 metadata，**不存 BLOB**。單檔上限預設 50 MB（由 `DM_PARAM` 控制）。
- **Rationale**: 符合 spec Clarify「單版本單檔」；DB 不存大型二進位，利於備份與效能。預覽（PDF / 圖片）由前端依 MIME 內嵌、Office 僅下載。
- **Alternatives**: 多附件（否決，spec Clarify）；DB BLOB（否決，效能 / 備份成本）。

## §4 文件狀態機與送審週期持久化

- **Decision**: `DM_DOCUMENT.STATUS`（文件層）+ `DM_DOC_VERSION.STATUS`（版本層）共同表達狀態機；**一次送審週期以一列 `DM_REVIEW` 表示**（含類型 新增 / 新版本 / 廢止、指定審核者、核准者、送審 / 完成時間、狀態、退回 / 廢止原因）。
- **Rationale**: 三類送審（新增 / 新版本 / 廢止）共用單一週期模型；撤回重送以新列記錄，原列保留不被改寫（spec：原指定審核者紀錄保留）。
- **狀態值**: 新增 / 新版本 DRAFT → PENDING_REVIEW → PUBLISHED / REJECTED；廢止 PUBLISHED → PENDING_OBSOLETE → OBSOLETE / 回 PUBLISHED。
- **約束**: 同一文件不可同時兩種送審 → 應用層檢核「該文件無其他 PENDING_* 之 DM_REVIEW」。

## §5 func_name 唯一性（線上操作手冊檢索）

- **Decision**: 「同一 func_name 至多對應一份**已發布**系統操作手冊」以**部分唯一索引**（partial unique index：`func_name` where 分類=系統操作手冊 AND 狀態=已發布）+ 應用層送審 / 發布前檢核共同保障；草稿 / 已廢止不佔用。
- **Rationale**: DM01 依作業項目（func_name）檢索須得唯一手冊（spec Clarify）；DB 約束防並發競態，應用層檢核給友善訊息（DM-MSG-DM03-003）。
- **Alternatives**: 僅應用層檢核（並發下可能雙發布）；同一 func_name 多份手冊清單（否決，UX 歧義）。
- **2026-06-26 變更**: 原「主系統按 func_name 跨系統反查」鏈路已移除；唯一性約束保留，理由改為 DM 內部檢索之唯一性。

## §6 核准發布 / 廢止之原子性

- **Decision**: 核准並發布於**單一交易**內完成：新版本 STATUS→PUBLISHED、舊目前版本標記已被取代、`DM_DOCUMENT.CURRENT_VERSION_ID` 更新、`DM_REVIEW` 完成、寫入 `DM_CHANGE_LOG`、發通知。核准並廢止同理（文件 STATUS→OBSOLETE、寫 DM_CHANGE_LOG、版本歷程末尾廢止紀錄）。
- **Rationale**: 避免「半發布」狀態（如已切換 CURRENT 但未寫歷程）；核准者 USER_ID 自 Session 取得、不可覆寫。

## §7 永久保留與不可竄改（版本 / 變更歷程 / 角色異動）

- **Decision**: 所有版本（`DM_DOC_VERSION`）以軟刪除永久保留（DELETED=0、不實體刪除）；`DM_CHANGE_LOG`（公開發布 / 廢止）與 `DM_USER_ROLE_LOG`（角色異動）為 **append-only**、永久保留、不提供修改 / 刪除。
- **Rationale**: spec Clarify「永久保留」；「至少 1 年」為法規下限，永久保留自然滿足。角色異動之完整歷史寫入 `DM_USER_ROLE_LOG`，但**不提供 DM 查詢 UI**（僅 DM09 顯示「最後異動」欄、完整歷史供 IT / 稽核由 DB 查）。
- **Alternatives**: 滿 1 年清除（否決，spec Clarify）。

## §8 SSO 與共用 user table

- **Decision**: `USER` 為 DM 與 ET **共用**之 user table（USER_ID 穩定識別碼、帳號 Email、密碼雜湊、姓名）；DM 僅管理自己之角色（`DM_USER_ROLE`），ET 角色獨立。
- **Rationale**: spec：註冊一次登兩系統、角色不共用。DM 不持有 USER 之獨佔權；帳號 / 密碼 / 姓名變更於兩系統同步生效。
- **Alternatives**: DM 自建帳號（否決，與 ET 重複、違 SSO 設計）。

## §9 通知與自動催辦

- **Decision**: 工作流通知經 **Email Server（SMTP）+ 站內訊息**；**自動催辦僅站內訊息**。催辦以**每日排程作業**掃描 `DM_REVIEW` 中停留 ≥ 催辦門檻天數（`DM_PARAM`，預設 7、可調 1–30）之 PENDING_* 項目，每日發一次直到處理完。
- **Rationale**: spec 通知範本 7 事件 + 催辦規則；催辦不發 Email 避免每日打擾。
- **Alternatives**: 即時 push（不需要，門檻為日粒度）。

## §10 預覽 / 下載

- **Decision**: 前端依 MIME / 副檔名判定：**PDF、圖片**內嵌瀏覽器預覽；**Office（Word / Excel / PPT）**不預覽、僅下載。僅目前發布版本可下載；舊版本僅預覽。
- **Rationale**: spec Clarify 預覽規則；瀏覽器原生支援 PDF / 圖片，Office 需轉檔不納入。
- **Alternatives**: 整合 Office Online viewer（超範圍，否決）。

---

## 待 plan / 實作補充（非阻擋）

- 各表數量 / 長度上限（文件名稱、變更摘要、廢止原因字數等）於 data-model.md 與實作定案
- 檔案儲存實體位置（檔案系統路徑 / 物件儲存）由部署決定
- 版本號輸入驗證（新版號需 > 現行、不可重複）於 [spec_us5.md](spec_us5.md) / 實作定案
