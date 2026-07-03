# User Story 10 — UCET011 個人資料維護（ET08）

> 返回總檔：[spec.md](spec.md) | 模組：教育訓練文件管理（ET）

所有登入使用者於 ET08 個人資料維護頁可編輯自己之姓名、帳號（Email）、密碼。變更同步寫入共用 user table，DM 端同步生效。帳號（Email）變更採「雙信箱共存 + 新 Email 驗證後切換」之延遲生效機制：使用者提交新 Email 後系統寄出驗證信至**新 Email**（30 分鐘有效），**舊 Email 變更期間仍可正常登入**；學員 30 分鐘內點驗證連結後 USER.EMAIL 更新為新值並強制登出，須以新 Email 重新登入；未點驗證連結則變更請求視為作廢、舊 Email 永遠維持有效；變更期間再次提交新請求取代前次。密碼變更須填舊密碼 + 新密碼 + 確認新密碼，系統檢核舊密碼正確、新密碼兩次一致後儲存。忘記密碼改走 [spec_us2.md](spec_us2.md) US2 登入頁之「忘記密碼」連結。

**Priority**: P2

**Why this priority**: 為所有使用者個人資料自助維護之入口；變更內容（特別是 Email）涉及認證流程之邊界處理。

**Independent Test**: 編輯姓名儲存後查看，名稱正確更新；變更密碼後以新密碼可登入；變更 Email 後 30 分鐘內驗證生效、未驗證則舊 Email 仍可登入。

**Acceptance Scenarios**:

### 編輯姓名

1. **Given** 使用者於 ET08 編輯姓名為新值並儲存，**When** 系統處理，**Then** 共用 USER.NAME 更新；DM 端同步生效（共用 user table）

### 變更帳號（Email）— 提交與驗證

2. **Given** 使用者於 ET08 輸入新 Email 並點「儲存」，**When** 系統處理，**Then** 寫入 USER.EMAIL_PENDING_CHANGE = 新 Email、產生 EMAIL_PENDING_TOKEN、EMAIL_PENDING_EXPIRES_AT = 當下 + 30 分鐘；USER.EMAIL（舊值）**不變**
3. **Given** 系統寄發驗證信至**新 Email**，**When** 學員 30 分鐘內點驗證連結，**Then** USER.EMAIL 更新為新值；清除 PENDING 欄位；學員當前 session 強制登出，須以新 Email 重新登入
4. **Given** 學員於 PENDING 期間未點驗證連結，**When** 30 分鐘逾期，**Then** PENDING 欄位於下次與該帳號相關之認證 / 變更動作時即時檢核並清理；變更請求視為作廢；舊 Email 永遠維持有效
5. **Given** 學員於 PENDING 期間再次提交新變更請求，**When** 系統處理，**Then** 舊 PENDING 紀錄被**取代**；新驗證連結重新計時 30 分鐘
6. **Given** 學員處於 PENDING 期間（驗證未完成），**When** 學員以**舊 Email** 登入，**Then** 系統**允許登入**（變更尚未生效）

### 變更密碼

7. **Given** 使用者點「變更密碼」按鈕，**When** 系統載入，**Then** 跳 modal，提供舊密碼 + 新密碼 + 確認新密碼三欄位
8. **Given** 使用者填寫完成點儲存，**When** 系統檢核舊密碼正確、新密碼兩次一致，**Then** USER.PASSWORD_HASH 更新；提示「密碼已變更」
9. **Given** 使用者輸入之舊密碼錯誤，**When** 系統檢核，**Then** 提示「舊密碼不正確」
10. **Given** 使用者輸入之新密碼與確認新密碼不一致，**When** 系統檢核，**Then** 提示「兩次新密碼不一致」

---

## Functional Requirements

- **FR-ET-US10-01**: 系統 MUST 提供使用者於 ET08 編輯自己之姓名，儲存後更新共用 USER.NAME 並同步生效於 ET / DM 兩系統（共用 user table）
- **FR-ET-US10-02**: 帳號（Email）變更 MUST 採「雙信箱共存 + 新 Email 驗證後切換」之延遲生效機制；提交新 Email 時系統 MUST 寫入 USER.EMAIL_PENDING_CHANGE、產生 EMAIL_PENDING_TOKEN 與 EMAIL_PENDING_EXPIRES_AT（當下 + 30 分鐘，TTL 由 ET_PARAM.PASSWORD_RESET_TTL_MIN 控制），且 USER.EMAIL（舊值）MUST 維持不變
- **FR-ET-US10-03**: 系統 MUST 將驗證信寄至新 Email；使用者於期限內點驗證連結後，系統 MUST 將 USER.EMAIL 更新為新值、清除 PENDING 欄位並強制登出當前 session，須以新 Email 重新登入
- **FR-ET-US10-04**: PENDING 期間（驗證未完成）系統 MUST 允許使用者以舊 Email 正常登入（變更尚未生效）
- **FR-ET-US10-05**: 驗證連結逾期未點時，系統 MUST 於下次與該帳號相關之認證 / 變更動作時即時檢核並清理 PENDING 欄位，變更請求視為作廢、舊 Email 永久維持有效
- **FR-ET-US10-06**: PENDING 期間再次提交新變更請求時，系統 MUST 取代前次 PENDING 紀錄並將新驗證連結重新計時 30 分鐘
- **FR-ET-US10-07**: 密碼變更 MUST 要求舊密碼 + 新密碼 + 確認新密碼三欄位並檢核舊密碼正確且新密碼兩次一致後更新 USER.PASSWORD_HASH；系統 MUST NOT 在舊密碼錯誤或新密碼兩次不一致時更新密碼，並須回覆對應錯誤訊息

---

## 系統訊息

各訊息類型（錯誤 / 警告 / 確認 / 成功 / 提示）定義見 [spec.md](spec.md) §Requirements。

| 訊息代碼 | 類型 | 訊息內容 | 觸發情境 |
|---------|------|---------|---------|
| ET-MSG-ET08-001 | 成功 | 姓名已更新 | 場景 1：編輯姓名 |
| ET-MSG-ET08-002 | 提示 | 驗證信已寄至新 Email，請於 30 分鐘內點擊完成變更；舊 Email 於此期間仍可登入 | 場景 2/3：提交帳號（Email）變更 |
| ET-MSG-ET08-003 | 成功 | 密碼已變更 | 場景 8：變更密碼成功 |
| ET-MSG-ET08-004 | 錯誤 | 舊密碼不正確 | 場景 9：舊密碼錯誤 |
| ET-MSG-ET08-005 | 錯誤 | 兩次新密碼不一致 | 場景 10：新密碼兩次不符 |

---

## 相關 Clarifications 摘錄

- ET / DM 共用 user table；姓名 / Email / 密碼變更皆同步生效於兩系統
- Email 變更採雙信箱共存模式；驗證連結 TTL 由 `ET_PARAM.PASSWORD_RESET_TTL_MIN` 控制（與密碼重設同 30 分鐘）

---

## 前置依賴

- 使用者已於 [spec_us2.md](spec_us2.md) US2 註冊並登入
- Email Server 介接已配置
