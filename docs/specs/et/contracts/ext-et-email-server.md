# EXT-EMAIL — ET 寄送 Email 至外部郵件伺服器

**編碼**: EXT-ET-EMAIL（外部介接）
**名稱**: ET 寄送 Email 至外部 SMTP 伺服器
**提供方**: 外部郵件伺服器（SMTP）
**呼叫方**: 教育訓練模組（ET）
**建立日期**: 2026-06-09
**對應 US**: [spec_us2.md](../spec_us2.md) US2、[spec_us3.md](../spec_us3.md) US3、[spec_us8.md](../spec_us8.md) US8、[spec_us10.md](../spec_us10.md) US10、[spec_us12.md](../spec_us12.md) US12

---

## 說明

ET 模組透過外部 SMTP 伺服器寄送以下類型之 Email；信件模板由 `ET_PARAM` 之模板代碼對應，內容由 ET 端組合後送出。寄送失敗時依場景處理：邀請信寄送失敗保留 `ET_INVITATION.STATUS = PENDING` 以供 US12 待加入追蹤；密碼重設信寄送失敗回應使用者「請稍後再試」。

---

## Email 類型

| 類型 | 對應 US | 模板代碼（ET_PARAM）| 觸發時機 | 收件者 |
|------|---------|---------------------|---------|--------|
| 課程邀請信 | US8 | `EMAIL_NOTIFY_INVITATION`（預設 `ET_INVITATION`）| 教師寄出 Email 邀請 / 點再次寄送 | 學員 Email |
| 密碼重設信 | US2 | `EMAIL_NOTIFY_PASSWORD_RESET`（預設 `ET_PASSWORD_RESET`）| 使用者點「忘記密碼」並輸入 Email | 使用者 Email |
| 帳號變更驗證信 | US10 | `EMAIL_NOTIFY_EMAIL_CHANGE`（預設 `ET_EMAIL_CHANGE`）| 使用者於 ET08 變更 Email | **新 Email**（變更目標）|
| 章節更新通知信 | US3 | `EMAIL_NOTIFY_NEW_CHAPTER`（預設 `ET_NEW_CHAPTER`）| 教師於已發布課程新增章節 | 該課程所有已加入學員之 Email |

---

## 介接流程

```
1. ET 業務邏輯觸發寄信動作
2. ET 後端依模板代碼讀取信件模板（含主旨、HTML 內文、變數佔位符）
3. ET 後端組合變數（課程名稱、邀請連結、重設連結、token、TTL 等）
4. ET 後端呼叫 SMTP 伺服器（透過標準 SMTP 協定，TLS 加密）
5. SMTP 伺服器回應寄送結果
6. ET 端依回應更新對應 DB（如 ET_INVITATION.LAST_SENT_AT、status_code）
```

---

## SMTP 配置參數（部署時設定）

| 參數 | 說明 |
|------|------|
| SMTP_HOST | SMTP 伺服器主機名 |
| SMTP_PORT | 通訊埠（如 587）|
| SMTP_USERNAME | SMTP 帳號 |
| SMTP_PASSWORD | SMTP 密碼（密碼管理由部署環境負責，不寫入 ET_PARAM）|
| SMTP_TLS | 是否啟用 TLS（建議 true）|
| SMTP_SENDER | 寄件者地址（如 `noreply@et.example.com`）|

> SMTP 配置不在 ET_PARAM 內，由部署環境之 secret manager 或環境變數提供。

---

## 信件模板格式

每類型之模板含：

| 欄位 | 型別 | 說明 |
|------|------|------|
| subject_template | TEXT | 主旨模板，含變數佔位符（如 `{course_name}`）|
| body_html_template | TEXT | HTML 內文模板 |
| body_text_template | TEXT | 純文字內文模板（fallback）|

### 變數對應（依信件類型）

#### 課程邀請信

| 變數 | 說明 |
|------|------|
| `{course_name}` | 課程名稱 |
| `{teacher_name}` | 教師姓名 |
| `{invitation_link}` | 邀請連結（含 token）|
| `{invitation_code}` | 8 碼純數字邀請碼 |

#### 密碼重設信

| 變數 | 說明 |
|------|------|
| `{user_name}` | 使用者姓名 |
| `{reset_link}` | 密碼重設連結（含 token）|
| `{ttl_min}` | 連結有效時間（分鐘，預設 30）|

#### 帳號變更驗證信

| 變數 | 說明 |
|------|------|
| `{user_name}` | 使用者姓名 |
| `{verify_link}` | 驗證連結（含 token）|
| `{old_email}` | 舊 Email |
| `{new_email}` | 新 Email |
| `{ttl_min}` | 連結有效時間（分鐘，預設 30）|

#### 章節更新通知信

| 變數 | 說明 |
|------|------|
| `{user_name}` | 學員姓名 |
| `{course_name}` | 課程名稱 |
| `{new_chapter_name}` | 新增章節名稱 |
| `{course_link}` | 進入課程之連結 |

---

## 業務規則

- 教師可於 US8 寄出邀請信前**手動編輯主旨與內文**；其他類型之信件採模板自動產生不可編輯
- 寄送失敗依場景處理：
  - 邀請信：`ET_INVITATION` 保留為 `PENDING`，教師可於 US12 「待加入」分頁點「再次寄送」
  - 密碼重設信：使用者端顯示「請稍後再試」；token 已寫入 USER 表，可重試
  - 帳號變更驗證信：同上
  - 章節更新通知信：寄送失敗不影響章節新增本身；不另設重試機制（次要通知）
- 不在 ET 端設定 retry 機制：失敗即記錄並由人工 / 使用者觸發重試（簡化系統複雜度）
- 章節更新通知信採「每次新增即寄」，不 debounce、不合併、不提供學員端關閉設定（per spec.md）

---

## 安全性

- SMTP 連線必須採 TLS 加密
- 邀請 token、重設 token、驗證 token 採 cryptographically secure random 產生（建議 ≥ 32 bytes）
- 收件者 Email 之有效性檢核由 SMTP 伺服器執行；ET 端不驗證
- 寄件者地址（SMTP_SENDER）為固定值，避免假冒

---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-06-09 | 0.1 | 初稿；以 SMTP 為介接方式，不引入額外 MQ 或事件匯流排 |
