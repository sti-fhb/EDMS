# User Story 2 — 使用者自助註冊（UCDP002）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（登入頁・註冊頁籤）

## User Story

作為尚未有帳號的訪客，我要於登入頁自助註冊帳號（Email）、姓名與密碼，並完成 Email 驗證後登入使用教育訓練（ET）功能。

**Priority**: P1 — 帳號來源主路徑；**Email 驗證後啟用**（驗證通過時自動授予 ET 學員預設角色）。

**Independent Test**: 以未註冊 Email 送出註冊後收到驗證信、帳號驗證前無法登入；點連結驗證通過後可登入，且權限管理清單（US7）中該使用者僅具 ET 學員角色、無任何 DM 角色；以已驗證 Email 註冊被阻擋；不合規密碼被阻擋。

### Acceptance Scenarios

1. **Given** 訪客於「註冊」頁籤填寫 Email / 姓名 / 密碼 / 確認密碼，**When** Email 未被已驗證帳號佔用且密碼合規（複雜度 + 兩次一致），**Then** 寫入待驗證表（**不建 `DP_USER`**）、寄「註冊驗證信」至該 Email、分頁內提示驗證信已寄（DP-MSG-REGISTER-004）
2. **Given** 已寫入待驗證表，**When** 使用者點驗證連結且未逾時，**Then** 建立 `DP_USER`（`ACTIVE`）、透過 ET service 授予 **ET 學員**、寫首筆歷程與雙稽核、刪待驗證列、提示帳號已啟用（DP-MSG-REGISTER-005）並導登入
3. **Given** 未驗證帳號（僅在待驗證表），**When** 以其 Email 嘗試登入，**Then** 回專屬提示「尚未完成 Email 驗證」（DP-MSG-REGISTER-008 / DP_AUTH_010）並提供重寄，MUST NOT 回「查無此帳號」
4. **Given** 驗證連結逾時 / 無效，**When** 點連結，**Then** 阻擋並提示（DP-MSG-REGISTER-006 / 007）；使用者可自助重寄（DP-MSG-REGISTER-009，防列舉）
5. **Given** 驗證完成之新使用者，**When** 管理者檢視權限管理（US7），**Then** 該使用者僅具 ET 學員角色；DM 四角色皆未勾選（不自動授予）
6. **Given** 註冊時 Email 已被**已驗證帳號**佔用，**When** 送出，**Then** 阻擋並提示（DP-MSG-REGISTER-001）；已在待驗證表（未驗證）→ 覆蓋 + 重寄（新註冊語意）
7. **Given** 密碼不符複雜度 / 兩次不一致，**When** 送出，**Then** 阻擋並提示（DP-MSG-REGISTER-002 / 003）
8. **Given** 驗證通過（AC2），**When** 檢視稽核（US10），**Then** 存在該帳號之建立紀錄（CREATE）與 ET 學員角色授予紀錄

## Functional Requirements

- **FR-DP-US2-01**: 登入頁 MUST 提供「註冊」頁籤，欄位：帳號（Email，必填、格式檢核）、姓名（必填）、密碼、確認密碼（必填、遮蔽顯示）
- **FR-DP-US2-02**: 系統 MUST 檢核 Email 未被註冊（`DP_USER` 唯一）、密碼符合複雜度、兩次輸入一致；檢核 MUST 於伺服器端執行
- **FR-DP-US2-03**: 檢核通過 MUST **不建立 `DP_USER`**，改將註冊申請（Email / 姓名 / 密碼不可逆雜湊 + 一次性驗證 token 之 SHA-256 + 效期）寫入待驗證表 `DP_PENDING_REGISTRATION`（EMAIL 唯一）；Email 已在 pending（未驗證）→ 覆蓋該筆（換新 token）＝重寄語意（2026-07-21 釐清，方案 B）
- **FR-DP-US2-04**: 註冊成功 MUST 寄「註冊驗證信」（經 US6 發信、範本 `MODULE=DP`「ACCOUNT_VERIFY」）至該 Email，內含一次性時效驗證連結（TTL 平台級參數，預設 30 分鐘）；**帳號於驗證通過前不可登入**（Email 驗證後啟用，**推翻原「註冊即用、不寄開通確認信」**）
- **FR-DP-US2-04a**: 使用者點驗證連結且未逾時，系統 MUST 建立 `DP_USER`（狀態 `ACTIVE`、密碼不可逆雜湊）、透過 ET service 授予「學員」（唯一預設角色）、寫首筆 `DP_PWD_HIST`、寫入雙稽核（帳號 CREATE + 角色授予），並刪除待驗證列；MUST NOT 授予任何 DM 角色或 ET 教師 / 管理者角色。冪等：建 `DP_USER` 撞 `UQ_DP_USER_EMAIL`（重複 / 競態確認）→ 乾淨拒絕、不重複建
- **FR-DP-US2-04b**: 驗證連結逾時 / 無效 MUST 拒絕並提示；使用者 MUST 可自助**重寄**驗證信（僅對待驗證帳號、作廢舊 token 產新、速率限制、防列舉——無論 Email 是否有待驗證列一律回相同訊息）
- **FR-DP-US2-04c**: 未驗證帳號（僅在待驗證表、不在 `DP_USER`）嘗試登入時 MUST 回專屬提示「尚未完成 Email 驗證」（引導驗證 / 重寄），MUST NOT 回「查無此帳號」
- **FR-DP-US2-05**: 帳號建立與預設角色授予 MUST 寫入 `DP_AUDIT_LOG`（於驗證步 FR-04a，operator = 新使用者本人 USER_ID）
- **FR-DP-US2-06**: 首筆密碼雜湊 MUST 寫入 `DP_PWD_HIST`（於驗證步 FR-04a），作為後續密碼重複性檢核基準

