# User Story 4 — 使用者管理（UCDP005，共用項）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-users）

## User Story

作為 ET 或 DM 管理者，我要於 DP 後台查詢、建立、停用 / 啟用帳號、維護基本資料並解鎖被鎖定的帳號，以便管理兩模組共用的使用者。

**Priority**: P1 — 管理者建帳號、停用離職者、解鎖為日常必要作業；帳號為共用項，任一管理者皆可操作。

**Independent Test**: 任一模組管理者可建立帳號（寄邀請連結信）→ 新使用者點信中連結自設密碼後啟用並登入；停用帳號後該使用者於 ET / DM 皆無法再操作；解鎖後被鎖帳號可再登入。

### Acceptance Scenarios

1. **Given** ET 或 DM 管理者進入 DP 後台使用者管理頁，**When** 以 Email / 姓名 / 狀態（啟用 / 停用 / 鎖定）查詢，**Then** 列出符合之使用者清單（後端分頁）；帳號為共用項，兩模組管理者所見相同
2. **Given** 管理者點「建立帳號」填寫 Email / 姓名（**不設密碼**），**When** Email 未被使用，**Then** 寫入待驗證表（`DP_PENDING_REGISTRATION`，`kind=ADMIN_INVITE`）並寄「帳號邀請信」（**不建 `DP_USER`、不授角色**）、提示（DP-MSG-USERS-003）；Email 重複則阻擋（DP-MSG-USERS-005）
3. **Given** 管理者對某帳號執行停用，**When** 確認（DP-MSG-USERS-002），**Then** 帳號停用、ET / DM 兩端同步失效（其未逾期 token 於下次請求被拒），寫入稽核
4. **Given** 管理者對停用（含閒置 90 日被自動禁用）帳號執行啟用，**When** 確認，**Then** 帳號恢復可登入，寫入稽核
5. **Given** 某帳號因登入失敗達上限被鎖定，**When** 管理者執行「解鎖」，**Then** 失敗計數歸零、帳號即可登入，寫入稽核（DP-MSG-USERS-004）
6. **Given** 管理者編輯某使用者之基本資料，**When** 儲存，**Then** 僅更新**姓名**並寫入稽核；**Email（登入帳號）為唯讀、管理者不可修改**（本人變更 Email 走個人資料維護 UCDP004 之雙信箱驗證流程）
7. **Given** 管理者對**自己的帳號**執行停用或鎖定，**When** 送出，**Then** 系統阻擋並提示（DP-MSG-USERS-001，自我保護）
8. **Given** 停用他人帳號造成某模組 0 名管理者，**When** 送出，**Then** 系統允許（不檢核「至少保留 1 名管理者」，0 名時由 IT 經 DB 恢復，比照 ET / DM）
9. **Given** 受邀使用者點邀請信連結進入啟用頁，**When** 於效期內設定符合複雜度之密碼，**Then** 建立 `DP_USER`（`ACTIVE`）、依 US2 規則授予 ET 學員、寫入稽核、消費待驗證列，使用者可即以該 Email 登入（**無須再強制變更密碼**）
10. **Given** 邀請逾期或使用者未收到信，**When** 管理者於「待啟用邀請」頁籤執行**重寄邀請**或**取消邀請**，**Then** 重寄＝作廢舊 token、產新並重寄（DP-MSG-USERS-006）；取消＝刪除該待驗證列（DP-MSG-USERS-007）

## Functional Requirements

