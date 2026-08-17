# 模組回呼介面契約（ET / DM 提供、DP 呼叫）

**日期**: 2026-07-09 | **規格**: [../spec.md](../spec.md)

> DP 為統一管理後台與排程引擎，部分能力**反向依賴**各模組提供之 service。本檔列出 DP 所需之介面簽章與語意；正式編碼（SRVET0xx / SRVDM0xx）由各模組於其 contracts 定案後回填本檔。同一 FastAPI 應用內之 Python 呼叫，邊界依 `sti-backend-boundaries`。

---

## 1. 管理者身分判定（US1 / US5 / US7 / US9 / US10 後台過濾用）

```python
# ET / DM 各自提供
def is_module_admin(user_id: str) -> bool
```

- 每請求即時查詢（JWT 不含角色，見 research §4）；DP 據以決定後台可見範圍（模組項過濾、共用項存取）

## 2. 預設角色授予（US2 註冊 / US4 代建，帳號建立當下）

```python
# ET 提供
def grant_default_student_role(user_id: str) -> None
```

- 寫入 `ET_USER_ROLE`（學員）+ 受訓單位標籤預設「未指派」；冪等（已存在不重複）
- **DM 無對應介面**——DM 角色一律由管理者於 US7 開通（2026-07-08 釐清第 3 輪）

## 3. 角色 / 標籤指派寫入（US7 權限管理）

```python
# ET 提供
def get_users_roles_tags(user_ids: list[str]) -> dict[str, EtRoleTagView]   # 批次載入一頁使用者之現況（避免逐列 N+1）
def assign_roles_tags(user_id: str, roles: set[str], tags: set[str], operator_id: str) -> None

# DM 提供
def get_users_roles_audiences(user_ids: list[str]) -> dict[str, DmRoleAudienceView]
def assign_roles_audiences(user_id: str, roles: set[str], audiences: set[str], operator_id: str) -> None
```

### 回傳型別（現況載入用）

```python
class EtRoleTagView:
    roles: set[str]                     # 現有 ET 角色；子集 {ADMIN, TEACHER, STUDENT}
    tags: set[str]                      # 現有受訓單位標籤：DP_PARAM `ET_` 前綴清單之 PARAM_KEY 集合
    last_modified_by: str | None        # 最後異動者 USER_ID（來源模組表 UPDATED_USER）
    last_modified_date: datetime | None # 最後異動時間（UPDATED_DATE）

class DmRoleAudienceView:
    roles: set[str]                     # 子集 {ADMIN, EDITOR, REVIEWER, VIEWER}
    audiences: set[str]                 # 現有可見對象 / 單位：DM_TAG（AUDIENCE 組）之 TAG_ID 集合（DM 自持表，非 DP_PARAM）
    last_modified_by: str | None
    last_modified_date: datetime | None
```

- **批次讀取（決策 3=B）**：一次回一頁使用者之現況，key＝`user_id`；查無指派者回**空集合之 View**（非缺 key）。避免清單頁逐列 N+1。`assign_*` 仍為單筆（一次改一位）。
- **標籤 / 可見對象回「代碼」而非名稱（決策 1=A）**——**來源依模組不同**：
  - **ET** 之 `tags` 為 `DP_PARAM`（`ET_` 前綴）之 **PARAM_KEY 集合**；中文顯示名由 **DP 讀 `DP_PARAM`（SRVDP001, US5 之 `PARAM_NAME`）** 對應。
  - **DM** 之 `audiences` 為 **`DM_TAG`（`AUDIENCE` 組）之 `TAG_ID` 集合**（DM 自持表，2026-08-06 #127 對齊 dm/spec.md §跨模組共用規則）；中文顯示名與**可選清單**由 **DM 經 catalog 轉接層提供**（見 §3.1 `list_audiences`），DP 不讀 DP_PARAM 取 DM 可見對象。
  - 各模組不重複回名稱、名稱權威在各自來源；此為 ET（DP_PARAM）與 DM（DM_TAG）之刻意差異。
