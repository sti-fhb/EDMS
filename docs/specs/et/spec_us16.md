# User Story 16 — UCET016 學員線下考核核可（ET03）

> 對應 UC：UCET016 ｜ 功能選項：ET03（學員線下考核核可）｜ Priority：P2 ｜ Wireframe：[學員頁－核可](../../wireframes/et/index.html) ｜ 返回總檔：[spec.md](spec.md)
> 2026-07-17 新增（客戶需求：線下人工核可）。與 [spec_us9.md](spec_us9.md) US9 共用 ET03「已加入」頁籤畫面；核可動作長在該頁，核可查詢另見 [spec_us17.md](spec_us17.md) US17。

部分課程於線上完課後仍有**實機操作 / 口頭考核**等系統無法自動判定之考核。教師（該課程 owner）或管理者於 ET03「已加入」頁籤，對**已線上完課**之學員執行**線下核可**：結果為**通過 / 不通過**二態（不記考核分數，不通過留紀錄並可附備註），支援**批次核可**（同一梯次一次核可多人）。已核可可**撤銷**，撤銷**必須填寫原因**；撤銷後學員回到「待核可」可重新核可。核可**通過**時寄「核可通過通知」給學員（[spec.md](spec.md) §通知信統一範本第 7 類）；不通過與撤銷不寄信。

核可為**獨立於完課之維度**（走法 A）：僅 `ET_COURSE.REQUIRE_APPROVAL = true` 之課程有核可流程；核可**以線上完課為前提**，但**不併入完課定義**，不影響完課率 / 平均成績 / 課後問卷開放 / 週報統計（[spec.md](spec.md) §線下核可規則、§完課定義與完課率計算）。教師新增章節致完課回退時，核可紀錄**不失效**（比照課後問卷）。

**Priority**: P2

**Why this priority**: 為訓練成效之最終把關（實機 / 口頭考核），是客戶明確提出之需求；但屬線上學習主流程（P1）之後的延伸作業，與 US17 查詢成對交付。

**Independent Test**: 於 `REQUIRE_APPROVAL = true` 之課程，ET03 對已完課學員可執行核可（通過 / 不通過、可批次），對未完課學員核可入口停用；核可通過後學員收到通知信、綜合狀態轉「已通過」；撤銷須填原因、撤銷後回「待核可」；`REQUIRE_APPROVAL = false` 之課程與已關閉課程不可執行核可。

**Acceptance Scenarios**:

### 核可欄顯示與前提

1. **Given** 所選課程 `REQUIRE_APPROVAL = true`，**When** 教師 / 管理者進入 ET03「已加入」頁籤區塊 1，**Then** 學員清單顯示「核可狀態」欄與核可操作（衍生狀態：未達核可資格 / 待核可 / 已通過 / 未通過）
2. **Given** 所選課程 `REQUIRE_APPROVAL = false`，**When** 進入 ET03，**Then** **不顯示**核可欄與核可操作
3. **Given** 學員**尚未線上完課**（完課狀態非「已完成」），**When** 檢視其核可操作，**Then** 顯示「未達核可資格」，**不顯示**核可按鈕（僅保留移除等既有操作）
4. **Given** 學員**已線上完課但尚無核可紀錄**，**When** 檢視，**Then** 綜合狀態顯示「待核可」，核可按鈕可點

### 核可（通過 / 不通過）

5. **Given** 學員已完課且待核可，**When** 教師 / 管理者對其核可「通過」並確認，**Then** 系統寫入 ET_APPROVAL（RESULT = PASS、APPROVED_BY / APPROVED_AT），綜合狀態轉「已通過」
6. **Given** 教師 / 管理者對已完課學員核可「不通過」（可填備註）並確認，**When** 送出，**Then** 系統寫入 ET_APPROVAL（RESULT = FAIL、RESULT_NOTE 選填），綜合狀態轉「未通過」；**不寄信**
7. **Given** 核可結果為「通過」，**When** 寫入成功，**Then** 系統呼叫平台唯一發信服務以範本 `APPROVAL_PASSED` 寄核可通過通知給該學員（經 `DP_EMAIL_LOG` outbox）
8. **Given** 教師 / 管理者勾選多名**已完課**學員執行**批次核可通過**並確認，**When** 送出，**Then** 系統對所選學員逐一寫入 PASS 並各寄一封核可通過通知；名單中若含未完課者，該筆**跳過**並提示

