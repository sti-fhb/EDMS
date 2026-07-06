# User Story 15 — UCET015 通知信範本維護（系統設定 -「通知範本」分頁，ET09）

> 對應 UC：UCET015 ｜ 功能選項：ET09（通知信範本維護）｜ Priority：P3 ｜ Wireframe：通知範本（wireframe 未含此畫面，屬系統設定分頁）｜ 返回總檔：[spec.md](spec.md)
> 2026-07-02 新增（客戶需求變更 items 2/4 之配套：所有通知信採統一範本，由管理者維護）。
> ET07（權限與標籤）與 ET09（通知範本）合併於管理者單一「**系統設定**」畫面之分頁（比照 DM09）；本 US 對應「**通知範本**」分頁。功能作業代碼 ET09 沿用。

管理者於「系統設定」之「通知範本」分頁（ET09）管理課程 / 學習相關通知信之統一範本（`ET_NOTIFY_TEMPLATE`，**6 類**內建範本代碼，seed 於部署時寫入）：可編輯各範本之**主旨與內文**（支援變數如 `{{COURSE_NAME}}`、`{{OPEN_START_AT}}`、`{{OPEN_END_AT}}`、`{{COURSE_URL}}`、`{{USER_NAME}}`）並**啟用 / 停用**該範本（比照 DM；停用後該類信件不寄送），**不可新增 / 刪除範本代碼**；另可調整排程參數（週報執行時間 `WEEKLY_STAT_DAY_TIME`、加急提醒天數 `URGENT_REMIND_DAYS`）。**教師不可逐課修改信件內容**——所有寄出信件一律依本表範本渲染，確保內容統一。**密碼重設（US2）與帳號變更驗證（US10）之信件不納入本畫面**，採系統預設固定範本、不開放編輯（帳號安全信件，2026-07-02 變更）。

**Priority**: P3

**Why this priority**: 內建 seed 範本即可支撐所有寄信功能運作；本 US 為管理者調整範本文案之輔助作業。

**Independent Test**: 管理者修改「課程邀請通知」範本主旨後儲存，觸發一次課程發布邀請，驗證寄出信件採用新主旨且變數正確帶值；教師端無任何信件編輯入口。

**Acceptance Scenarios**:

### 範本清單與編輯

1. **Given** 管理者進入 ET09，**When** 系統載入，**Then** 列出 **6 類**內建範本：課程邀請通知（COURSE_INVITE）、課程邀請彙整通知（COURSE_INVITE_DIGEST）、課程內容更新通知（COURSE_UPDATE）、每週未看提醒（WEEKLY_REMIND）、截止前加急提醒（URGENT_REMIND）、週報（WEEKLY_REPORT）；**密碼重設與帳號變更驗證不在清單內**（系統預設固定範本，不可編輯）
2. **Given** 管理者點擊某範本「編輯」，**When** 系統載入編輯頁，**Then** 顯示主旨與內文編輯欄位，並列出該範本可用之變數清單（點擊可插入）
3. **Given** 管理者修改主旨 / 內文後儲存，**When** 系統檢核通過（主旨與內文不可為空），**Then** 寫入 ET_NOTIFY_TEMPLATE 並更新版本號（樂觀鎖）；之後所有該類信件依新內容渲染
4. **Given** 範本內文含未定義之變數（如 `{{UNDEFINED_VAR}}`），**When** 儲存，**Then** 系統警告提示未定義變數（可仍儲存，寄出時該變數以空字串帶入）
5. **Given** 兩位管理者同時編輯同一範本，**When** 後儲存者版本不符，**Then** 系統拒絕並提示「內容已被其他使用者變更，請重新整理後再儲存」
6. **Given** 管理者檢視範本清單，**When** 嘗試新增或刪除範本，**Then** 無此功能（範本代碼固定，僅可編輯內容）

### 啟用 / 停用（2026-07-02 新增，比照 DM）

6a. **Given** 管理者於範本詳情將某範本「啟用」開關切為**停用**，**When** 儲存，**Then** ET_NOTIFY_TEMPLATE.IS_ACTIVE = false；之後該類信件**不寄送**（對應觸發事件照常運作，僅不發此信）；清單標示「已停用」
6b. **Given** 某範本已停用，**When** 其觸發事件發生（如停用「課程邀請通知」時課程發布），**Then** 系統照常執行事件（自動加入學員）但**不寄該封信**
6c. **Given** 管理者將已停用範本切回**啟用**，**When** 儲存，**Then** IS_ACTIVE = true；之後該類信件恢復寄送
6d. **Given** 密碼重設 / 帳號變更驗證信件，**When** 管理者檢視 ET09，**Then** 不在清單內、無啟用 / 停用開關（系統固定範本、不可停用；帳號安全信件）

### 排程參數調整

7. **Given** 管理者於 ET09 排程參數區，**When** 修改「週報執行時間」（`WEEKLY_STAT_DAY_TIME`）並儲存，**Then** SCHET001 下次依新時間執行
8. **Given** 管理者修改「加急提醒天數」（`URGENT_REMIND_DAYS`，正整數檢核），**When** 儲存，**Then** SCHET002 依新天數判定加急提醒時點

### 權限與統一性

9. **Given** 非管理者角色（教師 / 學員），**When** 嘗試進入 ET09，**Then** 系統拒絕存取（選單不顯示）
10. **Given** 教師於 ET02 執行 Email 邀請（[spec_us8.md](spec_us8.md) US8），**When** 預覽信件，**Then** 僅可預覽、**不可編輯**主旨與內文（統一範本）

