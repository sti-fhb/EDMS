# User Story 2 — 使用者自助註冊（UCDP002）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（登入頁・註冊頁籤）

## User Story

作為尚未有帳號的訪客，我要於登入頁自助註冊帳號（Email）、姓名與密碼，以便立即登入使用教育訓練（ET）功能。

**Priority**: P1 — 帳號來源主路徑；註冊即用（帳號建立時自動授予 ET 學員預設角色）。

**Independent Test**: 以未註冊 Email 完成註冊後即可登入，且權限管理清單（US7）中該使用者僅具 ET 學員角色、無任何 DM 角色；以已註冊 Email 註冊被阻擋；不合規密碼被阻擋。

### Acceptance Scenarios

1. **Given** 訪客於登入頁切換至「註冊」頁籤並填寫 Email / 姓名 / 密碼 / 確認密碼，**When** Email 未被註冊且密碼合規（複雜度 + 兩次一致），**Then** 建立 `DP_USER`（密碼雜湊）、透過 ET service 寫入 `ET_USER_ROLE` 授予 **ET 學員**（受訓單位標籤預設「未指派」）、提示註冊成功（DP-MSG-REGISTER-004）並跳回登入頁預填 Email
2. **Given** 註冊完成之新使用者，**When** 管理者檢視權限管理（US7），**Then** 該使用者僅具 ET 學員角色；DM 四角色皆未勾選（不自動授予，DM 存取須管理者開通）
3. **Given** 註冊時 Email 已被註冊，**When** 送出，**Then** 阻擋並提示（DP-MSG-REGISTER-001），引導改走登入或忘記密碼
4. **Given** 密碼不符複雜度（一般使用者至少 8 字元、至少 3 種字元組合），**When** 送出，**Then** 阻擋並提示（DP-MSG-REGISTER-002）
5. **Given** 兩次密碼輸入不一致，**When** 送出，**Then** 阻擋並提示（DP-MSG-REGISTER-003）
6. **Given** 註冊成功，**When** 檢視稽核（US10），**Then** 存在該帳號之建立紀錄（CREATE）與 ET 學員角色授予紀錄

## Functional Requirements

- **FR-DP-US2-01**: 登入頁 MUST 提供「註冊」頁籤，欄位：帳號（Email，必填、格式檢核）、姓名（必填）、密碼、確認密碼（必填、遮蔽顯示）
- **FR-DP-US2-02**: 系統 MUST 檢核 Email 未被註冊（`DP_USER` 唯一）、密碼符合複雜度、兩次輸入一致；檢核 MUST 於伺服器端執行
- **FR-DP-US2-03**: 檢核通過 MUST 建立 `DP_USER`（密碼不可逆雜湊、狀態啟用），並於**帳號建立當下**透過 ET service 寫入 `ET_USER_ROLE` 自動授予「學員」（唯一預設角色，受訓單位標籤預設「未指派」）；MUST NOT 授予任何 DM 角色或 ET 教師 / 管理者角色
- **FR-DP-US2-04**: 註冊成功 MUST 跳回登入頁並預填 Email，由使用者以新帳號登入（驗證密碼可用）；不寄帳號開通確認信（註冊即用）
- **FR-DP-US2-05**: 帳號建立與預設角色授予 MUST 寫入 `DP_AUDIT_LOG`
- **FR-DP-US2-06**: 首筆密碼雜湊 MUST 寫入 `DP_PWD_HIST`，作為後續密碼重複性檢核基準

## Clarifications

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
| DP-MSG-REGISTER-004 | 成功 | 註冊成功，請以新帳號登入 | FR-DP-US2-04 完成 |

## 前置依賴

- 密碼複雜度策略為平台級參數（US5）
- ET service 之「授予學員角色」介面（跨模組，契約見 [contracts/module-callbacks.md](contracts/module-callbacks.md)）
- DM 角色開通走 US7 權限管理（本 US 不涉及）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP002
- 決策：[spec.md](spec.md) Clarifications 釐清第 3 輪（預設角色僅 ET 學員、帳號建立時授予）
