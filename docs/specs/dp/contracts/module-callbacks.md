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
    audiences: set[str]                 # 現有可見對象 / 單位：DP_PARAM `DM_` 前綴清單之 PARAM_KEY 集合
    last_modified_by: str | None
    last_modified_date: datetime | None
```

- **批次讀取（決策 3=B）**：一次回一頁使用者之現況，key＝`user_id`；查無指派者回**空集合之 View**（非缺 key）。避免清單頁逐列 N+1。`assign_*` 仍為單筆（一次改一位）。
- **標籤 / 可見對象回「代碼」而非名稱（決策 1=A）**：View 之 `tags` / `audiences` 為 `DP_PARAM` 之 **PARAM_KEY 集合**；**中文顯示名由 DP 讀 `DP_PARAM`（SRVDP001, US5 之 `PARAM_NAME`）對應**——名稱權威在 DP_PARAM、模組不重複回名稱、不會不同步。
- **最後異動欄（決策 2=A）**：View 帶 `last_modified_by` / `last_modified_date`（來源模組表 `UPDATED_*`），供 dp-roles 表格「最後異動」欄呈現。
- 角色種類為固定 enum（ET：ADMIN / TEACHER / STUDENT；DM：ADMIN / EDITOR / REVIEWER / VIEWER）
- **自我保護判定在模組**：operator 取消自己之管理者角色 → 模組 raise `AppError`（error_code 由各模組於其 contracts 定案，如 SRVET / SRVDM 之自我保護碼）；**DP 端統一映射為 `DP-MSG-ROLES-001` 呈現**（非逐字透傳模組訊息，見 spec_us7 FR-06）。不檢核「至少 1 名管理者」。
- 標籤 / 可見對象值 MUST 屬 `DP_PARAM` 啟用中清單項（模組寫入前檢核）
- 指派異動由**模組**於同交易內呼叫 SRVDP003 寫稽核（事件歸屬各自 MODULE）

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
| 2026-07-27 | US7 交付前自檢（`/sti-sa-precheck #7`）補 §3：定義 `EtRoleTagView` / `DmRoleAudienceView` 欄位（roles / tags｜audiences 之 PARAM_KEY 集合 + last_modified_*）；讀取改**批次** `get_users_roles_*(user_ids)`（避免 N+1，決策 3=B）；標籤回代碼、名稱由 DP 讀 DP_PARAM 對應（決策 1=A）；自我保護錯誤由 DP 統一映射為 DP-MSG-ROLES-001（同步 spec_us7 FR-06）|
