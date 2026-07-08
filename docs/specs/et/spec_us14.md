# User Story 14 — UCET014 排程統計與提醒（SCHET001 / SCHET002）

> 對應 UC：UCET014 ｜ 功能選項：SCH（排程統計與提醒，無操作畫面）｜ Priority：P2 ｜ Wireframe：排程作業，無操作畫面 ｜ 返回總檔：[spec.md](spec.md)
> 2026-07-02 新增（客戶需求變更 item 4：每週自動統計看課百分比並回傳，同時通知未看者）。

系統以兩支排程自動統計看課狀況並寄發提醒，**僅針對開放中**（已發布且於起訖期間內）之課程執行：**SCHET001 每週統計與週報**（每週一 10:00，`DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` 可調）——統計各開放中課程並留存快照 `ET_WEEKLY_STAT`，寄週報予教師（自己建立之課程）與管理者（全域），並對**進度 0%（完全未開始）**之學員寄未看提醒（一人一信彙整）；**SCHET002 每日課程時窗檢查**（每日執行）——到期課程自動轉 CLOSED（→ [spec_us11.md](spec_us11.md) US11），並於**訖止前 3 天**（`DP_PARAM.ET_URGENT_REMIND_DAYS` 可調）對未完課學員寄加急提醒（每課只寄一次）。本 US 無 UI 畫面（純排程作業）；信件採 [spec_us15.md](spec_us15.md) US15 統一範本。**排程集中於平台 DP（2026-07-08）**：SCHET001 / SCHET002 於平台 `DP_SCHEDULE` 註冊、由平台單一排程引擎執行、`DP_SCHEDULE_LOG` 記錄執行歷程；job handler 由 ET 提供（需要業務資料時反向 import ET service）；寄信呼叫平台唯一發信服務（經 `DP_EMAIL_LOG` outbox）。

**Priority**: P2

**Why this priority**: 教師 / 管理者掌握訓練執行狀況與催辦之自動化核心，客戶明確要求；不阻擋學習主流程故非 P1。

**Independent Test**: 建立一門開放中課程（含 0% / 進行中 / 已完課學員各至少 1 名），手動觸發 SCHET001 驗證快照寫入、週報寄達教師與管理者、僅 0% 學員收到彙整提醒；將課程訖止時間調至 3 天內，觸發 SCHET002 驗證所有未完課學員收到加急提醒且只寄一次。

**Acceptance Scenarios**:

### SCHET001 — 每週統計與快照

1. **Given** 排定時間到（每週一 10:00，`DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` 可調），**When** 平台排程引擎觸發 SCHET001（於 `DP_SCHEDULE` 註冊），**Then** 系統對每門**開放中**課程統計：平均看課進度%、未開始 / 進行中 / 已完課人數、完課率、已加入人數（不含已移除）
2. **Given** 統計完成，**When** 寫入快照，**Then** 每門課程 INSERT 一筆 `ET_WEEKLY_STAT`（課程 × 統計日期唯一；append-only，不回頭修改）
3. **Given** 課程已關閉或尚未到起始時間，**When** SCHET001 執行，**Then** 該課程**不納入**統計與提醒

### SCHET001 — 週報寄送

4. **Given** 快照寫入完成，**When** 系統寄送週報，**Then** 每位**教師**收到一封週報（僅含自己建立之開放中課程）；每位**管理者**收到一封全域週報（所有開放中課程）
5. **Given** 週報產生，**When** 渲染內容，**Then** email 內文摘要含每門課程：平均看課進度%（含與上週快照比較之增減）、人數分布（未開始 / 進行中 / 已完課）、完課率、距訖止天數、未開始名單；並附 CSV 逐學員明細（姓名、Email、進度%、完課狀態、最後活動時間）
6. **Given** 該課程為本週首次統計（無上週快照），**When** 週報渲染，**Then** 「與上週比較」欄顯示「—」（不顯示錯誤）

### SCHET001 — 每週未看提醒

7. **Given** 某學員於一門以上開放中課程之進度為 **0%（完全未開始）**，**When** SCHET001 提醒階段執行，**Then** 該學員收到**一封彙整**提醒信（範本 `WEEKLY_REMIND`，列出其所有未開始課程與各課程截止時間）
8. **Given** 學員於某課程進度 > 0%，**When** 提醒階段執行，**Then** 該課程**不列入**其週提醒（已開始者不催）
9. **Given** 學員已完課或已被移除，**When** 提醒階段執行，**Then** 不收到該課程之任何提醒

