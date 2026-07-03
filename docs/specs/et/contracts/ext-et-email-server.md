# EXT-EMAIL — ET 寄送 Email 至外部郵件伺服器

**編碼**: EXT-ET-EMAIL（外部介接）
**名稱**: ET 寄送 Email 至外部 SMTP 伺服器
**提供方**: 外部郵件伺服器（SMTP）
**呼叫方**: 教育訓練模組（ET）
**建立日期**: 2026-06-09（2026-07-02 依客戶 6 項需求變更改寫）
**對應 US**: [spec_us2.md](../spec_us2.md) US2、[spec_us3.md](../spec_us3.md) US3、[spec_us8.md](../spec_us8.md) US8、[spec_us10.md](../spec_us10.md) US10、[spec_us12.md](../spec_us12.md) US12、[spec_us14.md](../spec_us14.md) US14、[spec_us15.md](../spec_us15.md) US15

---

## 說明

ET 模組透過外部 SMTP 伺服器寄送課程 / 學習 / 帳號相關 Email。信件內容一律採**範本渲染**，範本分兩類來源（2026-07-02 變更）：

- **可維護範本**（**6 類**）：儲存於 `ET_NOTIFY_TEMPLATE` 表，由管理者於 [spec_us15.md](../spec_us15.md) US15「通知範本」分頁維護主旨與內文，並可**啟用 / 停用**（`IS_ACTIVE`）。**教師不可逐課編輯**信件主旨與內文（統一範本）。
- **系統固定範本**（**2 類**）：密碼重設信、帳號變更驗證信；屬帳號安全信件，**不入 `ET_NOTIFY_TEMPLATE`、不開放任何人於 UI 編輯、不可停用**，內容固定以確保一致與防偽。

> **2026-07-02 重大變更**：原以 `ET_PARAM.EMAIL_NOTIFY_*` 參數對應模板之機制**廢除**；改由 `ET_NOTIFY_TEMPLATE` 表管理可維護範本，密碼重設 / 帳號變更驗證改為系統固定範本。原「教師可於寄出前手動編輯邀請信主旨與內文」規則**廢除**，改為統一範本、教師僅可預覽。

收件對象一律為**學員 / 使用者個人 Email**；不設「單位信箱」收件（受訓單位概念已由受訓單位標籤吸收，「通知各單位」＝通知該標籤所有人員）。

---

## Email 類型（共 8 類）

### 可維護範本（6 類；`ET_NOTIFY_TEMPLATE`，管理者於 US15 維護、可停用）

| 類型 | 對應 US | 範本代碼（TEMPLATE_CODE）| 觸發時機 | 收件者 |
|------|---------|--------------------------|---------|--------|
| 課程邀請通知 | US8 / US3 | `COURSE_INVITE` | 發布時標籤自動邀請（每人一封）/ 教師 Email 邀請 / 已發布課程新增標籤補邀請 | 被加入 / 受邀學員個人 Email |
| 課程邀請彙整通知 | US1 / US8 | `COURSE_INVITE_DIGEST` | 管理者事後為使用者新增標籤，補加入該標籤所有「已發布且未關閉」課程（一人一信、列多門課程）| 該使用者個人 Email |
| 課程內容更新通知 | US3 | `COURSE_UPDATE` | 教師於已發布課程新增章節（每次新增即寄）| 該課程所有已加入學員（過濾已移除）|
| 每週未看提醒 | US14 | `WEEKLY_REMIND` | SCHET001 每週對進度 0%（完全未開始）學員（一人一信彙整，列出所有未開始課程）| 進度 0% 之學員 |
| 截止前加急提醒 | US14 | `URGENT_REMIND` | SCHET002 每日檢查，訖止前 N 天（`ET_PARAM.URGENT_REMIND_DAYS`）對所有未完課學員（每課只寄一次）| 未完課學員 |
| 週報 | US14 | `WEEKLY_REPORT` | SCHET001 每週；教師收自己建立之開放中課程、管理者收全域（內文摘要＋CSV 逐學員明細附件）| 教師 / 管理者 |

### 系統固定範本（2 類；不入 `ET_NOTIFY_TEMPLATE`、不可編輯、不可停用）

| 類型 | 對應 US | 固定範本代碼 | 觸發時機 | 收件者 |
|------|---------|-------------|---------|--------|
| 密碼重設信 | US2 | `ET_PASSWORD_RESET` | 使用者點「忘記密碼」並輸入 Email | 使用者 Email |
| 帳號變更驗證信 | US10 | `ET_EMAIL_CHANGE` | 使用者於 ET08 變更 Email | **新 Email**（變更目標）|