- **FR-DP-US4-01**: 使用者管理頁 MUST 為共用項——ET / DM 管理者皆可操作全部帳號；一般使用者 MUST NOT 可存取
- **FR-DP-US4-02**: 系統 MUST 提供使用者查詢（Email / 姓名 / 狀態，後端分頁）與清單顯示（Email、姓名、狀態、鎖定狀態、最後登入時間）
- **FR-DP-US4-03**: 建立帳號 MUST 採**邀請連結信**——管理者僅填 Email / 姓名（**不設密碼**），系統寫入 `DP_PENDING_REGISTRATION`（`kind=ADMIN_INVITE`、`pwd_hash` 留空）並寄邀請信；**啟用前不建 `DP_USER`、不授角色**（比照 US2 自助註冊之待驗證機制）
- **FR-DP-US4-04**: 停用帳號 MUST 二次確認；停用後 MUST 於 ET / DM 兩端同步失效（伺服器端於每次請求檢核帳號狀態）；啟用 MUST 恢復可登入
- **FR-DP-US4-05**: 解鎖 MUST 將登入失敗計數歸零並解除鎖定狀態；閒置 90 日被自動禁用之帳號 MUST 可由管理者於本頁恢復
- **FR-DP-US4-06**: 管理者 MUST NOT 可停用 / 鎖定自己的帳號（自我保護）；系統 MUST NOT 檢核「至少保留 1 名管理者」
- **FR-DP-US4-07**: 帳號 MUST 唯一識別使用者、不得共用；帳號權限以最小權限為原則（啟用時僅授 ET 學員，其他角色走 US7）
- **FR-DP-US4-08**: 邀請寄送 / 重寄 / 取消邀請 / 使用者經邀請啟用 / 停用 / 啟用 / 解鎖 / 姓名異動 MUST 寫入 `DP_AUDIT_LOG`（含異動前後值）
- **FR-DP-US4-09**: 角色指派 MUST NOT 於本頁處理（見 US7 權限管理）
- **FR-DP-US4-10**: 使用者啟用（點邀請連結）MUST 於效期內自設符合複雜度之密碼；通過後 MUST 建立 `DP_USER`（`ACTIVE`）、依 US2 規則授予 ET 學員預設角色、寫入稽核並消費待驗證列；啟用副作用僅於此步落地，MUST NOT 需要「首次登入強制變更」
- **FR-DP-US4-11**: 管理者 MUST 可於「待啟用邀請」對邀請中帳號**重寄邀請**（作廢舊 token、產新並重寄）與**取消邀請**（刪除待驗證列）；此為管理者動作（需認證、不防列舉），與 US2 匿名重寄端點分離
- **FR-DP-US4-12**: 編輯帳號 MUST 僅可修改**姓名**；**Email（登入帳號）MUST 為唯讀**、管理者不可代改；使用者本人變更 Email 走個人資料維護（UCDP004）之雙信箱驗證流程

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-USERS-001 | 錯誤 | 無法停用或鎖定自己的帳號 | FR-DP-US4-06 自我保護 |
| DP-MSG-USERS-002 | 確認 | 確定停用此帳號？停用後 ET / DM 兩端將同步失效 | FR-DP-US4-04 停用確認 |
| DP-MSG-USERS-003 | 成功 | 邀請信已寄出，使用者需經連結設定密碼後啟用 | FR-DP-US4-03 邀請寄送 |
| DP-MSG-USERS-004 | 成功 | 帳號已解鎖 | FR-DP-US4-05 解鎖完成 |
| DP-MSG-USERS-005 | 錯誤 | 此 Email 已被使用 | FR-DP-US4-03 建立 Email 重複（編輯不觸發，Email 唯讀）|
| DP-MSG-USERS-006 | 成功 | 邀請信已重寄 | FR-DP-US4-11 重寄邀請 |
| DP-MSG-USERS-007 | 成功 | 已取消邀請 | FR-DP-US4-11 取消邀請 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1；角色由 US7 指派）
- 密碼複雜度策略為平台級參數（US5）
- ET service 之「授予學員角色」介面（同 US2，跨模組；授予時機為**使用者啟用時**，非建立時）
- 待驗證表 `DP_PENDING_REGISTRATION` 與 token / 寄信 / 驗證機制（重用 US2 #56；需 `pwd_hash` 改 **nullable**、新增 **`kind`** 欄位區分自助註冊 / 管理者邀請）
- 個人資料維護（UCDP004）之本人換 Email 流程，為使用者變更 Email 之唯一路徑（US4 不代改）
- 閒置 90 日自動禁用由 `SCHDP001` 執行（US11）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §使用者 / 帳號管理、§帳號鎖定
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP005
- 共用規則：[spec.md](spec.md) §模組過濾與共用項、§帳號鎖定與閒置控管