---

## Functional Requirements

- **FR-ET-US15-01**: 系統 MUST 於 ET09「通知範本」分頁列出 6 類內建範本（COURSE_INVITE、COURSE_INVITE_DIGEST、COURSE_UPDATE、WEEKLY_REMIND、URGENT_REMIND、WEEKLY_REPORT）並提供編輯各範本之主旨與內文；MUST NOT 提供新增或刪除範本代碼之功能（範本代碼固定）
- **FR-ET-US15-02**: 系統 MUST 於範本編輯頁列出該範本可用之變數清單（如 `{{COURSE_NAME}}`、`{{OPEN_START_AT}}`、`{{OPEN_END_AT}}`、`{{COURSE_URL}}`、`{{USER_NAME}}`），並支援點擊插入
- **FR-ET-US15-03**: 系統 MUST 於儲存範本時檢核主旨與內文皆不可為空，通過後寫入 ET_NOTIFY_TEMPLATE 並更新版本號；之後所有該類信件 MUST 依新內容渲染
- **FR-ET-US15-04**: 內文含未定義變數時，系統 MUST 提示警告但仍允許儲存，並於寄出時將該變數以空字串帶入
- **FR-ET-US15-05**: 系統 MUST 以版本號（樂觀鎖）控制並行編輯；後儲存者版本不符時 MUST 拒絕儲存並提示「內容已被其他使用者變更，請重新整理後再儲存」
- **FR-ET-US15-06**: 系統 MUST 提供各範本之啟用 / 停用開關；停用（IS_ACTIVE = false）時該類信件 MUST NOT 寄送，惟其觸發事件（如課程發布之自動加入學員）MUST 照常運作；切回啟用（IS_ACTIVE = true）後 MUST 恢復寄送
- **FR-ET-US15-07**: 系統 MUST 將密碼重設（US2）與帳號變更驗證（US10）信件排除於 ET09 清單之外，採系統固定範本，MUST NOT 開放編輯或啟用 / 停用（帳號安全信件）
- **FR-ET-US15-08**: 系統 MUST 提供排程參數調整：週報執行時間（`WEEKLY_STAT_DAY_TIME`）供 SCHET001 下次依新時間執行、加急提醒天數（`URGENT_REMIND_DAYS`，須為正整數）供 SCHET002 依新天數判定加急提醒時點
- **FR-ET-US15-09**: 系統 MUST 僅允許管理者存取 ET09；非管理者角色（教師 / 學員）MUST 被拒絕存取且選單不顯示
- **FR-ET-US15-10**: 系統 MUST 使所有寄出信件一律依 ET_NOTIFY_TEMPLATE 統一範本渲染；教師於 ET02 Email 邀請（[US8](spec_us8.md)）等情境僅可預覽，MUST NOT 逐課編輯主旨與內文

---

## 系統訊息

各訊息類型（錯誤 / 警告 / 確認 / 成功 / 提示）定義見 [spec.md](spec.md) §Requirements。

| 訊息代碼 | 類型 | 訊息內容 | 觸發情境 |
|---------|------|---------|---------|
| ET-MSG-ET09-001 | 成功 | 範本已儲存 | 場景 3：編輯範本主旨 / 內文並儲存 |
| ET-MSG-ET09-002 | 錯誤 | 主旨與內文不可為空 | 場景 3：必填未填 |
| ET-MSG-ET09-003 | 警告 | 內文含未定義變數，寄出時將以空字串帶入；仍可儲存 | 場景 4：含未定義變數 |
| ET-MSG-ET09-004 | 錯誤 | 內容已被其他使用者變更，請重新整理後再儲存 | 場景 5：樂觀鎖版本衝突 |
| ET-MSG-ET09-005 | 提示 | 已停用此範本，該類信件將不寄送（觸發事件照常運作）| 場景 6a/6b：停用範本 |
| ET-MSG-ET09-006 | 成功 | 已啟用此範本，該類信件恢復寄送 | 場景 6c：啟用範本 |
| ET-MSG-ET09-007 | 錯誤 | 加急提醒天數須為正整數 | 場景 8：排程參數檢核 |
| ET-MSG-ET09-008 | 錯誤 | 您無權限存取此頁 | 場景 9：非管理者嘗試進入 ET09 |

---

## 相關 Clarifications 摘錄

- 寄出內容統一：管理者改範本即全系統生效，教師不需（也不可）逐課調整（2026-07-02 客戶確認）
- 範本代碼與觸發對應之權威清單見 [spec.md](spec.md) §通知信統一範本 與 data-model.md ET_NOTIFY_TEMPLATE
- 範本異動屬參數異動性質；異動記錄依標準稽核欄位（UPDATED_USER / UPDATED_DATE）

---

## 前置依賴

- 6 類可維護範本 seed 已於部署時寫入（per [plan.md](plan.md) §系統初始化）；密碼重設 / 帳號變更驗證採系統固定範本，不在本畫面
- 排程 SCHET001 / SCHET002 已註冊（[spec_us14.md](spec_us14.md) US14）
- 管理者角色由 [spec_us1.md](spec_us1.md) US1 指派

---

## 相關文件

- 模組總覽與跨 US 規則：[spec.md](spec.md)
- 資料模型：[data-model.md](data-model.md)
- 需求清單：[../../requirements/RQET.md](../../requirements/RQET.md)
- 使用案例：[../../use-cases/et/usecases.md](../../use-cases/et/usecases.md)
- 畫面 Wireframe：[ET wireframe](../../wireframes/et/index.html)
