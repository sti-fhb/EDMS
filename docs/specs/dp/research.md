# 研究決策：平台模組（Platform）

**日期**: 2026-07-09
**規格**: [spec.md](spec.md) | **計畫**: [plan.md](plan.md)
**資料庫**: PostgreSQL（命名 / 型別遵循 CLAUDE.md）

> 本檔記錄 DP 設計階段之關鍵技術決策（Decision / Rationale / Alternatives）。多數承自 spec.md 三輪 Clarifications 與 `_refs/09-平台模組.md` 兩次決策紀錄，部分為 plan 階段定案。

---

## §1 遷移起手包之裁剪（對照 [EDMS-MIGRATION.md](../../../EDMS-MIGRATION.md) §4）

- **Decision**: 認證起手包自 TBMS 複製後，除既定之「砍 MFA」外，**再裁剪以下項目**以對齊 spec（2026-07-06 / 07-08 決策晚於遷移清單 2026-07-03）：
  | 起手包項目 | 處置 | 依據 |
  |-----------|------|------|
  | `DP_SESSION`（Refresh Token / Token Rotation / 單一登入踢出）| ❌ 不帶——無伺服器端 session，改「短 TTL + 活動換發」（§2）| spec 釐清第 1 輪 Q3 |
  | `app/dp/roles/`、`app/dp/menus/`（全域 RBAC）、`core/permission.py` 之選單權限 | ❌ 不帶——平台不做全域 RBAC，角色能力 / 判定留模組 | 2026-07-06 決策 |
  | `confirm_account` / TOKEN_TYPE `ACCOUNT_CONFIRM`、`account_activation.py` | ❌ 不帶——自助註冊即用、代建亦直接可用，無開通信 | 2026-07-06 決策 |
  | `DP_USER.EMAIL` 之 `EncryptedString`（AES-256-GCM）| ❌ 不用——Email / 姓名屬一般個資、不加密儲存（`core/encryption.py` 仍帶入備用）| spec Assumptions |
  | `refresh_token` 端點 | ✂ 改為 `renew` 換發端點（驗現行 token + `auth_time` 上限，§2）| spec 釐清第 1 輪 Q3 |
  | `IS_PLATFORM_ADMIN` 等平台管理員概念 | ❌ 不帶——DP 後台由 ET / DM 管理者進入 | 2026-07-08 決策 |
- **Rationale**: 遷移清單以「照抄可用」為目標，spec 隨後拍板之簡化（簡單 JWT、無 RBAC、共管後台）使部分起手包項目失效；於此一次載明避免實作時照清單誤帶。
- **保留項**: `core/db.py` / `base_model.py` / `pagination.py` / `exceptions.py`、`auth.py`（decode_jwt 等，改造 payload）、`request_context.py`、`operator.py`、`password_policy.py`、寄信基礎（`fastapi-mail`）、Alembic 骨架與測試 DB 骨架——依 EDMS-MIGRATION §3 / §4 帶入。

## §2 閒置自動登出：短 TTL + 活動換發（無 Refresh Token）

- **Decision**: JWT payload 含 `auth_time`（本次登入時間）與標準 `exp`（簽發時間 + 閒置逾時，預設 15 分鐘）。前端於 token 將到期且使用者有操作時呼叫 `renew` 端點：驗證**現行 token 仍有效** + `now − auth_time < 單日換發上限（預設 8 小時）` + 帳號狀態正常，簽發新 token（沿用原 `auth_time`）。停止操作逾 15 分鐘 → token 自然過期；換發逾 8 小時上限 → 拒絕，需重新登入。
- **Rationale**: 完全無狀態（無 session 表）即可同時滿足「閒置 ≤ 15 分自動登出」與「單日工作時數上限」；被竊 token 之風險窗縮至 15 分鐘。
- **Alternatives**: (a) 純前端計時丟棄 token（token 實際仍有效 8 小時，資安弱）；(b) 伺服器端記錄最後活動時間（違反「不採伺服器端 session」決策）。均否決（spec 釐清第 1 輪 Q3 採 A 案）。

## §3 帳號停用 / 鎖定之即時失效（無狀態 JWT 下）

- **Decision**: 認證 middleware 於**每請求**依 JWT 之 USER_ID 查 `DP_USER` 狀態（STATUS / LOCKED_UNTIL / DELETED），停用或鎖定即拒絕（401/403）。不做行程內快取。
- **Rationale**: spec SC-006 要求停用「下次請求即拒絕」兩端同步失效；`DP_USER` 單鍵查詢成本低（PK 索引），EDMS 規模（單一組織）無快取必要，避免快取失效窗。
- **Alternatives**: JWT 黑名單表（等同 session，否決）；短 TTL 自然失效（最長 15 分鐘延遲，不滿足「下次請求即拒絕」）。

## §4 角色與模組過濾之判定來源（JWT 不含角色）

