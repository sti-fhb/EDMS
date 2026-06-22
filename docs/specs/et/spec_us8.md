# User Story 8 — UCET004 邀請學員（ET02）

> 返回總檔：[spec.md](spec.md) | 模組：教育訓練文件管理（ET）

教師於 ET02 課程編輯頁針對已發布之課程點「邀請學員」按鈕，可透過三種來源邀請學員加入：（A）Email 邀請（教師輸入學員 Email 清單，系統產生邀請信預覽含課程名稱、邀請連結、邀請碼，教師可手動編輯主旨與內文後寄出）；（B）邀請碼（課程發布時系統自動產生 8 碼純數字邀請碼，教師可複製或顯示 QR Code 提供學員自行於 ET04 加入）；（C）模組預設帶入（建立課程時指定「關聯模組」後系統自動加入該模組所屬人員）。「邀請學員」按鈕僅於已發布狀態顯示；草稿與已停課狀態下隱藏。寄信失敗之 Email 列入 [spec_us12.md](spec_us12.md) US12 待加入清單。

**Priority**: P2

**Why this priority**: 課程已發布後之招生作業；但 Email 邀請與模組預設帶入皆可由「邀請碼自行加入」之 [spec_us4.md](spec_us4.md) US4 替代，故列 P2。

**Independent Test**: 教師對已發布課程執行 Email 邀請（含至少 1 個有效 Email、1 個無效 Email），驗證有效 Email 寄出並出現於學員端；無效 Email 列入待加入清單供 US12 處理。

**Acceptance Scenarios**:

### 顯示條件

1. **Given** 課程狀態為「草稿」，**When** 教師進入 ET02，**Then** 「邀請學員」按鈕**隱藏**
2. **Given** 課程狀態為「已發布」，**When** 教師進入 ET02，**Then** 「邀請學員」按鈕顯示於頁面右上
3. **Given** 課程狀態為「停課中」或「已停課」，**When** 教師進入 ET02，**Then** 「邀請學員」按鈕**隱藏**

### Email 邀請

4. **Given** 教師點「邀請學員」並選「Email 邀請」，**When** 系統載入，**Then** 跳出輸入視窗，提供 Email 清單欄位（多筆以分行或逗號分隔）
5. **Given** 教師輸入 Email 清單後點「下一步」，**When** 系統載入，**Then** 顯示邀請信預覽（含課程名稱、邀請連結、邀請碼）；教師可手動編輯主旨與內文
6. **Given** 教師點「寄出」，**When** 系統呼叫 Email Server，**Then** 對每個 Email 建立 ET_INVITATION 紀錄（狀態 = 待加入）並寄信；寄信成功 / 失敗皆寫入 status_code
7. **Given** 學員點擊邀請連結，**When** 系統驗證 token，**Then** 自動加入課程；ET_ENROLLMENT 寫入加入來源「Email 邀請」；ET_INVITATION 狀態更新為「已加入」
8. **Given** 已加入之學員再次點擊邀請連結，**When** 系統檢測，**Then** 直接導向 [spec_us5.md](spec_us5.md) US5 學習頁

### 邀請碼

9. **Given** 課程發布時，**When** 系統自動產生唯一 8 碼純數字邀請碼，**Then** 寫入 ET_COURSE.INVITATION_CODE（不可變更、不提供重新產生功能）
10. **Given** 教師點「邀請學員」並選「邀請碼」，**When** 系統載入，**Then** 顯示邀請碼字串與 QR Code，提供「複製」按鈕
11. **Given** 學員於 ET04 輸入該邀請碼加入，**When** 系統驗證，**Then** ET_ENROLLMENT 寫入加入來源「邀請碼」

### 模組預設帶入

12. **Given** 教師建立課程時指定「關聯模組 = 採血」，**When** 課程發布，**Then** 系統依 ET_USER_MODULE 對應自動加入所有「採血」業務模組所屬使用者；ET_ENROLLMENT 寫入加入來源「模組預設」
13. **Given** 管理者於 [spec_us1.md](spec_us1.md) US1 **新增**某使用者 × 採血對應，**When** 儲存，**Then** 系統自動將該使用者加入過去所有採血模組之已發布課程
14. **Given** 管理者**移除**某使用者 × 採血對應，**When** 儲存，**Then** 既有課程之學員名單**不變動**；之後新建之該模組課程不會自動邀請該使用者

---

## 相關 Clarifications 摘錄

- 邀請碼為純數字 8 碼、不可手動指定、不提供重新產生功能
- 業務模組對應變更後對既有 / 新課程之影響詳見 [spec.md](spec.md) §邀請與加入課程

---

## 前置依賴

- 課程已由 [spec_us3.md](spec_us3.md) US3 發布
- 業務模組對應由 [spec_us1.md](spec_us1.md) US1 維護
- Email Server 介接已配置
