# User Story 12 — UCET006 待加入邀請追蹤（ET03）

> 返回總檔：[spec.md](spec.md) | 模組：教育訓練文件管理（ET）

教師於 ET03 學員頁切至「待加入」分頁，可查看已寄出 Email 邀請但尚未加入之學員清單（Email、寄送時間、邀請狀態）。教師可對個別邀請執行「再次寄送」（系統重新呼叫 Email Server 寄出同一邀請信、寄送時間更新）或「撤回邀請」（ET_INVITATION 狀態更新為「已撤回」，原邀請連結失效，學員若點擊將顯示邀請已撤回）。學員透過邀請連結加入後，系統自動將其從「待加入」移至「已加入」分頁（屬 [spec_us9.md](spec_us9.md) US9）。

**Priority**: P3

**Why this priority**: 屬 Email 邀請（[spec_us8.md](spec_us8.md) US8）之後續追蹤；少數情境使用（多數學員會於收到信後加入），不影響日常作業核心流程。

**Independent Test**: 教師對既有「待加入」邀請執行「再次寄送」與「撤回邀請」，分別觸發新 Email 寄出與邀請連結失效。

**Acceptance Scenarios**:

1. **Given** 教師於 ET03 切至「待加入」分頁，**When** 系統載入，**Then** 顯示已寄出 Email 邀請但未加入之學員清單（欄位：Email、寄送時間、邀請狀態）
2. **Given** Email 邀請已寄出但學員未加入，**When** 顯示，**Then** 邀請狀態 = 「待加入」
3. **Given** 學員透過邀請連結加入，**When** 系統處理，**Then** ET_INVITATION 狀態更新為「已加入」；該紀錄自「待加入」清單移除、出現於 [spec_us9.md](spec_us9.md) US9「已加入」清單
4. **Given** 教師對某「待加入」邀請點「再次寄送」，**When** 系統處理，**Then** 重新呼叫 Email Server 寄出同一邀請信；ET_INVITATION.LAST_SENT_AT 更新為當下時間
5. **Given** 教師對某「待加入」邀請點「撤回邀請」，**When** 系統處理，**Then** ET_INVITATION 狀態更新為「已撤回」；該紀錄自「待加入」清單移除
6. **Given** 邀請已撤回，**When** 學員點擊該邀請連結，**Then** 系統顯示「此邀請已撤回」訊息頁
7. **Given** 課程被停課，**When** 教師查看「待加入」分頁，**Then** 仍可閱覽該課程之待加入清單，但無法再執行「再次寄送」（按鈕禁用）

---

## 相關 Clarifications 摘錄

- ET_INVITATION 狀態流：待加入 → 已加入 / 已撤回
- Email 邀請寄送失敗時於 [spec_us8.md](spec_us8.md) US8 設定 status_code；本 US 提供追蹤與重寄機制

---

## 前置依賴

- 教師已於 [spec_us8.md](spec_us8.md) US8 寄出 Email 邀請
- Email Server 介接已配置