### 撤銷

9. **Given** 學員已有核可紀錄（通過 / 不通過），**When** 教師 / 管理者點「撤銷核可」，**Then** 系統要求**填寫撤銷原因**（必填）
10. **Given** 撤銷原因為空，**When** 送出撤銷，**Then** 系統阻擋並提示「請填寫撤銷原因」
11. **Given** 撤銷原因已填，**When** 確認撤銷，**Then** 系統更新 ET_APPROVAL（IS_REVOKED = true、REVOKE_REASON、REVOKED_BY / REVOKED_AT），綜合狀態回「待核可」；**不寄信**
12. **Given** 已撤銷之學員，**When** 教師 / 管理者重新核可，**Then** 系統以同一筆更新（IS_REVOKED 回 false、更新 RESULT 與 APPROVED_BY / APPROVED_AT、清撤銷欄位）；若重核為「通過」則再寄核可通過通知

### 權限與並發

13. **Given** 教師**非**該課程 owner（他人課程），**When** 檢視 ET03，**Then** 核可操作**不顯示**（僅 owner 或管理者可核可）
14. **Given** 兩位有權者同時對同一學員核可，**When** 後者送出，**Then** 系統以 VERSION 樂觀鎖檢核，版本不符時拒絕並提示重新整理

### 核可與完課 / 課程狀態之關係

15. **Given** 學員已核可通過後，教師新增章節致其完課狀態回退為「進行中」，**When** 系統處理，**Then** 核可紀錄**不失效**（維持「已通過」）；完課回退僅影響完課維度
16. **Given** 課程**已關閉（CLOSED）**，**When** 教師 / 管理者進入 ET03，**Then** 核可狀態仍可**閱覽**，但「核可 / 撤銷」按鈕**停用**；再開課後恢復
17. **Given** 學員完課率統計 / 週報執行，**When** 系統計算，**Then** 核可維度**不計入**完課率、平均成績與週報（獨立維度）

---

## Functional Requirements

- **FR-ET-US16-01**: 系統 MUST 於 ET02 課程基本資料提供「是否需線下核可」（`REQUIRE_APPROVAL`）設定，預設 false；此設定屬課程屬性，於 [spec_us3.md](spec_us3.md) US3 課程建立 / 編輯畫面維護
- **FR-ET-US16-02**: 系統 MUST 僅於 `REQUIRE_APPROVAL = true` 之課程於 ET03「已加入」頁籤顯示核可欄與核可操作；學員綜合狀態 MUST 由完課狀態 + ET_APPROVAL 即時衍生（未達核可資格 / 待核可 / 已通過 / 未通過），MUST NOT 另存狀態欄位
- **FR-ET-US16-03**: 系統 MUST 以「線上完課」（`ET_ENROLLMENT.COMPLETION_STATUS = COMPLETED`）為核可前提；未完課學員 MUST NOT 顯示核可按鈕（不提供核可入口，狀態顯示「未達核可資格」）；批次核可時對名單中未完課者 MUST 跳過並提示
- **FR-ET-US16-04**: 核可結果 MUST 為二態（PASS 通過 / FAIL 不通過），MUST NOT 記考核分數；不通過（FAIL）MUST 留紀錄並得附備註（RESULT_NOTE）；寫入 MUST 記錄 APPROVED_BY / APPROVED_AT
- **FR-ET-US16-05**: 系統 MUST 支援批次核可（對多名已完課學員一次核可通過 / 不通過），逐一寫入 ET_APPROVAL 並各自套用通知規則
- **FR-ET-US16-06**: 撤銷核可時系統 MUST 要求填寫撤銷原因（必填），MUST 阻擋原因為空之撤銷；撤銷 MUST 寫入 IS_REVOKED = true、REVOKE_REASON、REVOKED_BY / REVOKED_AT，撤銷後綜合狀態 MUST 回「待核可」且可重新核可（以同一筆 (COURSE_ID, USER_ID) 更新）
- **FR-ET-US16-07**: 核可 / 撤銷之執行者 MUST 限該課程 owner（教師）或管理者；非 owner 之其他教師 MUST NOT 顯示核可操作
- **FR-ET-US16-08**: 核可結果為 PASS 且非撤銷狀態時系統 MUST 以範本 `APPROVAL_PASSED`（`DP_NOTIFY_TEMPLATE`，`MODULE=ET`）呼叫平台唯一發信服務寄核可通過通知；FAIL 與撤銷 MUST NOT 寄信
- **FR-ET-US16-09**: 核可 MUST 獨立於完課維度，MUST NOT 計入完課率 / 平均成績 / 課後問卷開放時機 / 週報統計；教師新增章節致完課回退時核可紀錄 MUST NOT 失效
- **FR-ET-US16-10**: 課程狀態為 CLOSED 時系統 MUST 允許閱覽核可狀態但 MUST NOT 允許新增核可 / 撤銷；課程再開課後 MUST 恢復
- **FR-ET-US16-11**: ET_APPROVAL MUST 以 (COURSE_ID, USER_ID) 邏輯唯一（0～1 筆 / 學員 / 課程）；寫入 MUST 以 VERSION 樂觀鎖檢核並防並發覆寫

