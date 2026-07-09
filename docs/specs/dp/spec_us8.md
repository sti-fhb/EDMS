# User Story 8 — 個人資料維護（UCDP004）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P2 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-profile）

## User Story

作為已登入的使用者，我要維護自己的姓名、帳號（Email）與密碼，以便個人資料保持正確且變更同步生效於 ET / DM 兩系統。

**Priority**: P2 — 使用者自助作業；登入 / 註冊（P1）可先行，個資維護可隨後交付。ET / DM 不自設個資畫面，皆導向本頁。

**Independent Test**: 改姓名後 ET / DM 顯示同步更新；Email 變更走新信箱驗證後切換（期間舊 Email 仍可登入、逾時作廢）；密碼變更須驗舊密碼且新密碼過複雜度與重複性檢核。

### Acceptance Scenarios

1. **Given** 使用者進入個人資料頁編輯**姓名**，**When** 儲存，**Then** 直接更新 `DP_USER`（ET / DM 兩端同步生效）並寫入稽核
2. **Given** 使用者變更**帳號（Email）**輸入新 Email，**When** 新 Email 未被他人使用，**Then** 寄驗證信至**新 Email**（連結預設 30 分鐘有效，經 US6 發信、範本 `MODULE=DP`「帳號變更驗證」），提示（DP-MSG-PROFILE-005）；期間**舊 Email 仍可登入**（延遲生效）
3. **Given** 使用者點驗證連結且未逾時，**When** 驗證通過，**Then** 新 Email 生效、舊 Email 失效、寫入稽核；**When** 連結逾時未點，**Then** 變更作廢、舊 Email 維持（DP-MSG-PROFILE-008）
4. **Given** 新 Email 已被他人註冊，**When** 送出變更，**Then** 阻擋並提示（DP-MSG-PROFILE-006）
5. **Given** 使用者變更**密碼**（輸入舊密碼 + 新密碼 + 確認新密碼），**When** 舊密碼正確、兩次一致、符合複雜度與重複性（不與最近 N 次相同），**Then** 更新密碼雜湊、追加 `DP_PWD_HIST`、寫入稽核、提示（DP-MSG-PROFILE-007）
6. **Given** 舊密碼錯誤 / 兩次不一致 / 不符複雜度 / 與近期密碼重複，**When** 送出，**Then** 阻擋並提示對應訊息（DP-MSG-PROFILE-001～004）
7. **Given** 使用者具 ET 或 DM 管理者角色（特權帳號），**When** 變更密碼，**Then** 新密碼最小長度門檻為 **12 字元**（一般使用者 8 字元）
8. **Given** 密碼變更端點被高頻嘗試，**When** 超過速率限制，**Then** 暫時拒絕（比照 US1 / US3 速率限制）

## Functional Requirements

- **FR-DP-US8-01**: 個人資料頁 MUST 供所有已登入使用者維護**自己的**姓名 / Email / 密碼；MUST NOT 可維護他人資料（他人由 US4 管理者維護）
- **FR-DP-US8-02**: 姓名變更 MUST 直接儲存並於 ET / DM 兩端同步生效（共用 `DP_USER`）
- **FR-DP-US8-03**: Email 變更 MUST 採「新信箱驗證後切換」延遲生效——寄一次性時效驗證信（TTL 平台級參數，預設 30 分鐘）至新 Email，點連結後新 Email 生效、舊 Email 失效；驗證前舊 Email MUST 仍可登入；逾時 MUST 作廢變更；新 Email MUST 檢核未被他人使用
- **FR-DP-US8-04**: 密碼變更 MUST 驗證舊密碼正確、新密碼兩次一致、符合複雜度（一般 8 / 特權 12 字元、≥3 種字元組合）與重複性（不與最近 N 次相同，查 `DP_PWD_HIST`）；檢核 MUST 於伺服器端執行
- **FR-DP-US8-05**: 特權帳號（具 ET / DM 管理者角色者）之 12 字元門檻 MUST 於其變更密碼時適用（被指派管理者角色當下不強制改密碼）
- **FR-DP-US8-06**: 密碼更新 MUST 以不可逆雜湊儲存並追加 `DP_PWD_HIST`；姓名 / Email / 密碼異動 MUST 寫入 `DP_AUDIT_LOG`
- **FR-DP-US8-07**: 密碼變更端點 MUST 實施伺服器端速率限制（來源 IP + 帳號）
- **FR-DP-US8-08**: 本頁亦承載「強制變更密碼」情境（密碼逾效期 / 初始密碼首登，US1 導入）——完成變更前 MUST NOT 允許離開至其他功能

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-PROFILE-001 | 錯誤 | 舊密碼不正確 | FR-DP-US8-04 驗舊失敗 |
| DP-MSG-PROFILE-002 | 錯誤 | 兩次輸入之新密碼不一致 | FR-DP-US8-04 不一致 |
| DP-MSG-PROFILE-003 | 錯誤 | 密碼不符合複雜度要求（一般至少 8 字元、管理者至少 12 字元，含 3 種字元組合）| FR-DP-US8-04 / 05 複雜度 |
| DP-MSG-PROFILE-004 | 錯誤 | 不可與最近使用過之密碼相同 | FR-DP-US8-04 重複性 |
| DP-MSG-PROFILE-005 | 提示 | 驗證信已寄至新 Email，請於 30 分鐘內完成驗證；驗證前原 Email 仍可登入 | FR-DP-US8-03 變更送出 |
| DP-MSG-PROFILE-006 | 錯誤 | 此 Email 已被使用 | FR-DP-US8-03 重複 |
| DP-MSG-PROFILE-007 | 成功 | 密碼已更新 | FR-DP-US8-04 完成 |
| DP-MSG-PROFILE-008 | 錯誤 | 驗證連結已失效，Email 變更作廢，原 Email 維持有效 | FR-DP-US8-03 逾時 |

## 前置依賴

- 使用者已登入（US1）
- 驗證信經發信服務寄送（US6）、範本 `MODULE=DP`「帳號變更驗證」（US9 可編輯主旨 / 內文，不可停用）
- 密碼策略 / 驗證連結 TTL 為平台級參數（US5）
- ET / DM 個資入口以連結導向本頁（跨模組；對齊 ET UCET011、DM US9 個資分區）

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §密碼與帳號安全、§使用者 / 帳號管理
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP004
- 共用規則：[spec.md](spec.md) §密碼策略與帳號安全