## Clarifications

### Session 2026-07-21（改為 Email 驗證後啟用，#56）

- **決策：自助註冊改為「Email 驗證後啟用」**，**推翻**原「註冊即用、不寄開通確認信」（原 FR-DP-US2-04、spec.md「無 ACCOUNT_CONFIRM 開通信」）。理由：(1) 與 US8 改 Email「驗證後切換」一致；(2) 假 / 打錯的 Email 使帳號無法自救（忘記密碼、通知皆靠 Email）。
- **架構：方案 B（驗證前不寫 DP_USER）**。未驗證註冊暫存於新表 `DP_PENDING_REGISTRATION`；驗證通過才 INSERT `DP_USER`。`DP_USER` 只存已驗證帳號，登入 / 忘記密碼 / 使用者管理不必處理未驗證半成品。
- **啟用副作用移至驗證步**（FR-04a）：授 ET 學員、雙稽核、首筆 `DP_PWD_HIST`。
- **重複註冊 / 重寄 / 未驗證登入 / TTL / 冪等**：見 FR-04~04c 與新增訊息碼。TTL 30 分（沿用既有 token，不新增參數）。
- **US4 無耦合**：未驗證帳號不在 DP_USER，US4「啟用」僅對 `DISABLED`。

### Session 2026-07-20（US2 開工前自檢釐清）

- **Q（FR-05 角色授予稽核歸屬）**：「授予 ET 學員」這筆稽核由 DP 還是 ET 寫？（US2 開發時 ET 以 stub 先行、stub 不會寫任何稽核，若期待 ET 寫則 AC6 於 US2 無法驗）
  → **A：由 DP 於註冊流程寫入**。DP 呼叫 ET `grant_default_student_role`（stub）後，於**同交易內**自行經 `SRVDP003.log_action` 寫一筆「授予預設 ET 學員角色」稽核（`MODULE=DP`）。如此 ET 尚為 stub 時 AC6（存在角色授予紀錄）即可驗；ET 模組實作後是否於自身另記由 ET 自理、不影響 US2 驗收。兩筆稽核（帳號 CREATE + 角色授予）皆經 SRVDP003 寫入 `DP_AUDIT_LOG`。

- **Q（自助註冊稽核 operator_id）**：自助註冊無登入操作者，CREATE / 角色授予稽核之 `operator_id`（`CREATED_USER`）填誰？
  → **A：填新建立之使用者本人 USER_ID**。自助註冊為本人行為，operator 即該新帳號，語意最準且稽核可追溯至帳號自身。（對照：US4 管理者代建填管理者 USER_ID。）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-REGISTER-001 | 錯誤 | 此 Email 已被註冊，請直接登入或使用忘記密碼 | FR-DP-US2-02 Email 重複 |
| DP-MSG-REGISTER-002 | 錯誤 | 密碼不符合複雜度要求（至少 8 字元、含大小寫英文 / 數字 / 特殊符號至少 3 種）| FR-DP-US2-02 複雜度 |
| DP-MSG-REGISTER-003 | 錯誤 | 兩次輸入之密碼不一致 | FR-DP-US2-02 不一致 |
| DP-MSG-REGISTER-004 | 提示 | 驗證信已寄至您的信箱，請於 30 分鐘內點連結完成驗證 | FR-DP-US2-04 註冊送出 |
| DP-MSG-REGISTER-005 | 成功 | 帳號已啟用，請以新帳號登入 | FR-DP-US2-04a 驗證通過 |
| DP-MSG-REGISTER-006 | 錯誤 | 驗證連結無效 | FR-DP-US2-04b token 無效 |
| DP-MSG-REGISTER-007 | 錯誤 | 驗證連結已失效，請重新申請 | FR-DP-US2-04b 逾時 |
| DP-MSG-REGISTER-008 | 錯誤 | 此帳號尚未完成 Email 驗證，請至信箱點驗證連結或重新寄送 | FR-DP-US2-04c 未驗證登入 |
| DP-MSG-REGISTER-009 | 提示 | 若該 Email 有待驗證的註冊，驗證信將重新寄出，請於 30 分鐘內完成驗證 | FR-DP-US2-04b 重寄（防列舉） |

## 前置依賴

- 密碼複雜度策略為平台級參數（US5）
- ET service 之「授予學員角色」介面（跨模組，契約見 [contracts/module-callbacks.md](contracts/module-callbacks.md)）
- DM 角色開通走 US7 權限管理（本 US 不涉及）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP002
- 決策：[spec.md](spec.md) Clarifications 釐清第 3 輪（預設角色僅 ET 學員、帳號建立時授予）