---

## 系統訊息

各訊息類型（錯誤 / 警告 / 確認 / 成功 / 提示）定義見 [spec.md](spec.md) §Requirements。ET03 為多 US 共用畫面，本 US（線下核可）使用流水號區段 **301–399**（US9 = 001–099、US12 = 101–199）。

| 訊息代碼 | 類型 | 訊息內容 | 觸發情境 |
|---------|------|---------|---------|
| ET-MSG-ET03-301 | 確認 | 確定核可所選學員為「通過」？ | 場景 5 / 8：核可通過（含批次）|
| ET-MSG-ET03-302 | 成功 | 已完成核可 | 場景 5/6/8：核可成功 |
| ET-MSG-ET03-303 | 提示 | 部分學員尚未完課，已跳過（N 筆）| 場景 8：批次含未完課者 |
| ET-MSG-ET03-304 | 錯誤 | 學員尚未完課，無法核可 | 場景 3：對未完課學員核可 |
| ET-MSG-ET03-305 | 錯誤 | 請填寫撤銷原因 | 場景 10：撤銷未填原因 |
| ET-MSG-ET03-306 | 成功 | 已撤銷核可 | 場景 11：撤銷成功 |
| ET-MSG-ET03-307 | 提示 | 課程已關閉，僅可閱覽核可狀態 | 場景 16：關閉後嘗試核可 / 撤銷 |
| ET-MSG-ET03-308 | 警告 | 核可狀態已被其他人變更，請重新整理後再試 | 場景 14：樂觀鎖衝突 |

---

## 相關 Clarifications 摘錄

- 走法 A：核可為**獨立維度**，不併入完課定義（2026-07-17 客戶確認）
- 核可前提為**線上先完課**；粒度為**課程層級**（非個別考核項目）（2026-07-17 客戶確認）
- 結果**只有通過 / 不通過**（不記分數）；**不通過留紀錄**（2026-07-17 客戶確認）
- 可**撤銷**，撤銷**須填原因**（2026-07-17 客戶確認）
- **不需**核可證明 / 結業證書輸出（2026-07-17 客戶確認）
- 核可通過**寄信**通知學員（新增第 7 類通知範本 `APPROVAL_PASSED`）；不通過 / 撤銷不寄（2026-07-17 客戶確認）
- 核可紀錄**獨立、不隨新增章節之完課回退失效**（2026-07-17 客戶確認）

---

## 前置依賴

- 課程已由 [spec_us3.md](spec_us3.md) US3 建立並設定 `REQUIRE_APPROVAL`；已發布且有學員完課
- 完課判定依 [spec.md](spec.md) §完課定義與完課率計算（US5 / US6 寫入進度與成績）
- 核可動作畫面共用 [spec_us9.md](spec_us9.md) US9 之 ET03「已加入」頁籤（區塊 1 學員清單）
- 通知範本 `APPROVAL_PASSED` 由平台 DP seed（`DP_NOTIFY_TEMPLATE`，`MODULE=ET`），寄信經平台唯一發信服務
- 查詢由 [spec_us17.md](spec_us17.md) US17 提供

---

## 相關文件

- 模組總覽與跨 US 規則：[spec.md](spec.md)（§線下核可規則）
- 資料模型：[data-model.md](data-model.md)（ET_APPROVAL、ET_APPROVAL_RESULT）
- 需求清單：[../../requirements/RQET.md](../../requirements/RQET.md)
- 使用案例：[../../use-cases/et/usecases.md](../../use-cases/et/usecases.md)（UCET016）
- 畫面 Wireframe：[ET wireframe](../../wireframes/et/index.html)
