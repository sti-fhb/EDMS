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
- **append-only 事件表之標準欄位（2026-06-29 補充）**：`DM_CHANGE_LOG` / `DM_USER_ROLE_LOG` / `DM_DOC_READ` 屬只新增、不改不刪之事件紀錄，**省略 `UPDATED_*` / `DELETED`**。其中 **`DM_DOC_READ`**（下載即建立一列）之「下載者 / 下載時間」即標準 `CREATED_USER` / `CREATED_DATE`，故**不另設 `USER_ID` / `READ_TIME`**（避免同值重複欄位）；KPI 已看以 `CREATED_USER`（＝下載者）判定。

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

## §5b 標籤式可見性（閱覽者存取控制）— 2026-06-29 客戶會議

- **Decision**: 新增專用標籤組 `AUDIENCE`（可見對象/單位，權限），與檢索標籤組（MODULE / NATURE / LEGAL）分離；文件端必填≥1（含通用值「全體」），閱覽者端由 `DM_USER_TAG` 授權。閱覽者可見某文件 ⇔ 文件掛「全體」 **OR**（文件 AUDIENCE 標籤 ∩ 使用者 `DM_USER_TAG` ≠ 空）。可見性僅作用於閱覽者；編輯者 / 審核者 / 管理者可見全部。原檢索組 `ROLE`（適用角色）移除。
- **Rationale**: 若逕用既有檢索標籤（尤其全 4 組 OR 平比）當權限，會造成「改標籤＝改權限」之耦合、語意不通（如「衛福部」不宜當授權）、過度授權與不可預期。專用 AUDIENCE 組令**權限與檢索解耦**：改檢索標籤不影響可見性、改可見對象不污染搜尋。OR 比對貼近「賦予對象即可看」之直覺；「全體」值免去逐一列舉。
- **soft-retire**: AUDIENCE 值之停用**不收回**既有文件 / 授權之可見性，僅停止後續指派、並提示受影響數（避免權限大範圍抽離）；不開放刪除。
- **Alternatives**: (a) 沿用檢索標籤當權限（否決，耦合與語意問題）；(b) 單一維度（如僅「適用角色」）當可見性（否決，客戶要單位/群組彈性，另立專組更清晰）；(c) AND 比對（否決，難表達「賦予即可看」、易漏授權）。
- **效能**: DM01 查詢對閱覽者加入可見性過濾（EXISTS 子查詢比對 `DM_DOC_TAG`×`DM_USER_TAG` 之 AUDIENCE 交集，或含「全體」）；索引見 data-model。
- **與 ET 對齊、無「部門」資料源（2026-07-02）**: DM 的 `DM_TAG(AUDIENCE)` / `DM_USER_TAG` 對應 ET 的 `ET_TAG（受訓單位標籤）` / `ET_USER_TAG`，種子值一致（全體 / 護理師 / 軍人 / 醫檢師 / 行政人員）、皆管理者維護；惟兩系統**各自持有、不共用**（使用者群相交而不相同，per ET 2026-07-02 決策）。DM09 權限管理原「部門」欄**無外部資料來源**（DM 不介接主系統 HR / 組織資料），移除；使用者所屬「單位」改由管理者於 DM09 以「可見對象/單位」授權設定（＝ `DM_USER_TAG`）。

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
- **Rationale**: spec 通知範本事件 + 催辦規則；催辦不發 Email 避免每日打擾。
- **Alternatives**: 即時 push（不需要，門檻為日粒度）。

## §9b 文件發布通知（撰寫者 + 相符閱覽者，2026-06-29 客戶會議）