- **最後異動欄（決策 2=A）**：View 帶 `last_modified_by` / `last_modified_date`（來源模組表 `UPDATED_*`），供 dp-roles 表格「最後異動」欄呈現。
- 角色種類為固定 enum（ET：ADMIN / TEACHER / STUDENT；DM：ADMIN / EDITOR / REVIEWER / VIEWER）
- **自我保護判定在模組**：operator 取消自己之管理者角色 → 模組 raise `AppError`（error_code 由各模組於其 contracts 定案，如 SRVET / SRVDM 之自我保護碼）；**DP 端統一映射為 `DP-MSG-DP06-001` 呈現**（非逐字透傳模組訊息，見 spec_us7 FR-06）。不檢核「至少 1 名管理者」。
- 指派值 MUST 屬啟用中清單項（模組寫入前檢核）：**ET** `tags` 屬 `DP_PARAM`（`ET_` 前綴）啟用項；**DM** `audiences` 屬 `DM_TAG`（`AUDIENCE` 組、`IS_ENABLED=true`）——soft-retire 之值不可**新增**指派，但既有指派保留（見 §3.1）
- 指派異動由**模組**於同交易內呼叫 SRVDP003 寫稽核（事件歸屬各自 MODULE）

## 3.1 受控主檔維護（US1「系統參數與清單」＋「權限管理」可見對象清單）

適用於**受控主檔為模組自持表**之情形：DM 之分類 / func_name / 標籤庫皆為 DM 表（`DM_CATEGORY` / `DM_FUNC` / `DM_TAG_GROUP` / `DM_TAG`，含 `IS_BUILTIN` / `GROUP_TYPE` 等富語意欄位與手冊唯一部分索引所需之真欄，**非 `DP_PARAM`**）。DP 後台「系統參數與清單」畫面經本轉接層呼叫模組維護、「權限管理」畫面經 `list_audiences` 取可見對象可選清單（比照 §3 roles 轉接層，DP 不直接寫模組表）。**ET** 之受訓單位標籤存 `DP_PARAM`（`ET_` 前綴）、由 DP 直接維護，**不走本轉接層**。

```python
# DM 提供（DP 後台「系統參數與清單」/「權限管理」呼叫）
def list_controlled(kind: str, *, enabled_only: bool = False) -> list[ControlledItemView]
def create_controlled(kind: str, code: str, name: str, operator_id: str) -> None
def rename_controlled(kind: str, code: str, new_name: str, operator_id: str) -> None
def set_controlled_enabled(kind: str, code: str, enabled: bool, operator_id: str) -> SetEnabledResult
def list_audiences(*, enabled_only: bool = True) -> list[ControlledItemView]  # = list_controlled('TAG') 之 AUDIENCE 組；供權限管理可見對象核取清單

class ControlledItemView:
    kind: str                    # 'CATEGORY' | 'FUNC' | 'TAG'
    code: str                    # CATEGORY_CODE / FUNC_CODE；TAG 用 TAG_ID（字串化）
    name: str
    is_builtin: bool             # 內建項：代碼鎖定、僅可改名
    is_enabled: bool
    group_type: str | None       # 僅 TAG：'AUDIENCE' | 'RETRIEVAL'
    tag_group_code: str | None   # 僅 TAG：所屬標籤組

class SetEnabledResult:
    affected_docs: int | None    # 僅 AUDIENCE 標籤停用（soft-retire）回；其餘為 None
    affected_viewers: int | None # 僅 AUDIENCE 標籤停用回
```