### SCHET002 — 每日課程時窗檢查

10. **Given** 每日排程執行，**When** 偵測課程 `OPEN_END_AT` 已過且狀態仍為 PUBLISHED，**Then** 系統自動將該課程轉 CLOSED（行為依 [spec_us11.md](spec_us11.md) US11）
11. **Given** 課程進入「訖止前 3 天」（`DP_PARAM.ET_URGENT_REMIND_DAYS` 可調）且 `URGENT_REMIND_SENT = false`，**When** SCHET002 執行，**Then** 對該課程**所有未完課**學員（不含已移除）寄加急提醒信（範本 `URGENT_REMIND`，標明課程名稱與截止時間），並將 `URGENT_REMIND_SENT` 置 true
12. **Given** `URGENT_REMIND_SENT = true`，**When** 次日 SCHET002 再執行，**Then** **不重複**寄送加急提醒
13. **Given** 已關閉課程執行「再開課」（重設起訖），**When** 再開課完成，**Then** `URGENT_REMIND_SENT` 歸 false（新時窗之加急提醒重新計）

### 例外處理

14. **Given** 週報 / 提醒信寄送失敗（Email Server 異常），**When** 排程完成，**Then** 失敗紀錄寫入系統 log；快照資料不受影響（統計與寄信分離）

---

## 統計定義（權威定義見 [spec.md](spec.md) §排程統計與提醒規則）

| 名詞 | 定義 |
|------|------|
| 學員看課進度 % | 已完成章節項目數 ÷ 總章節項目數（影片依覆蓋率 ≥ 80%、測驗依及格、文件 / 說明文字依開啟判完成）|
| 完課率 | 已完課 ÷ 已加入（不含已移除）|
| 與上週比較 | 本次 ET_WEEKLY_STAT − 該課程前一次快照 |

---

## Functional Requirements

- **FR-ET-US14-01**: 系統 MUST 僅對「開放中」（已發布且於起訖期間內）之課程執行 SCHET001 與 SCHET002 之統計與提醒；已關閉或尚未到起始時間之課程 MUST NOT 納入統計與提醒
- **FR-ET-US14-02**: 系統 MUST 於排定時間（每週一 10:00，`DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` 可調）由平台排程引擎執行 SCHET001（於 `DP_SCHEDULE` 註冊、`DP_SCHEDULE_LOG` 記錄），對每門開放中課程統計平均看課進度%、未開始 / 進行中 / 已完課人數、完課率與已加入人數（不含已移除）
- **FR-ET-US14-03**: 系統 MUST 於每次 SCHET001 統計完成時，為每門課程以 append-only 方式 INSERT 一筆 `ET_WEEKLY_STAT` 快照（課程 × 統計日期唯一），MUST NOT 回頭修改既有快照
- **FR-ET-US14-04**: 系統 MUST 於快照寫入後寄送週報：每位教師收到一封（僅含自己建立之開放中課程）、每位管理者收到一封全域週報；內文 MUST 含各課程平均看課進度%（含與上週快照比較之增減）、人數分布、完課率、距訖止天數與未開始名單，並附逐學員 CSV 明細；當該課程無上週快照時「與上週比較」MUST 顯示「—」而非錯誤
- **FR-ET-US14-05**: 系統 MUST 於 SCHET001 提醒階段，對進度為 0%（完全未開始）之學員寄送一封彙整未看提醒信（範本 `WEEKLY_REMIND`，列出其所有未開始課程與各課程截止時間）；進度 > 0%、已完課或已被移除者 MUST NOT 就該課程列入週提醒
- **FR-ET-US14-06**: 系統 MUST 於 SCHET002 每日執行時，將 `OPEN_END_AT` 已過且狀態仍為 PUBLISHED 之課程自動轉為 CLOSED（行為依 [US11](spec_us11.md)）
- **FR-ET-US14-07**: 系統 MUST 於課程進入「訖止前 N 天」（`DP_PARAM.ET_URGENT_REMIND_DAYS` 可調）且 `URGENT_REMIND_SENT = false` 時，對該課程所有未完課學員（不含已移除）寄送加急提醒信（範本 `URGENT_REMIND`，標明課程名稱與截止時間），並將 `URGENT_REMIND_SENT` 置 true
- **FR-ET-US14-08**: 系統 MUST 於 `URGENT_REMIND_SENT = true` 時不重複寄送加急提醒；課程執行「再開課」（重設起訖）時 MUST 將 `URGENT_REMIND_SENT` 歸 false，使新時窗之加急提醒重新計算
- **FR-ET-US14-09**: 系統 MUST 將統計快照與寄信作業分離；週報 / 提醒信經平台唯一發信服務寄送（`DP_EMAIL_LOG` outbox），寄送失敗時 MUST 將失敗紀錄寫入系統 log / `DP_SCHEDULE_LOG`，且 MUST NOT 影響已寫入之統計快照資料
- **FR-ET-US14-10**: 系統 MUST 一律依 [US15](spec_us15.md) 之平台 `DP_NOTIFY_TEMPLATE`（`MODULE=ET`）統一範本渲染所有排程寄出信件（WEEKLY_REPORT / WEEKLY_REMIND / URGENT_REMIND），並經平台唯一發信服務寄送

