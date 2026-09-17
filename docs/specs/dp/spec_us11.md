# User Story 11 — 排程作業執行與總覽（UCDP008）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P2 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-schedule，唯讀總覽）

## User Story

作為平台（系統自動），我要依 `DP_SCHEDULE` 註冊表以單一引擎觸發各模組與平台自身的排程 job 並記錄執行歷程；作為 ET / DM 管理者，我要於 DP 後台唯讀檢視排程總覽，以便掌握各 job 的執行狀態。

**Priority**: P2 — 承載 ET 週報 / 提醒（SCHET001 / 002）、DM KPI 週報（SCHDM001）與平台自身 `SCHDP001`；各模組排程功能上線前完成即可。

**Independent Test**: 註冊之 job 依 cron 準時觸發且 `DP_SCHEDULE_LOG` 留起訖與結果；單一 job 失敗不影響其他 job；前次未完成時本次跳過；管理者於總覽頁只能檢視、無啟停 / 補跑按鈕。

### Acceptance Scenarios

1. **Given** job 已於 `DP_SCHEDULE` 登錄（`JOB_ID`、cron、執行程式參照、啟用中），**When** cron 到期，**Then** 平台引擎（APScheduler）觸發該 job；多實例部署時僅 leader 實例觸發一次
2. **Given** job 執行，**When** 需要業務資料，**Then** job handler（由所屬模組提供）反向 import 模組 service 取得；執行起訖時間與成功結果寫入 `DP_SCHEDULE_LOG`
3. **Given** job 執行失敗，**When** 引擎捕捉例外，**Then** `DP_SCHEDULE_LOG` 記錄失敗與錯誤訊息；**不影響其他 job**；補跑由各模組視需要處理
4. **Given** 前次執行尚未完成，**When** 下次 cron 到期，**Then** 跳過本次並記錄（不重複執行同一 job）
5. **Given** job 於 `DP_SCHEDULE` 為停用狀態，**When** cron 到期，**Then** 不觸發
6. **Given** 平台自身排程 `SCHDP001`（每日）執行，**When** 檢核全部帳號，**Then** ① 連續 90 日未登入之帳號自動禁用並寫稽核（`LAST_LOGIN_DATE` 逾 `IDLE_DISABLE_DAYS`；**null＝從未登入則以 `CREATED_DATE` 為基準**）；② 密碼將於 N 天內到期（預設 7 天）之使用者經發信服務（US6）寄「密碼到期提醒」（`MODULE=DP` 範本）；提醒於到期前每日跑均寄出（達成前每日提醒，非單次）
7. **Given** ET 或 DM 管理者進入排程總覽頁（共用項），**When** 頁面載入，**Then** 列出各 job（`JOB_ID` / 說明 / cron / 狀態〔啟用停用〕/ 上次執行時間 / **下次執行時間** / 執行歷程）；**可編輯 `JOB_NAME` / `CRON_EXPR` / 啟停**（cron 即時生效）；**MUST NOT 提供手動補跑；`HANDLER_REF` / `MODULE` / `JOB_ID` 不可改**；無紀錄時顯示空狀態（DP-MSG-DP10-001）

## Functional Requirements