- **Decision**: 文件**核准並發布**（新增首版 / 新版本，**廢止不含**）時，以**單一「文件發布通知」（`DOC_PUBLISH`，CHANNEL=EMAIL_ONLY）**非同步 **Email** 通知**撰寫者 + 發布當下可見對象相符之閱覽者**——文件掛「全體」則所有閱覽者、否則可見對象 ∩ 閱覽者授權 ≠ 空（OR，per §5b）；只要具閱覽者角色且可見對象相符即通知（不排除兼具編輯 / 審核者）。
- **合併決策（2026-06-29 後續）**: 原「文件發布（撰寫者，EMAIL_MSG）」與「發布通知閱覽者（EMAIL_ONLY）」**合併為單一 `DOC_PUBLISH`**，收件對象＝撰寫者 + 相符閱覽者、**僅 Email、非同步**；撰寫者原站內發布通知取消（改由 US9「我的文件動態」呈現，避免同事件雙管道 / 雙範本）。通知範本由 10 → **9**。
- **非同步 outbox**: 核准發布交易僅將收件人（快照）逐筆寫入 `DM_NOTIFY_QUEUE`（PENDING），由背景 worker 批次寄送、標記 SENT / FAILED 可重試。理由：一次發布（尤其「全體」）可能通知上千人，同步寄信會拖慢甚至回滾核准交易；outbox 使寄送與交易解耦、失敗不遺漏。
- **快照名單**: 收件人於發布當下依可見對象計算並定住；事後新授權之閱覽者不補寄（由 §KPI 每週未讀提醒補足）。
- **「全體」照實全寄**: 客戶確認掛「全體」之文件即逐一 Email 所有閱覽者（不設群發信箱 / 不設上限）。
- **Rationale**: 客戶需求「新版本 / 新上傳文件時通知對應閱覽者」；閱覽者無站內文件動態功能故僅 Email。
- **Alternatives**: (a) 同步寄送（否決，阻塞交易 / 大量收件風險）；(b)「全體」改公告或群發信箱（否決，客戶要求照實寄）；(c) Email + 站內（否決，閱覽者無站內動態）。

## §9c 閱讀統計與 KPI（2026-06-29 客戶會議）

- **已看認定 = 下載**: 使用者下載「目前發布版」記一筆 `DM_DOC_READ`，唯一約束 (DOC_ID, VERSION_ID, CREATED_USER) 以人去重（下載者/時間即標準 CREATED_USER/CREATED_DATE，見 §1）；**預覽不記**。理由：下載代表實際取用，較「開啟預覽」明確可稽核。
- **應看（分母）= 可見對象名單**: 沿用 §5b 可見性（掛「全體」→全部閱覽者、否則 OR 交集），**不排除**兼編輯/審核/管理者（與發布通知一致）。KPI 已看＝分母 ∩ 目前發布版之 `DM_DOC_READ` distinct CREATED_USER。
- **版本重置**: KPI 綁「目前發布版（CURRENT_VERSION_ID）」；發新版→VERSION_ID 改變→已看自然歸零（要大家重看新版）。
- **範圍 = 全部已發布文件**: KPI 統計 / 儀表板（DM10）/ 管理者週報 / **未讀提醒**均涵蓋全部已發布文件。未讀提醒是否寄送**由管理者於 DM09 通知範本「未讀提醒」啟用 / 停用統一控制**（比照 ET）；**不設文件層個別開關**（2026-07-02 移除原 `WEEKLY_REMIND_VIEWER` 旗標——避免逐文件維護負擔，統一開關更單純）。
- **排程 SCHDM001（每週執行，星期＋時間可設定，預設週一 10:00）**: 一個作業算 KPI→寄管理者週報（Email，內文摘要 + CSV）→寄未看閱覽者提醒（Email，一人一信彙整）；寄信沿用 `DM_NOTIFY_QUEUE` outbox 非同步，不阻塞排程。新增 `KPI_WEEKLY` / `UNREAD_REMIND` 兩事件（EMAIL_ONLY）。**每週執行時間**（星期＋時間）由管理者於 DM09 通知範本（KPI 週報 / 未讀提醒）設定、存於 `DM_PARAM.DM_WEEKLY_SCHED_DAY_TIME`（格式 `星期,HH:MM`，預設 `週一,10:00`），KPI 週報與未讀提醒共用同一時間同批執行（對齊 ET `ET_PARAM.WEEKLY_STAT_DAY_TIME` 設計）。
- **Rationale**: 客戶要「已看/未看 KPI + 每週回報 + 催未看」；分母不排除、範圍全部為客戶 2026-06-29 決定；未讀提醒之開關由管理者以範本統一控制（2026-07-02 客戶變更，取代原文件層旗標）。
- **Alternatives**: (a) 預覽也算已看（否決，難認定實際閱讀）；(b) 文件層「每週未看提醒」旗標逐一控制（2026-06-29 曾採，2026-07-02 移除——逐文件維護負擔大，改由管理者以範本統一開關）；(c) 同步寄信（否決，大量收件阻塞，沿用 outbox）。
- **應看＝0 之處理**：文件掛了可見對象但無任何閱覽者被授予該對象時，應看＝0。DM10 顯示「—（無對應閱覽者）」、**不列入整體平均閱讀率**計算；週報 CSV 照列但百分比欄標「—」。
- **佇列不存內容快照**（2026-06-29，per SA 決定）：`DM_NOTIFY_QUEUE` 僅存 `TEMPLATE_CODE` + `RECIPIENT_USER_ID`（+ 發布通知之 DOC_ID），背景 worker **寄送時即時組信**（未讀提醒即時算該人未看清單、KPI 週報即時算統計 + CSV）。取捨：寄送時點與排程時點之未看數字可能微幅差異，可接受（更即時）；`DOC_ID` / `VERSION_ID` 改為可空（僅發布通知填）。