---

## 系統訊息

本 US 為純排程作業、**無 UI 畫面**，功能作業碼採 `SCH`。下列為排程寄送之信件與執行結果 log；信件內容一律依 [spec_us15.md](spec_us15.md) US15 之平台 `DP_NOTIFY_TEMPLATE`（`MODULE=ET`）統一範本渲染、經平台唯一發信服務寄送。訊息類型定義見 [spec.md](spec.md) §Requirements。

| 訊息代碼 | 類型 | 訊息內容 | 觸發情境 |
|---------|------|---------|---------|
| ET-MSG-SCH-001 | 提示 | （週報信）本週看課統計週報（範本 WEEKLY_REPORT）| 場景 4/5：SCHET001 寄送教師 / 管理者週報 |
| ET-MSG-SCH-002 | 提示 | （提醒信）您有課程尚未開始（範本 WEEKLY_REMIND）| 場景 7：SCHET001 對進度 0% 學員之未看提醒 |
| ET-MSG-SCH-003 | 提示 | （加急信）課程即將截止，請儘速完課（範本 URGENT_REMIND）| 場景 11：SCHET002 截止前 N 天加急提醒 |
| ET-MSG-SCH-004 | 錯誤 | 排程寄信失敗，已寫入系統 log（不影響統計快照）| 場景 14：Email Server 異常 |

---

## 相關 Clarifications 摘錄

- 週提醒**僅寄 0% 未開始者**：長期課程「未完課就提醒」造成提醒疲勞；「開始後停滯者」由截止前加急信作最後防線（2026-07-02 客戶確認方案 a）
- 加急提醒對象為**所有未完課者**（不設進度門檻）
- 週報呈現「平均進度％＋人數分布＋與上週比較」而非僅完課率——長期課程前期完課率必為 0，無參考價值（2026-07-02 客戶確認）
- 排程於平台 `DP_SCHEDULE` 註冊、由平台單一排程引擎執行（`DP_SCHEDULE_LOG` 記錄）；job handler 由 ET 提供；「到期自動關閉」另有應用層存取時即時判定作雙保險（per [spec.md](spec.md) §課程起訖時間與狀態機）

---

## 前置依賴

- 課程起訖時間與狀態機由 [spec_us3.md](spec_us3.md) / [spec_us11.md](spec_us11.md) 定義
- 學員進度資料由 [spec_us5.md](spec_us5.md) / [spec_us6.md](spec_us6.md) 產生
- 信件範本（WEEKLY_REMIND / URGENT_REMIND / WEEKLY_REPORT）由 [spec_us15.md](spec_us15.md) US15 維護（存平台 `DP_NOTIFY_TEMPLATE`，`MODULE=ET`）
- 平台發信服務（`DP_EMAIL_LOG` outbox）與平台排程引擎（`DP_SCHEDULE` / `DP_SCHEDULE_LOG`）已就緒；SCHET001 / SCHET002 已於 `DP_SCHEDULE` 註冊

---

## 相關文件

- 模組總覽與跨 US 規則：[spec.md](spec.md)
- 資料模型：[data-model.md](data-model.md)
- 需求清單：[../../requirements/RQET.md](../../requirements/RQET.md)
- 使用案例：[../../use-cases/et/usecases.md](../../use-cases/et/usecases.md)
- 畫面 Wireframe：[ET wireframe](../../wireframes/et/index.html)
