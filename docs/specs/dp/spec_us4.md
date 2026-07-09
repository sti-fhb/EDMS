# User Story 4 — 使用者管理（UCDP005，共用項）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-users）

## User Story

作為 ET 或 DM 管理者，我要於 DP 後台查詢、建立、停用 / 啟用帳號、維護基本資料並解鎖被鎖定的帳號，以便管理兩模組共用的使用者。

**Priority**: P1 — 管理者建帳號、停用離職者、解鎖為日常必要作業；帳號為共用項，任一管理者皆可操作。

**Independent Test**: 任一模組管理者可建立帳號（設初始密碼）並讓新使用者以「首次登入強制變更」流程啟用；停用帳號後該使用者於 ET / DM 皆無法再操作；解鎖後被鎖帳號可再登入。

### Acceptance Scenarios

1. **Given** ET 或 DM 管理者進入 DP 後台使用者管理頁，**When** 以 Email / 姓名 / 狀態（啟用 / 停用 / 鎖定）查詢，**Then** 列出符合之使用者清單（後端分頁）；帳號為共用項，兩模組管理者所見相同
2. **Given** 管理者點「建立帳號」填寫 Email / 姓名 / 初始密碼，**When** Email 未被使用且密碼合規，**Then** 建立 `DP_USER` 並標記「首次登入強制變更」、於帳號建立時授予 ET 學員（同 US2 規則）、提示（DP-MSG-USERS-003）
3. **Given** 管理者對某帳號執行停用，**When** 確認（DP-MSG-USERS-002），**Then** 帳號停用、ET / DM 兩端同步失效（其未逾期 token 於下次請求被拒），寫入稽核
4. **Given** 管理者對停用（含閒置 90 日被自動禁用）帳號執行啟用，**When** 確認，**Then** 帳號恢復可登入，寫入稽核
5. **Given** 某帳號因登入失敗達上限被鎖定，**When** 管理者執行「解鎖」，**Then** 失敗計數歸零、帳號即可登入，寫入稽核（DP-MSG-USERS-004）
6. **Given** 管理者編輯某使用者之基本資料（姓名 / Email），**When** 儲存且 Email 未與他人重複，**Then** 直接更新（管理者代改不走驗證信流程）並寫入稽核；Email 重複則阻擋（DP-MSG-USERS-005）
7. **Given** 管理者對**自己的帳號**執行停用或鎖定，**When** 送出，**Then** 系統阻擋並提示（DP-MSG-USERS-001，自我保護）
8. **Given** 停用他人帳號造成某模組 0 名管理者，**When** 送出，**Then** 系統允許（不檢核「至少保留 1 名管理者」，0 名時由 IT 經 DB 恢復，比照 ET / DM）

## Functional Requirements

- **FR-DP-US4-01**: 使用者管理頁 MUST 為共用項——ET / DM 管理者皆可操作全部帳號；一般使用者 MUST NOT 可存取
- **FR-DP-US4-02**: 系統 MUST 提供使用者查詢（Email / 姓名 / 狀態，後端分頁）與清單顯示（Email、姓名、狀態、鎖定狀態、最後登入時間）
- **FR-DP-US4-03**: 建立帳號 MUST 由管理者設定初始密碼（符合複雜度）並標記「首次登入強制變更」；帳號建立時 MUST 依 US2 規則授予 ET 學員預設角色；不寄開通確認信（直接可用）
- **FR-DP-US4-04**: 停用帳號 MUST 二次確認；停用後 MUST 於 ET / DM 兩端同步失效（伺服器端於每次請求檢核帳號狀態）；啟用 MUST 恢復可登入
- **FR-DP-US4-05**: 解鎖 MUST 將登入失敗計數歸零並解除鎖定狀態；閒置 90 日被自動禁用之帳號 MUST 可由管理者於本頁恢復
- **FR-DP-US4-06**: 管理者 MUST NOT 可停用 / 鎖定自己的帳號（自我保護）；系統 MUST NOT 檢核「至少保留 1 名管理者」
- **FR-DP-US4-07**: 帳號 MUST 唯一識別使用者、不得共用；帳號權限以最小權限為原則（建立時僅 ET 學員，其他角色走 US7）
- **FR-DP-US4-08**: 建立 / 停用 / 啟用 / 解鎖 / 基本資料異動 MUST 寫入 `DP_AUDIT_LOG`（含異動前後值）
- **FR-DP-US4-09**: 角色指派 MUST NOT 於本頁處理（見 US7 權限管理）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-USERS-001 | 錯誤 | 無法停用或鎖定自己的帳號 | FR-DP-US4-06 自我保護 |
| DP-MSG-USERS-002 | 確認 | 確定停用此帳號？停用後 ET / DM 兩端將同步失效 | FR-DP-US4-04 停用確認 |
| DP-MSG-USERS-003 | 成功 | 帳號已建立；使用者以初始密碼首次登入時須變更密碼 | FR-DP-US4-03 建立完成 |
| DP-MSG-USERS-004 | 成功 | 帳號已解鎖 | FR-DP-US4-05 解鎖完成 |
| DP-MSG-USERS-005 | 錯誤 | 此 Email 已被使用 | FR-DP-US4-03 / 06 Email 重複 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1；角色由 US7 指派）
- 密碼複雜度策略為平台級參數（US5）
- ET service 之「授予學員角色」介面（同 US2，跨模組）
- 閒置 90 日自動禁用由 `SCHDP001` 執行（US11）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理、§帳號鎖定
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP005
- 共用規則：[spec.md](spec.md) §模組過濾與共用項、§帳號鎖定與閒置控管
