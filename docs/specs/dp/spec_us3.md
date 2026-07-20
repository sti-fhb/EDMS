# User Story 3 — 忘記密碼（UCDP003）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（登入頁・忘記密碼）

## User Story

作為忘記密碼的使用者，我要於登入頁申請密碼重設，透過寄至我 Email 的一次性時效連結設定新密碼，以便自行恢復系統存取。

**Priority**: P1 — 帳號自救路徑；無此機制忘記密碼只能求助 IT。依賴 US6 發信服務。

**Independent Test**: 輸入已註冊 Email 申請後於 30 分鐘內點連結完成重設並以新密碼登入；輸入未註冊 Email 得到相同回覆訊息（防列舉）；逾時連結被拒絕。

### Acceptance Scenarios

1. **Given** 使用者於登入頁點「忘記密碼」並輸入帳號（Email），**When** 送出，**Then** 不論帳號是否存在皆回覆相同訊息（DP-MSG-FORGOT-001，防帳號列舉）；若帳號存在，系統產生一次性時效 token（預設 30 分鐘）寫入 `DP_PWD_RESET`，並經發信服務（US6）以 `MODULE=DP`「密碼重設」範本寄重設信
2. **Given** 使用者於效期內點信中連結，**When** token 驗證通過，**Then** 進入重設密碼頁，輸入新密碼 + 確認新密碼，檢核複雜度與重複性後更新 `DP_USER`、寫入 `DP_PWD_HIST` 與稽核、token 即時作廢，提示（DP-MSG-FORGOT-005）
3. **Given** token 已逾時或已被使用，**When** 點連結，**Then** 拒絕並提示（DP-MSG-FORGOT-002）
4. **Given** 使用者重複申請重設，**When** 新申請成立，**Then** 產生新 token 且舊 token 立即失效（一次性）
5. **Given** 新密碼不符複雜度或與最近 N 次（預設 3）使用過之密碼相同，**When** 送出，**Then** 阻擋並提示（DP-MSG-FORGOT-003 / 004）
6. **Given** 帳號處於鎖定 / 停用狀態，**When** 申請忘記密碼，**Then** 仍回覆相同訊息；重設成功亦不解除鎖定 / 停用（仍需管理者處理或逾時解鎖）
7. **Given** 同一來源 IP + 帳號對忘記密碼端點高頻嘗試，**When** 超過速率限制，**Then** 暫時拒絕（DP-MSG-FORGOT-006）

## Functional Requirements

- **FR-DP-US3-01**: 登入頁 MUST 提供「忘記密碼」入口；申請僅需輸入帳號（Email）
- **FR-DP-US3-02**: 系統 MUST 對重新身分確認後之申請產生**一次性且具時效**之重設 token（TTL 為平台級參數，預設 30 分鐘），寫入 `DP_PWD_RESET`（TOKEN_TYPE=`PWD_RESET`）；同帳號重新申請時舊 token MUST 立即失效
- **FR-DP-US3-03**: 系統 MUST 防帳號列舉——不論帳號是否存在皆回覆相同訊息；不存在之帳號不產 token、不寄信
- **FR-DP-US3-04**: 重設信 MUST 經平台發信服務（US6）以 `DP_NOTIFY_TEMPLATE`（`MODULE=DP`、密碼重設範本）非同步寄送
- **FR-DP-US3-05**: 重設頁 MUST 驗證 token 有效性與期限；新密碼 MUST 檢核複雜度與重複性（禁止與最近 N 次相同，查 `DP_PWD_HIST`）；檢核 MUST 於伺服器端執行
- **FR-DP-US3-06**: 更新成功 MUST 以不可逆雜湊寫入 `DP_USER`、追加 `DP_PWD_HIST`、作廢 token、寫入 `DP_AUDIT_LOG`（密碼重置）
- **FR-DP-US3-07**: 密碼重設 MUST NOT 解除帳號之鎖定 / 停用狀態
- **FR-DP-US3-08**: 忘記密碼端點 MUST 實施伺服器端速率限制（來源 IP + 帳號）

## Clarifications

### Session 2026-07-20（US3 開工前自檢釐清）

- **Q（FR-05 重設密碼頁 UI）**：信中連結落點的「設定新密碼」頁 wireframe 未畫專屬 screen，UI 如何定？
  → **A：沿用 US1 強制變更頁殼樣式**（`wireframes/dp/index.html` 之 `login-force-change`：新密碼 + 確認新密碼 + 警告 Alert）。重設頁為 token 落點的獨立頁（非 overlay 分頁），欄位與版式比照強制變更頁殼；token 失效顯示 FORGOT-002、成功顯示 FORGOT-005 後導回登入。業務行為以 FR-05/06 為準，wireframe 缺 screen 不影響開發。

- **Q（FR-04 reset_link base URL 來源）**：重設信連結需前端重設頁完整 URL，base（scheme+host）從哪來？
  → **A：後端設定（`config.py` + `.env`）新增 `FRONTEND_BASE_URL`**，由後端組 `reset_link = {FRONTEND_BASE_URL}/reset-password?token=<明文token>`。**不放 DP_PARAM**——base URL 因部署環境而異（dev / staging / prod 不同），性質同 `DATABASE_URL` / `CORS_ORIGINS` / `MAIL_SERVER`，屬部署設定；dev 預設 `http://localhost:5173`（對齊既有 `CORS_ORIGINS`）。

- **Q（範本變數）**：`PWD_RESET` 範本變數以何為準？
  → **A：以種子為準**：`user_name` / `reset_link` / `expiry_minutes`，語法為單括號 `{var}`（US6 `_SafeFormatter`）。wireframe 範本編輯 modal 之示範文字 `{{TTL_MIN}}` 等為舊 mockup、已校正對齊種子。

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-FORGOT-001 | 提示 | 若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設 | FR-DP-US3-03 申請送出 |
| DP-MSG-FORGOT-002 | 錯誤 | 連結已失效，請重新申請 | FR-DP-US3-05 token 逾時 / 已用 |
| DP-MSG-FORGOT-003 | 錯誤 | 密碼不符合複雜度要求（至少 8 字元、含 3 種字元組合）| FR-DP-US3-05 複雜度 |
| DP-MSG-FORGOT-004 | 錯誤 | 不可與最近使用過之密碼相同 | FR-DP-US3-05 重複性 |
| DP-MSG-FORGOT-005 | 成功 | 密碼已更新，請以新密碼登入 | FR-DP-US3-06 完成 |
| DP-MSG-FORGOT-006 | 錯誤 | 嘗試次數過多，請稍後再試 | FR-DP-US3-08 速率限制 |

## 前置依賴

- 發信服務與 outbox（US6）、`MODULE=DP` 密碼重設範本（US9 可編輯主旨 / 內文，不可停用）
- 重設 token TTL、密碼策略、重複性次數為平台級參數（US5）
- 外部 eMail Server（SMTP）可用（跨模組介接）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §忘記密碼、§密碼與帳號安全
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP003
- 共用規則：[spec.md](spec.md) §密碼策略與帳號安全
