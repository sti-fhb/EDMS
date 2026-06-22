# User Story 11 — UCET003 課程停課（ET02）

> 返回總檔：[spec.md](spec.md) | 模組：教育訓練文件管理（ET）

教師於 ET02 課程編輯頁針對已發布之課程點「停課」按鈕，將課程狀態變更為「已停課」。停課後不可逆；已加入學員之歷史紀錄完整保留。若有學員作答中（ET_QUIZ_ATTEMPT_M 狀態 = IN_PROGRESS），課程先進入 `PENDING_CLOSE` 過渡狀態：新學員無法加入、無法開新 attempt、已加入學員可閱覽但不可開新 attempt，仍允許作答中學員完成本次（含 timeout 自動提交）；全部提交後系統自動將 `PENDING_CLOSE` → `CLOSED`。「停課」按鈕僅於已發布狀態顯示；草稿與已停課狀態下隱藏。

**Priority**: P3

**Why this priority**: 課程運作結束之終態流程；少數情境使用，不影響日常作業；採 Graceful Termination 設計需配合 attempt 完成機制。

**Independent Test**: 教師對無學員作答中之已發布課程點停課，立即進入「已停課」狀態；若有學員作答中，課程進入 PENDING_CLOSE；學員完成 attempt 後系統自動轉 CLOSED。

**Acceptance Scenarios**:

### 顯示條件

1. **Given** 課程狀態為「草稿」，**When** 教師進入 ET02，**Then** 「停課」按鈕**隱藏**
2. **Given** 課程狀態為「已發布」，**When** 教師進入 ET02，**Then** 「停課」按鈕顯示於頁面右上
3. **Given** 課程狀態為「停課中」或「已停課」，**When** 教師進入 ET02，**Then** 「停課」按鈕**隱藏**

### 無學員作答中之停課

4. **Given** 課程無 IN_PROGRESS 之 attempt，**When** 教師點「停課」並確認，**Then** 課程狀態立即變更為「已停課」（CLOSED）；ET_COURSE.CLOSED_AT 寫入
5. **Given** 學員於 ET04 我的課程列表，**When** 系統載入，**Then** 已停課課程於列表顯示「已停課」狀態標示；不顯示於進行中清單
6. **Given** 學員嘗試開啟已停課課程，**When** 系統載入，**Then** 顯示「此課程已停止開放」訊息頁
7. **Given** 教師查看已停課課程，**When** 點擊進入，**Then** 進入唯讀模式

### 有學員作答中之停課（PENDING_CLOSE）

8. **Given** 課程有 N 名學員 IN_PROGRESS attempt，**When** 教師點「停課」，**Then** 系統跳警告「目前有 {N} 位學員作答中，停課後將於其等提交後生效。確定停課？」
9. **Given** 教師確認，**When** 系統處理，**Then** 課程狀態變更為「停課中」（PENDING_CLOSE）：新學員無法加入、無法開新 attempt、已加入學員可閱覽但不可開新 attempt
10. **Given** 課程處於 PENDING_CLOSE，**When** 已加入學員嘗試開啟新測驗 attempt，**Then** 系統阻擋並提示「此課程已停止接受新作答」
11. **Given** 學員 IN_PROGRESS attempt 提交（含 timeout 自動提交），**When** 系統處理，**Then** 該 attempt 正常閱卷與計分；計入歷史紀錄
12. **Given** 所有 IN_PROGRESS attempt 皆已提交，**When** 系統偵測（排程或事件觸發），**Then** 課程狀態自動 PENDING_CLOSE → CLOSED；ET_COURSE.CLOSED_AT 寫入
13. **Given** 課程處於 PENDING_CLOSE，**When** 教師進入 ET02 編輯頁，**Then** 顯示「停課中（等待 {N} 位學員提交）」提示

### 終態保護

14. **Given** 已停課（CLOSED）為終態，**When** 教師嘗試恢復為已發布，**Then** 系統**不提供恢復按鈕**（per 「停課後不可逆」）
15. **Given** 邀請碼於課程停課後失效，**When** 學員嘗試輸入該邀請碼於 ET04 加入，**Then** 系統提示「此課程已停止開放」

---

## 相關 Clarifications 摘錄

- 停課後不可逆；已加入學員之歷史紀錄完整保留
- PENDING_CLOSE 為「已發布 → 已停課」之過渡狀態；無人作答後排程或事件觸發自動轉 CLOSED
- 此 US 採 Graceful Termination 原則：保留學員作答中之 attempt 完成機會

---

## 前置依賴

- 課程已由 [spec_us3.md](spec_us3.md) US3 發布
- 學員 attempt 由 [spec_us6.md](spec_us6.md) US6 寫入並提交
