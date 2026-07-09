# User Story 9 — 通知範本維護（UCDP011）

> 返回總檔：[spec.md](spec.md) | 模組：平台（DP）| Priority：P2 | Wireframe：[dp/index.html](../../wireframes/dp/index.html)（dp-templates）

## User Story

作為 ET 或 DM 管理者，我要於 DP 後台編輯本模組的通知範本（主旨 / 內文 / 管道 / 啟停），以便通知內容集中維護，發信服務（US6）以最新範本渲染。

**Priority**: P2 — 範本有內建預設值即可運作；編輯功能可於發信服務（P1）之後交付。

**Independent Test**: ET 管理者僅見 `MODULE=ET` 與 `MODULE=DP` 範本、看不到 `MODULE=DM`；編輯主旨內文後 US6 立即以新內容渲染；DP 系統信可編輯但停用 / 刪除被阻擋；並行編輯觸發版本衝突提示。

### Acceptance Scenarios

1. **Given** ET 管理者進入通知範本頁，**When** 頁面載入，**Then** 列出 `MODULE=ET` 之範本與 `MODULE=DP` 系統信；`MODULE=DM` 範本**不顯示**；DM 管理者反之（見 DM + DP）
2. **Given** 管理者選取範本編輯主旨、內文、管道（Email / 站內 / 兩者）、啟用停用，**When** 儲存且版本未衝突，**Then** 寫入 `DP_NOTIFY_TEMPLATE`（版本 +1）、寫入稽核、提示（DP-MSG-TEMPLATES-003）；後續 US6 發信即以新範本渲染
3. **Given** 範本被停用，**When** 模組觸發該事件，**Then** 該類 Email 不寄、觸發事件照常運作（見 US6）
4. **Given** 範本為 DP 系統信（`MODULE=DP`：密碼重設 / 帳號變更驗證 / 密碼到期提醒），**When** 管理者嘗試停用或刪除，**Then** 阻擋並提示（DP-MSG-TEMPLATES-001）；主旨 / 內文仍可編輯（兩管理者皆可，共用項）
5. **Given** 兩管理者同時編輯同一範本，**When** 後儲存者之版本落後，**Then** 拒絕儲存並提示重新載入（DP-MSG-TEMPLATES-002，樂觀鎖）
6. **Given** 管理者檢視範本清單，**When** 尋找新增 / 刪除範本功能，**Then** 無此功能——事件（`TEMPLATE_CODE`）固定，內容不同的通知＝同表不同列，由系統種子資料建立
7. **Given** ET 管理者以直接呼叫 API 之方式編輯 `MODULE=DM` 範本，**When** 請求到達，**Then** 伺服器端拒絕（DP-MSG-TEMPLATES-004）
8. **Given** 範本管道設定含「站內」，**When** 儲存，**Then** 允許——惟站內訊息之發送與呈現由各模組自理，本欄位僅作為該事件是否寄 Email 之開關依據

## Functional Requirements

- **FR-DP-US9-01**: 通知範本 MUST 統一存 `DP_NOTIFY_TEMPLATE`（`MODULE` + `TEMPLATE_CODE` 唯一），欄位含主旨、內文、可用變數、管道、啟用停用、版本
- **FR-DP-US9-02**: 編輯頁 MUST 按 `MODULE` 過濾——ET 管理者編輯 `MODULE=ET`、DM 管理者編輯 `MODULE=DM`，互不可見；`MODULE=DP` 系統信為共用項、兩管理者皆可編輯；過濾 MUST 於伺服器端 enforce
- **FR-DP-US9-03**: `MODULE=DP` 系統信（密碼重設 / 帳號變更驗證 / 密碼到期提醒）MUST NOT 允許停用或刪除（帳號安全信）；主旨 / 內文可編輯
- **FR-DP-US9-04**: 事件（`TEMPLATE_CODE`）MUST 固定不可新增 / 刪除；各模組事件之啟停語意由模組規格定義（如 DM 9 項事件、未讀提醒之統一控制）
- **FR-DP-US9-05**: 儲存 MUST 採版本樂觀鎖；版本衝突 MUST 拒絕並提示重載
- **FR-DP-US9-06**: 範本異動 MUST 寫入 `DP_AUDIT_LOG`（含異動前後值）；儲存後 US6 發信 MUST 即以最新啟用中範本渲染
- **FR-DP-US9-07**: 管道欄位僅作為該事件**是否寄 Email** 之開關依據；站內訊息之儲存與 UI 由各模組自理（DP 不設站內訊息表）

## 系統訊息

| 訊息代碼 | 類型 | 訊息內容 | 觸發 / 對應 FR |
|---------|------|---------|---------------|
| DP-MSG-TEMPLATES-001 | 錯誤 | 系統信不可停用或刪除（主旨與內文可編輯）| FR-DP-US9-03 系統信保護 |
| DP-MSG-TEMPLATES-002 | 警告 | 內容已被他人修改，請重新載入後再儲存 | FR-DP-US9-05 版本衝突 |
| DP-MSG-TEMPLATES-003 | 成功 | 範本已更新 | FR-DP-US9-06 儲存完成 |
| DP-MSG-TEMPLATES-004 | 錯誤 | 無權限編輯此模組之範本 | FR-DP-US9-02 越權 |

## 前置依賴

- 操作者具 ET 或 DM 管理者角色並已登入（US1 / US7）
- 範本種子資料（DP 系統信 3 支 + ET / DM 各模組事件）於 data-model / migration 階段定義
- 發信渲染為 US6；DM 事件之啟停業務語意見 [../dm/spec_us1.md](../dm/spec_us1.md) FR-007

## 相關文件

- 需求章節：[RQDP.md](../../requirements/RQDP.md) §通知範本與發信引擎
- 使用案例：[usecases.md](../../use-cases/dp/usecases.md) UCDP011
- 共用規則：[spec.md](spec.md) §通知範本與發信引擎