- **Decision**: JWT **不放角色 claim**。DP 後台端點於每請求呼叫模組 service `is_module_admin(user_id)`（ET / DM 各自提供）判定操作者之管理者身分，據以決定共用項存取與模組項過濾（`ET_` / `DM_` 前綴、`MODULE` 值）；過濾一律於伺服器端 enforce。
- **Rationale**: 角色指派「即時生效」（spec US7），token 內角色會有最長 15 分鐘過期延遲；角色資料在模組表（`ET_USER_ROLE` / `DM_USER_ROLE`），由模組判定符合「判定留模組」邊界（`sti-backend-boundaries` API-First 隔離）。
- **Alternatives**: 角色進 JWT（否決，即時性）；DP 直讀模組角色表（否決，違反模組邊界）。

## §5 一次性 token 之儲存與 TOKEN_TYPE 擴充

- **Decision**: `DP_PWD_RESET` 存 token 之 **SHA-256 雜湊**（非明文，信中連結才有明文）；`TOKEN_TYPE` 取值 `PWD_RESET`（忘記密碼）與 **`EMAIL_CHANGE`**（帳號 Email 變更驗證，`NEW_EMAIL` 欄記待生效信箱）。同一使用者同一類型重新申請時，舊未用 token 一律作廢（USED_DATE 標記）。
- **Rationale**: US8 Email 變更需一次性時效驗證 token，與密碼重設同模式，共用一張表最精簡；DB 洩漏時雜湊 token 不可反打。spec Key Entities 原寫「現僅 PWD_RESET」，本計畫依 US8 需求擴充為兩型（無 `ACCOUNT_CONFIRM`，見 §1）。
- **Alternatives**: token 存 `DP_USER` 欄位（一人同時僅一 token、查詢彆扭）；JWT self-contained token（無法單次作廢）。均否決。

## §6 稽核日誌：TEXT 存 JSON、append-only 落地、完整性雜湊

- **Decision**: `DP_AUDIT_LOG` 之異動前後值以 **TEXT 欄存 JSON 字串**（`BEFORE_VALUE` / `AFTER_VALUE`），不使用 JSONB；append-only 以**應用層（無 UPDATE / DELETE 端點與 repository 方法）+ DB 帳號權限（應用帳號對本表僅 GRANT INSERT / SELECT）**雙重落地；每列寫入 `ROW_HASH`（列內容 + 前列 ROW_HASH 之 SHA-256 鏈式雜湊）供完整性驗證。
- **Rationale**: CLAUDE.md 型別規範限用集合不含 JSONB（DM 亦同此裁定）；查詢介面（US10）僅展示前後值、不做 JSON 條件查詢，TEXT 無效能損失。RQDP「以雜湊等方式確保完整性」以鏈式雜湊落地——竄改任一列即斷鏈可稽。
- **Alternatives**: JSONB（違型別規範，且無查詢需求）；DB trigger 禁改（多一層 DDL 維護，以權限 + 應用層已足）；外部 WORM 儲存（過度設計）。
- **註**: _refs / RQDP 原文之「JSONB」字樣屬分析階段用語，落地型別以本節為準。

## §7 DP_PARAM 二層模型與唯讀查詢服務

- **Decision**: `DP_PARAM_M`（PARAM_ID、名稱、型態 VALUE / LIST、`DETAIL_LOCK`）+ `DP_PARAM_D`（PARAM_ID + PARAM_KEY、值、排序、啟停）。單值參數＝一筆 D（固定 PARAM_KEY，如 `VALUE`）；清單＝多筆 D。歸屬以 `PARAM_ID` 前綴判定（無前綴＝平台級、`ET_` / `DM_`＝模組級）。唯讀查詢服務 `get_param_values(param_id, key?)` **不快取、每次讀 DB**。
- **Rationale**: 對齊 TBMS `DP_PARAM_M/D` 慣例與 `_refs/09` §2.6；「儲存即生效」（spec SC-008 即時反映）——參數讀取頻率低（表單載入 / 業務檢核時），無快取必要，避免多實例快取一致性問題。`DETAIL_LOCK` 於 M 層宣告該參數之明細碼（PARAM_KEY）建立後不可改。
- **Alternatives**: 單表 KV（清單型與鎖定語意難表達）；行程內 TTL 快取（即時生效要求下增加複雜度）。均否決。
- **「全體」等特殊清單項**: 以**固定 PARAM_KEY 慣例**（如 `ALL`）辨識，不另設欄位；`IS_ALL` 展開等語意歸模組（定義 vs 關聯分層）。

## §8 發信引擎：outbox + 常駐 worker、渲染快照

- **Decision**: `send_email()` 於呼叫方交易外（或後）渲染範本並**逐收件人**寫入 `DP_EMAIL_LOG`（含渲染後 SUBJECT / BODY 快照、CALLER_MODULE、狀態 PENDING）後即返回。**常駐背景 worker**（FastAPI lifespan 啟動之 asyncio task，非排程 job）輪詢 PENDING，依平台級 `MAIL` 參數（每分鐘速率、重試上限、重試間隔）經 SMTP 寄送，更新 SENT / FAILED 與重試軌跡。
- **Rationale**: spec US6 非同步不阻塞（DM「全體」發布通知可達千人）；快照確保「寄出內容」可稽——範本事後修改不影響已排隊信件；逐收件人一列使單筆失敗獨立重試（FR-DP-US6-06）。
- **Alternatives**: Celery / 外部 MQ（EDMS 單體規模過度設計）；寄送時才渲染（範本異動使佇列內容漂移，且失敗重試需重讀範本）。均否決。
- **告警**: 不做系統內通報（spec 釐清第 2 輪 Q1）；FAILED 率由 IT 以 log / 監控工具追蹤。