- **不開放刪除**：淘汰改停用（`set_controlled_enabled(enabled=False)`）；停用後既有引用 100% 保留、僅擋後續新增 / 編輯 / 檢索下拉（對應 dm/spec_us1 FR-001 / DM-MSG-DM09-003）。
- **分類碼建立後鎖定**：`create_controlled('CATEGORY', ...)` 之 `code` 須英數唯一（格式違反 → `DM_CATALOG_003`；重複 → `DM_CATALOG_001`）；內建項僅可改名（`is_builtin=true`）。查無 → `DM_CATALOG_002`。
- **AUDIENCE 標籤停用＝soft-retire**：`set_controlled_enabled('TAG', <audience_tag_id>, enabled=False)` 回 `SetEnabledResult(affected_docs, affected_viewers)`——既有 `DM_DOC_TAG` / `DM_USER_TAG` 不收回、僅擋後續指派；DP 後台據此提示受影響數（對應 dm/spec_us1 FR-010 / DM-MSG-DM09-009）。**觸發落點：DP 後台呼叫 DM `set_controlled_enabled`，DM 端執行 soft-retire 並回傳受影響數，DP 呈現提示**（2026-08-06 定案原 US1 開工前 SA Q）。
- **可見對象 `list_audiences`**：供 §3「權限管理」渲染可見對象核取清單；`assign_roles_audiences` 之 `audiences` 值 MUST 屬本清單啟用項（`DM_TAG` AUDIENCE 組、`IS_ENABLED=true`），soft-retire 之值不可新增指派、既有保留。
- 維護異動由**模組**於同交易內呼叫 SRVDP003 寫稽核（`MODULE=DM`）。
- error_code 由模組定案（DM：`DM_CATALOG_001` 重複 / `DM_CATALOG_002` 查無 / `DM_CATALOG_003` 格式；見 dm 錯誤碼表）。

## 4. 使用者模組角色摘要（模組入口頁，US1 導向）

```python
# ET / DM 各自提供
def has_any_role(user_id: str) -> bool
```

- 入口頁據以決定 DM 卡狀態：具任一 DM 角色＝可進入；無＝「未開通」鎖定卡（引導洽管理者，2026-07-09 釐清第 4 輪）；ET 恆可用（學員預設）。模組側欄之 DM 組顯示與否亦由各模組以同一判定 enforce

## 5. 排程 job handler（US11 引擎動態載入）

```python
# 各模組提供，於 DP_SCHEDULE.HANDLER_REF 登錄 dotted path
async def run() -> None      # SCHET001 / SCHET002 / SCHDM001；SCHDP001 由 DP 自持
```

- handler 內需業務資料時反向 import 模組 service；例外由引擎捕捉記 `DP_SCHEDULE_LOG`（FAILED）
- 寄信一律經 SRVDP002；排程時間參數存 `DP_PARAM`（模組前綴）

---

## 版本

| 日期 | 異動 |
|------|------|
| 2026-07-09 | 首版；SRVET / SRVDM 正式編碼待各模組 contracts 定案回填 |
| 2026-08-06 | DM US1 交付前自檢（`/sti-sa-precheck dm us1`）修 3 處 #127 集中化後之 drift：**§3** `DmRoleAudienceView.audiences` 來源由「`DP_PARAM` `DM_` 前綴 PARAM_KEY」更正為 **`DM_TAG`（AUDIENCE 組）之 TAG_ID**（DM 自持表；顯示名與清單由 DM 經 §3.1 提供，非 DP 讀 DP_PARAM）——標明 ET（DP_PARAM）/ DM（DM_TAG）刻意差異；新增 **§3.1 受控主檔維護轉接層**（`list_controlled` / `create` / `rename` / `set_controlled_enabled` / `list_audiences` + `ControlledItemView` / `SetEnabledResult`），定義 DP 後台呼叫 DM 維護 `DM_CATEGORY` / `DM_FUNC` / `DM_TAG` 及 AUDIENCE soft-retire 觸發落點（DP 呼叫 → DM 執行回受影響數）|
| 2026-07-27 | US7 交付前自檢（`/sti-sa-precheck #7`）補 §3：定義 `EtRoleTagView` / `DmRoleAudienceView` 欄位（roles / tags｜audiences 之 PARAM_KEY 集合 + last_modified_*）；讀取改**批次** `get_users_roles_*(user_ids)`（避免 N+1，決策 3=B）；標籤回代碼、名稱由 DP 讀 DP_PARAM 對應（決策 1=A）；自我保護錯誤由 DP 統一映射為 DP-MSG-DP06-001（同步 spec_us7 FR-06）|