> **停用（IS_ACTIVE=false）行為**：僅適用可維護 6 類。停用後該類信件**不寄送**，但對應觸發事件**照常運作**（如停用 `COURSE_INVITE` 則發布仍自動加入學員、僅不寄邀請信；停用 `WEEKLY_REMIND` 則 SCHET001 仍統計 / 寄週報、僅不寄未看提醒）。系統固定 2 類無此開關。

---

## 介接流程

```
1. ET 業務邏輯 / 排程觸發寄信動作
2. ET 後端判定範本來源：
   a. 可維護範本 → 讀取 ET_NOTIFY_TEMPLATE（TEMPLATE_CODE）；若 IS_ACTIVE = false 則略過寄信（事件照常）
   b. 系統固定範本 → 讀取內建固定範本（不查 ET_NOTIFY_TEMPLATE）
3. ET 後端組合變數（課程名稱、起訖時間、學習連結、token、TTL、課程清單等）並渲染主旨 / 內文
   - 未定義之變數以空字串帶入（per US15）
4. ET 後端呼叫 SMTP 伺服器（標準 SMTP 協定，TLS 加密）
5. SMTP 伺服器回應寄送結果
6. ET 端依回應更新對應 DB / 寫入 log（如 ET_INVITATION.LAST_SENT_AT、status_code、URGENT_REMIND_SENT）
```

---

## SMTP 配置參數（部署時設定）

| 參數 | 說明 |
|------|------|
| SMTP_HOST | SMTP 伺服器主機名 |
| SMTP_PORT | 通訊埠（如 587）|
| SMTP_USERNAME | SMTP 帳號 |
| SMTP_PASSWORD | SMTP 密碼（由部署環境 secret manager / 環境變數提供，不寫入 ET_PARAM）|
| SMTP_TLS | 是否啟用 TLS（建議 true）|
| SMTP_SENDER | 寄件者地址（如 `noreply@et.example.com`；固定值，避免假冒）|

---

## 範本格式與變數

可維護範本之欄位定義見 [data-model.md](../data-model.md) `ET_NOTIFY_TEMPLATE`（`SUBJECT` / `BODY` / `IS_ACTIVE` / `VERSION`）。主旨與內文皆支援變數佔位符，格式為 `{{VARIABLE}}`（雙大括號、大寫；per [spec_us15.md](../spec_us15.md)）。系統固定範本之變數同格式，但範本內容不落 DB、不可編輯。

### 變數對應（依範本）

#### COURSE_INVITE（課程邀請通知）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 受邀學員姓名 |
| `{{COURSE_NAME}}` | 課程名稱 |
| `{{TEACHER_NAME}}` | 課程擁有者（教師）姓名 |
| `{{OPEN_START_AT}}` / `{{OPEN_END_AT}}` | 閱課期間起 / 訖 |
| `{{COURSE_URL}}` | 學習連結（Email 邀請時含 token）|
| `{{INVITATION_CODE}}` | 8 碼純數字邀請碼 |

#### COURSE_INVITE_DIGEST（課程邀請彙整通知）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 學員姓名 |
| `{{COURSE_LIST}}` | 本次補加入之所有課程清單（課程名稱＋起訖時間＋學習連結）|

#### COURSE_UPDATE（課程內容更新通知）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 學員姓名 |
| `{{COURSE_NAME}}` | 課程名稱 |
| `{{NEW_CHAPTER_NAME}}` | 新增章節名稱 |
| `{{COURSE_URL}}` | 進入課程之連結 |

#### WEEKLY_REMIND（每週未看提醒）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 學員姓名 |
| `{{COURSE_LIST}}` | 該學員所有進度 0% 之課程清單（課程名稱＋截止時間＋學習連結）|

#### URGENT_REMIND（截止前加急提醒）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 學員姓名 |
| `{{COURSE_NAME}}` | 課程名稱 |
| `{{OPEN_END_AT}}` | 截止時間 |
| `{{COURSE_URL}}` | 學習連結 |

#### WEEKLY_REPORT（週報）

| 變數 | 說明 |
|------|------|
| `{{RECIPIENT_NAME}}` | 收件者（教師 / 管理者）姓名 |
| `{{REPORT_SUMMARY}}` | 各課程摘要（平均進度%＋與上週比較、人數分布、完課率、距訖止天數、未開始名單）|

