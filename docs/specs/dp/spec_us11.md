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
6. **Given** 平台自身排程 `SCHDP001`（每日）執行，**When** 檢核全部帳號，**Then** ① 連續 90 日未登入之帳號自動禁用並寫稽核；② 密碼將於 N 天內到期（預設 7 天）之使用者經發信服務（US6）寄「密碼到期提醒」（`MODULE=DP` 範本）
7. **Given** ET 或 DM 管理者進入排程總覽頁（共用項），**When** 頁面載入，**Then** 唯讀列出各 job（`JOB_ID` / 說明 / cron / 啟停狀態 / 上次執行時間與結果）並可展開執行歷程；**無啟停 / 手動補跑操作**（啟停由 DB / 部署管理）；無紀錄時顯示空狀態（DP-MSG-SCHEDULE-001）

## Functional Requirements

- **FR-DP-US11-01**: 平台 MUST 提供單一排程執行引擎（APScheduler）＋ `DP_SCHEDULE` 註冊表（`JOB_ID`、cron、執行程式參照、啟停、上次執行時間 / 結果）；各模組 job 與平台自身 job MUST 於此登錄
- **FR-DP-US11-02**: 多實例部署時 MUST 以 leader 選舉確保只有一個實例觸發（單一實例部署可簡化）
- **FR-DP-US11-03**: 每次執行 MUST 於 `DP_SCHEDULE_LOG` 記錄起訖時間、成功 / 失敗、錯誤訊息（append-only）；單一 job 失敗 MUST NOT 影響其他 job；前次未完成時 MUST 跳過本次並記錄
- **FR-DP-US11-04**: job handler 由所屬模組提供並向引擎註冊；需要業務資料時反向 import 模組 service（平台 job → 模組 service）
- **FR-DP-US11-05**: 平台自身排程 `SCHDP001`（每日）MUST 執行：① 閒置帳號禁用（連續 90 日未登入，天數為平台級參數）；② 密碼效期到期前提醒（預設到期前 7 天起，經 US6 寄 `MODULE=DP`「密碼到期提醒」）；兩者結果寫入稽核 / outbox
- **FR-DP-US11-06**: DP 後台 MUST 提供排程總覽**唯讀**畫面（共用項，ET / DM 管理者皆可檢視）：job 清單與執行歷程；MUST NOT 提供 UI 啟停或手動補跑（啟停由 DB / 部署管理）
- **FR-DP-US11-07**: 排程時間等業務參數存 `DP_PARAM`（前綴分模組，如 `ET_WEEKLY_STAT_DAY_TIME`、`DM_WEEKLY_SCHED_DAY_TIME`），由各模組管理者於 US5 維護；引擎 MUST 於觸發時讀取最新值

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-SCHEDULE-001 | 提示 | 尚無排程執行紀錄 | FR-DP-US11-06 空狀態 |

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