- **FR-DP-US11-01**: 平台 MUST 提供單一排程執行引擎（APScheduler）＋ `DP_SCHEDULE` 註冊表（`JOB_ID`、cron、執行程式參照、啟停、上次執行時間 / 結果）；各模組 job 與平台自身 job MUST 於此登錄
- **FR-DP-US11-02**: 多實例部署時 MUST 以 leader 選舉確保只有一個實例觸發（單一實例部署可簡化）
- **FR-DP-US11-03**: 每次執行 MUST 於 `DP_SCHEDULE_LOG` 記錄起訖時間、成功 / 失敗、錯誤訊息（append-only）；單一 job 失敗 MUST NOT 影響其他 job；前次未完成時 MUST 跳過本次並記錄
- **FR-DP-US11-04**: job handler 由所屬模組提供並向引擎註冊；需要業務資料時反向 import 模組 service（平台 job → 模組 service）
- **FR-DP-US11-05**: 平台自身排程 `SCHDP001`（每日）MUST 執行：① 閒置帳號禁用（`ACTIVE` 帳號 `LAST_LOGIN_DATE` 逾 `IDLE_DISABLE_DAYS`，天數為平台級參數；**`LAST_LOGIN_DATE` 為 null〔從未登入〕時以 `CREATED_DATE` 為閒置起算基準**；禁用寫稽核 `func_name=DP-USERS`、operator=SYSTEM）；② 密碼效期到期前提醒（`PWD_CHANGED_DATE`+`EXPIRY_DAYS` 距今 ≤ `EXPIRY_REMIND_DAYS`，預設到期前 7 天起、**每日跑均寄出直至變更 / 到期**，經 US6 寄 `MODULE=DP`「密碼到期提醒」）；兩者結果寫入稽核 / outbox，各批次逐筆容錯（單一使用者失敗不擋其他）
- **FR-DP-US11-06**: DP 後台 MUST 提供排程總覽畫面（共用項，ET / DM 管理者皆可檢視）：job 清單（含下次執行時間）與執行歷程；**MAY 編輯 `JOB_NAME` / `CRON_EXPR` / 啟停（`IS_ENABLED`）**，`CRON_EXPR` / `IS_ENABLED` 變更即時套到運行中的引擎；**MUST NOT 提供手動補跑**（補跑各模組自理，FR-03）；**`HANDLER_REF` / `MODULE` / `JOB_ID` MUST NOT 可經 UI 修改**（`HANDLER_REF` 改＝任意程式執行風險）
- **FR-DP-US11-08**: job 清單 MUST 顯示 `DESCRIPTION`（這支 job 在做什麼）；該欄 **MUST NOT 可經 UI 修改**——它描述的是程式行為，管理者改了不會改變行為、只會讓說明與實作不符，變更途徑為 IT 直接操作 DB。`JOB_NAME` 為短名詞，工作內容細節一律寫入 `DESCRIPTION`（#311）
- **FR-DP-US11-07**（2026-09-17 由 #332 改訂）: 排程之**執行時點**唯一由 `DP_SCHEDULE.CRON_EXPR` 控制（於 DP 後台「排程管理」編輯，經 `apply_job_change` **即時生效**，見 FR-06）；引擎 MUST NOT 自 `DP_PARAM` 讀取任何排程時點。`DP_PARAM`（前綴分模組）用於各模組的**業務門檻**參數（如 `DM_REMIND_THRESHOLD` 簽核停留天數、`ET_URGENT_REMIND_DAYS` 截止前天數），由各模組管理者於 US5 維護、**各模組 handler 於執行時自行讀取**
    > **改訂理由**：原條文寫「排程時間等業務參數存 `DP_PARAM`…引擎 MUST 於觸發時讀取最新值」，而**那條 MUST 從未被實作**——`app/dp/schedules/scheduler.py` 只以 `CronTrigger.from_crontab(job.cron_expr, ...)` 註冊，完全不讀 `DP_PARAM`。
    >
    > 後果不是「功能缺了」，而是**管理者在 DP 後台改那個參數會完全沒有效果且無任何錯誤訊息**——與 #171（參數缺維護層級）、#307（通知 CHANNEL 改了靜默失效）同族。
    >
    > 收斂方向選「改規格配合實作」而非反過來，理由是**能改時間的地方與被讀的地方必須合一**：排程管理頁本來就有 UI、有權限（`require_any_module_admin()`，與參數頁同一道閘）、有稽核，且變更即時生效不必重啟。
    >
    > 兩個曾被本條點名的參數皆已移除：`ET_WEEKLY_STAT_DAY_TIME`（#325 / `d5a81f37c6b2`）、`DM_WEEKLY_SCHED_DAY_TIME`（#332 / `a3f7c21e58d9`）。

- **FR-DP-US11-07a**（2026-09-17 新增，#332）: 排程總覽 MUST 顯示「執行時點」欄，其值由 `CRON_EXPR` **現算**並標示 `UTC`；`DESCRIPTION` MUST NOT 承載執行時點，只描述該 job 的職責
    > **為何不讓說明欄寫時點**：`DESCRIPTION` 與 `CRON_EXPR` 在同一個畫面上，但只有後者可編輯、兩者無同步機制。這不是假設性風險——`SCHDM001` 的 cron 於 `9eb4dd6e496b` 改為 10:00，12 天後回填說明欄的 `b3f7c2e8a591` 抄的仍是舊的 08:00，畫面上那行字自此為假。
    >
    > **為何標 UTC 而非換算本地時間**：引擎以 `timezone="UTC"` 註冊，管理者在同一頁編輯的也是 UTC 運算式。若顯示時偷偷換成本地時間，會出現「編輯框寫 10、旁邊顯示 18:00」的矛盾。本地時刻由「下次執行」欄承擔（該欄本就是本地時區）。
    >
    > ⚠️ **day-of-week 以週一為 0**（`0=週一` … `6=週日`），非標準 crontab 的週日為 0；`7` 會被直接拒絕。`SCHDM001` / `SCHET001` 原寫 `0 10 * * 1` 而實際跑在**週二**，已由 `c8b4e2f1d97a` 更正為 `0 10 * * 0`。語意由 `tests/unit/dp/test_dp_schedule_cron_weekday.py` 釘住。

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-DP10-001 | 提示 | 尚無排程執行紀錄 | FR-DP-US11-06 空狀態 |

> 排程執行本身無使用者介面訊息；執行結果以 `DP_SCHEDULE_LOG` 與應用層 log 表達。

## 前置依賴

- 各模組 job handler：ET SCHET001 / 002、DM SCHDM001（跨模組，由 ET / DM 提供）
- `SCHDP001` 之提醒信經發信服務（US6）與 `MODULE=DP`「密碼到期提醒」範本（US9）
- 排程時間 / 閒置天數 / 提醒天數等參數（US5）
- 總覽頁操作者具 ET 或 DM 管理者角色並已登入（US1 / US7）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §排程基礎建設
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP008
- 模組端排程語意：[../dm/spec_us13.md](../dm/spec_us13.md)（SCHDM001）、ET 週報 / 提醒（../et/）
- 共用規則：[spec.md](spec.md) §排程引擎