> 週報另附 **CSV 逐學員明細**（姓名、Email、進度%、完課狀態、最後活動時間）為附件，非內文變數。

#### ET_PASSWORD_RESET（密碼重設信；系統固定）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 使用者姓名 |
| `{{RESET_LINK}}` | 密碼重設連結（含 token）|
| `{{TTL_MIN}}` | 連結有效時間（分鐘，`ET_PARAM.PASSWORD_RESET_TTL_MIN`，預設 30）|

#### ET_EMAIL_CHANGE（帳號變更驗證信；系統固定）

| 變數 | 說明 |
|------|------|
| `{{USER_NAME}}` | 使用者姓名 |
| `{{VERIFY_LINK}}` | 驗證連結（含 token）|
| `{{OLD_EMAIL}}` / `{{NEW_EMAIL}}` | 舊 / 新 Email |
| `{{TTL_MIN}}` | 連結有效時間（分鐘，同 `PASSWORD_RESET_TTL_MIN`，預設 30）|

---

## 業務規則

- **統一範本、教師不可編輯**：所有課程 / 學習相關信件一律依 `ET_NOTIFY_TEMPLATE` 範本渲染；教師於 US8 Email 邀請時僅可**預覽**信件、**不可編輯主旨與內文**（2026-07-02 變更，原「教師可手動編輯」廢除）。管理者於 US15 統一維護。
- **停用不寄**：可維護 6 類若 `IS_ACTIVE = false` 則不寄該信、觸發事件照常；系統固定 2 類不可停用。
- **收件對象**：一律為個人 Email；不設單位信箱。
- **寄送失敗處理**（ET 端不設自動 retry，簡化系統複雜度）：
  - 課程邀請通知（標籤自動邀請）：**非同步**寄送，**失敗不回滾**已加入狀態（學員仍成功加入）；失敗寫入 log。
  - 課程邀請通知（Email 邀請補件）：`ET_INVITATION` 保留 `PENDING` 並寫 status_code，教師可於 [spec_us12.md](../spec_us12.md) US12「待加入」分頁點「再次寄送」。
  - 密碼重設信 / 帳號變更驗證信：使用者端顯示「請稍後再試」；token 已寫入 USER 表，可重試。
  - 課程內容更新 / 週報 / 週提醒 / 加急提醒：失敗寫入系統 log，**不影響**觸發事件本身（章節新增、統計快照、`URGENT_REMIND_SENT` 標記照常）；不另設重試（次要通知）。
- **加急提醒防重複**：`URGENT_REMIND` 每門課程只寄一次，以 `ET_COURSE.URGENT_REMIND_SENT` 控制；再開課重設起訖後歸 false 重新計。
- **課程內容更新通知**採「每次新增即寄」，不 debounce、不合併、不提供學員端關閉設定（per spec.md）。

---

## 安全性

- SMTP 連線必須採 TLS 加密。
- 邀請 token、密碼重設 token、Email 變更驗證 token 採 cryptographically secure random 產生（建議 ≥ 32 bytes）。
- 收件者 Email 之有效性檢核由 SMTP 伺服器執行；ET 端不驗證。
- 寄件者地址（SMTP_SENDER）為固定值，避免假冒。
- 密碼重設 / 帳號變更驗證信採系統固定範本、不可經 UI 編輯，避免範本遭竄改用於釣魚。

---

## 依賴狀態（提醒 SD）

- 依賴 `ET_NOTIFY_TEMPLATE` 表與 6 類範本 seed（[tasks.md](../tasks.md) T129）先行建立；US15 維護頁（T151）非阻擋——seed 內容即可支撐所有寄信。
- 密碼重設 / 帳號變更驗證之系統固定範本由 T040 / T101 實作（不入 `ET_NOTIFY_TEMPLATE`）。
- 各寄信點（T136 邀請 / T112 內容更新 / T146 週報 / T147 週提醒 / T148 加急）寄送前須檢查對應範本 `IS_ACTIVE`（T151 規範）。

---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-06-09 | 0.1 | 初稿；以 SMTP 為介接方式，不引入額外 MQ 或事件匯流排 |
| 2026-07-03 | 0.2 | 依 2026-07-02 客戶 6 項需求變更整份改寫：範本改掛 `ET_NOTIFY_TEMPLATE`（廢除 `EMAIL_NOTIFY_*`）、教師不可編輯改統一範本、補齊 US14 排程三類信與課程邀請彙整信、加入 `IS_ACTIVE` 停用不寄與系統固定範本規則、對應 US 補 US3/US14/US15 |