## §9 排程引擎：APScheduler + DB 註冊表 + leader

- **Decision**: 平台以 APScheduler（AsyncIOScheduler）為執行引擎，啟動時自 `DP_SCHEDULE` 載入啟用中 job（cron + `HANDLER_REF` 動態 import 各模組 handler）；`max_instances=1` + coalesce 落實「前次未完成跳過本次」，跳過亦寫 `DP_SCHEDULE_LOG`（SKIPPED）。多實例部署沿用 TBMS `core/scheduler_leader.py` 之 leader 選舉（EDMS 預設單一實例可直接執行）。
- **Rationale**: `_refs/09` §2.10 既定方案；DB 註冊表使 job 清單 / 啟停可查可稽（US11 總覽唯讀讀此表 + log 表）；handler 反向 import 模組 service 符合「平台引擎、業務歸模組」。
- **平台自身 job `SCHDP001`（每日）**: 掃 `DP_USER`——① `LAST_LOGIN_DATE` 逾 90 日（參數）→ 停用 + 稽核；② `PWD_CHANGED_DATE` 距效期不足提醒天數（預設 7）→ 經發信服務寄「密碼到期提醒」（`MODULE=DP`）。
- **Alternatives**: 各模組自跑排程（多引擎多觸發點，已於 2026-07-08 集中化決策否決）；Celery beat（同 §8 理由否決）。

## §10 速率限制（防自動化程式）

- **Decision**: 於登入 / 忘記密碼 / 密碼變更端點以**行程內記憶體滑動視窗**（`slowapi` 或等效自製 middleware）按「來源 IP + 帳號」限流；門檻於 plan 階段預設（如 10 次 / 分鐘），超限回 429。不採 CAPTCHA。
- **Rationale**: spec 釐清第 2 輪 Q3；EDMS 預設單一實例，行程內計數即足，避免引入 Redis。帳號鎖定（5 次錯誤）為第二層防線。
- **Alternatives**: Redis 集中限流（多實例才需要，屆時再演進）；CAPTCHA（內部系統易用性，否決）。

## §11 密碼策略之落地

- **Decision**: 雜湊採 **bcrypt**（`passlib`，起手包 `password_policy.py` 沿用改參）；複雜度（一般 8 / 特權 12 字元、≥3 種字元組合）與歷史次數（3）、效期（90 日）皆讀平台級 `PWD_POLICY` 參數。特權門檻於**變更密碼當下**依 `is_module_admin()` 判定（§4）。`DP_PWD_HIST` 於每次密碼設定（註冊 / 重設 / 變更 / 代建）追加一列，檢核時取最近 N 列比對 bcrypt。
- **Rationale**: spec §密碼策略與帳號安全；bcrypt 為業界標準且起手包既有。
- **Alternatives**: argon2（更新但引入新依賴，起手包 bcrypt 已足）。

## §12 模組入口頁與登入後導向

- **Decision**: 登入端點支援 `redirect`（原目標頁面路徑）參數：有值且屬白名單（ET / DM 路徑）→ 登入成功後前端導回；無值 → 前端路由至模組入口頁。redirect 觸發情境：① 通知信連結未登入點擊、② **閒置 15 分逾時重新登入（最頻繁）**、③ 書籤 / 直接輸入模組網址。入口頁載入時呼叫「我的模組角色摘要」端點（DP 聚合 ET / DM `is_module_admin` / `has_any_role`）決定 DM 卡狀態。
- **Rationale**: spec 釐清第 1 / 2 / 4 輪：入口頁 ET 恆顯、不顯後台入口；redirect 白名單防 open redirect；短 TTL（15 分）使逾時重登頻繁，返回原頁面為必要 UX。
- **2026-07-09（釐清第 4 輪）**: DM 卡由「依角色顯示 / 隱藏」改為**恆顯示雙狀態**——無任何 DM 角色者呈「未開通」鎖定卡（引導洽單位主管 / 管理者、點擊不進入），兼顧機密性（只揭露模組存在）與主管級使用者之可發現性；首次登入顯示歡迎橫幅一次。模組側欄可見性（DM 組未開通隱藏、後台組僅管理者）由各模組 enforce——引導歸入口頁、側欄保持乾淨。**開通申請流程**（申請單 / 通知按鈕）評估後列 backlog：內部系統線下開通成本低，v1 不做系統閉環。
- **Alternatives**: (a) 註冊時勾選要用的模組（否決——勾了仍需等管理者開通，徒增欄位）；(b) 開通申請流程 v1 即做（否決——複雜度不符效益，留 backlog）；(c) DM 卡未開通完全隱藏（否決——主管級使用者無從發現 DM 存在，第 3 輪原案）。
