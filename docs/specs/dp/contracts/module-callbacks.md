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
def get_user_roles_tags(user_id: str) -> EtRoleTagView          # 現況（供畫面載入）
def assign_roles_tags(user_id, roles: set[str], tags: set[str], operator_id) -> None

# DM 提供
def get_user_roles_audiences(user_id: str) -> DmRoleAudienceView
def assign_roles_audiences(user_id, roles: set[str], audiences: set[str], operator_id) -> None
```

- 角色種類為固定 enum（ET：ADMIN / TEACHER / STUDENT；DM：ADMIN / EDITOR / REVIEWER / VIEWER）
- **自我保護判定在模組**：operator 取消自己之管理者角色 → 模組 raise `AppError`（DP 呈現 DP-MSG-ROLES-001）；不檢核「至少 1 名管理者」
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