## §9d 批量寄信之韌性（outbox 重試 / 限流 / 告警，2026-06-29）

- **Decision**: `DM_NOTIFY_QUEUE` 背景 worker（T018a）採：① **最大重試 `DM_MAIL_MAX_RETRY`（預設 5）**，超過標 `FAILED` 不再自動重試；② **指數退避**（約 1 / 2 / 4 / 8 / 16 分）；③ **批次限流 `DM_MAIL_RATE_PER_MIN`（預設 60 封/分，依 SMTP 主機上限調）**；④ **失敗告警 `DM_MAIL_FAIL_ALERT_PCT`（預設 20%）**——單次排程完成後 FAILED 比率超標即以系統內訊息 + Email 通知管理者 / IT。門檻均為 `DM_PARAM`、可調。
- **Rationale**: 一次排程（尤其「全體」發布 / 全院未讀提醒）可能上千封，SMTP 主機有速率上限、暫時性錯誤（限流 / 逾時）在所難免；限流 + 退避重試 + 狀態欄使「部分失敗不遺漏、不重複寄」；失敗告警避免「以為都寄出其實沒有」。
- **Alternatives**: (a) 無限重試（否決，堆積 / 資源浪費）；(b) 無限流一次灌爆（否決，被主機限流 / IP 信譽下降判垃圾信）。
- **部署層**：寄件網域須設 SPF / DKIM，避免大量同內容信被判垃圾（屬部署設定，非程式）。

## §10 預覽 / 下載

- **Decision**: 前端依 MIME / 副檔名判定：**PDF、圖片**內嵌瀏覽器預覽；**Office（Word / Excel / PPT）**不預覽、僅下載。僅目前發布版本可下載；舊版本僅預覽。
- **Rationale**: spec Clarify 預覽規則；瀏覽器原生支援 PDF / 圖片，Office 需轉檔不納入。
- **Alternatives**: 整合 Office Online viewer（超範圍，否決）。

---

## 待 plan / 實作補充（非阻擋）

- 各表數量 / 長度上限（文件名稱、變更摘要、廢止原因字數等）於 data-model.md 與實作定案
- 檔案儲存實體位置（檔案系統路徑 / 物件儲存）由部署決定
- 版本號輸入驗證（新版號需 > 現行、不可重複）於 [spec_us5.md](spec_us5.md) / 實作定案
