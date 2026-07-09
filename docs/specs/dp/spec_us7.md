# User Story 7 — 權限管理（角色 + 標籤 / 可見對象指派）（UCDP010）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P1 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-roles）

## User Story

作為 ET 或 DM 管理者，我要於 DP 後台的權限管理頁對使用者指派本模組的角色與標籤 / 可見對象授權，以便開通使用者於各模組的功能權限（ET 學員以外之所有角色皆由此開通）。

**Priority**: P1 — ET 學員以外所有角色（ET 教師 / 管理者、DM 全部四角色含閱覽者）之唯一開通路徑；亦是其他管理者角色的產生路徑。

**Independent Test**: ET 管理者於同一列對使用者勾選 ET 角色與受訓單位標籤後即時生效（寫入 `ET_USER_ROLE` / `ET_USER_TAG`）；DM 管理者對使用者勾選閱覽者後該使用者方可進入 DM；ET 管理者看不到 DM 之指派區。

### Acceptance Scenarios

1. **Given** ET 管理者進入權限管理頁，**When** 查詢使用者，**Then** 每列顯示該使用者之 **ET 角色**（管理者 / 教師 / 學員）核取方塊與**受訓單位標籤**多選；**不顯示** DM 之角色與授權區
2. **Given** DM 管理者進入權限管理頁，**When** 查詢使用者，**Then** 每列顯示 **DM 角色**（管理者 / 編輯者 / 審核者 / 閱覽者）核取方塊與**可見對象 / 單位授權**多選（主要對閱覽者有意義）；**不顯示** ET 區；兼具兩模組管理者身分者兩區皆見
3. **Given** 管理者於同一列勾選 / 取消角色與標籤（兩維度獨立、可各自設定），**When** 儲存，**Then** 透過模組 service 寫入模組表——角色 → `ET_USER_ROLE` / `DM_USER_ROLE`、標籤 → `ET_USER_TAG`、可見對象授權 → DM 授權表——即時生效並提示（DP-MSG-ROLES-002）
4. **Given** 同一使用者被勾選多個角色，**When** 儲存，**Then** 允許（多角色、權限取聯集）；角色種類為固定 enum，畫面**無**「新增角色種類」功能
5. **Given** 當前登入之管理者取消**自己**之（本模組）管理者角色，**When** 儲存，**Then** 模組 service 阻擋並提示（DP-MSG-ROLES-001，自我保護；判定在模組）
6. **Given** 管理者 A 取消管理者 B 之管理者角色，**When** 儲存，**Then** 允許（不檢核「至少保留 1 名管理者」）
7. **Given** 角色 / 標籤指派異動完成，**When** 檢視稽核（US10），**Then** 存在對應紀錄（資安事件，含異動前後值）
8. **Given** ET 管理者以直接呼叫 API 之方式指派 DM 角色，**When** 請求到達，**Then** 伺服器端拒絕（DP-MSG-ROLES-003）

## Functional Requirements

- **FR-DP-US7-01**: 權限管理頁 MUST 按模組過濾——ET 管理者僅見 / 僅改 ET 角色與標籤、DM 管理者僅見 / 僅改 DM 角色與可見對象授權，互不可見；過濾 MUST 於伺服器端 enforce
- **FR-DP-US7-02**: 角色與標籤 / 可見對象 MUST 於**同一頁同一列**指派（對齊 ET / DM 現行權限管理）；兩維度獨立、可各自設定
- **FR-DP-US7-03**: 指派結果 MUST 透過模組 service 寫入模組表（`ET_USER_ROLE` / `DM_USER_ROLE` / `ET_USER_TAG` / DM 可見對象授權）；平台 MUST NOT 自持指派資料、MUST NOT 做全域 RBAC、MUST NOT 定義角色能力（判定與 enforce 在模組）
- **FR-DP-US7-04**: 角色種類 MUST 為固定 enum（無新增角色種類）；同一使用者可多角色、權限取聯集；勾選 / 取消 MUST 即時生效
- **FR-DP-US7-05**: 標籤 / 可見對象之可選清單 MUST 讀自 `DP_PARAM` 定義（僅列啟用中項，US5）；本頁只做「指派（誰配誰）」
- **FR-DP-US7-06**: 「取消自己之管理者角色」之阻擋（自我保護）與「不檢核至少 1 名管理者」由**模組 service** 判定（比照 ET FR-ET-US1-04/05、DM FR-006）；DP 畫面 MUST 呈現模組回傳之阻擋訊息
- **FR-DP-US7-07**: 角色 / 標籤指派異動屬資安事件，MUST 寫入 `DP_AUDIT_LOG`（含異動前後值）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-ROLES-001 | 錯誤 | 無法取消自己的管理者角色 | FR-DP-US7-06 自我保護 |
| DP-MSG-ROLES-002 | 成功 | 角色 / 標籤已更新並即時生效 | FR-DP-US7-03 儲存完成 |
| DP-MSG-ROLES-003 | 錯誤 | 無權限維護此模組之角色指派 | FR-DP-US7-01 越權 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1）；初始管理者由建置時預設指派（IT 經 DB 寫入）
- 標籤 / 可見對象定義清單存 `DP_PARAM`（US5）
- ET / DM 模組 service 之角色 / 標籤寫入介面與自我保護判定（跨模組，契約見 contracts/）
- 新帳號之 ET 學員預設角色於帳號建立時授予（US2 / US4），非本頁操作

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §權限管理（角色 + 標籤 / 可見對象指派）
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP010
- 模組端對應規格：[../et/spec_us1.md](../et/spec_us1.md)、[../dm/spec_us1.md](../dm/spec_us1.md)
- 共用規則：[spec.md](spec.md) §定義 vs 關聯分層、§跨模組共用規則（角色分治）
