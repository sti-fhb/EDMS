# SRVET001–006 — ET 提供予平台 DP 之回呼介面（ET → DP）

**編碼**: SRVET001 ~ SRVET006
**名稱**: ET 模組回呼介面（供平台 DP 後台、入口與排程引擎呼叫）
**提供方**: 教育訓練模組（ET）
**呼叫方**: 平台模組（DP）
**權威來源**: [DP contracts/module-callbacks.md](../../dp/contracts/module-callbacks.md)（DP 為需求方，介面語意以 DP 端為準；本檔為 ET 之實作面定案與編碼回填）
**建立日期**: 2026-08-19（#181）
**對應 US**: [spec_us1.md](../spec_us1.md) US1、[spec_us2.md](../spec_us2.md) US2、[spec_us14.md](../spec_us14.md) US14

---

## 說明

平台 DP 為統一管理後台、模組入口與排程引擎，部分能力**反向依賴**各業務模組提供之 service。DP 契約 [module-callbacks.md](../../dp/contracts/module-callbacks.md) 已列出所需介面，並註明「正式編碼 SRVET0xx 由各模組於其 contracts 定案後**回填本檔**」——本檔即 ET 之定案。

DP 端之掛鉤**已全部就緒並在等待 ET 註冊**（平台 core 之四個聚合閘均 fail-closed，未註冊模組視為無權限 / no-op）：

| DP 端掛鉤 | 位置 | 現況 |
|-----------|------|------|
| 管理者判定 | `app/core/module_admin.py` | 已備，ET 未註冊 → 恆回 `False` |
| 預設角色授予 | `app/core/module_provisioning.py` | 已備，**`app/dp/user/activation.py` 已在呼叫**；ET 未註冊 → no-op |
| 角色 / 群組指派 | `app/core/module_assign.py` | 已備，ET 未註冊 → DP 後台回 404 `DP_ROLE_003` |
| 角色摘要 | `app/core/module_roles.py` | 已備，ET 未註冊 → 恆回 `False` |
| 排程 handler | `app/dp/schedules/scheduler.py` | 白名單已含 `app.et.`；`DP_SCHEDULE` 已預留 SCHET001 / SCHET002 兩列（`IS_ENABLED=false`） |

---

## 呼叫方式（實作層）

- **同一 FastAPI 應用內之 Python 呼叫**（in-process），非 HTTP；邊界依 `.claude/rules/sti-backend-boundaries.md`
- ET 於**啟動期**以 `app/et/bootstrap.py` 註冊各 checker / provider（比照 `app/dm/bootstrap.py`），於 `main.py` module-level 呼叫一次
- 註冊為**冪等**：重複呼叫僅覆蓋同一 checker / provider（供測試重入）

```python
# app/et/bootstrap.py（比照 DM）
def register_et_module() -> None:
    module_role_gate.register("ET", et_has_any_role)              # SRVET005
    module_admin_gate.register("ET", et_is_module_admin)           # SRVET001
    module_provisioning_gate.register("ET", grant_default_student_role)  # SRVET002
    module_assign_registry.register("ET", EtAssignProvider())      # SRVET003 / SRVET004
```

---

## SRVET001 — 管理者身分判定（DP §1）

```python
async def et_is_module_admin(db: AsyncSession, user_id: str) -> bool
```

- 每請求即時查詢 `ET_USER_ROLE`（JWT 不含角色）；DP 據以決定後台可見範圍（`MODULE=ET` 範本、`ET_` 前綴參數、ET 角色指派）
- **fail-closed**：查無角色回 `False`；例外不得吞掉後回 `True`
- 對應 DP 用途：US1 / US5 / US7 / US9 / US10 之後台過濾

## SRVET002 — 預設角色授予（DP §2）

```python
async def grant_default_student_role(db: AsyncSession, user_id: str) -> None
```

- 於帳號建立當下（DP US2 自助註冊 / US4 管理者代建）**同交易內**寫入 `ET_USER_ROLE`（`ROLE=STUDENT`）；受訓單位標籤預設「未指派」（不寫 `ET_USER_TAG`）
- **冪等**：已存在該角色時不重複寫入、不報錯
- **失敗必須向上傳播**：授予失敗即為壞帳號，須讓 DP 之帳號建立整筆交易回滾（與 fail-closed 的讀取型 checker 不同）
- DP 側呼叫點：`app/dp/user/activation.py`（已接線，等 ET 註冊後回歸）

## SRVET003 — 角色 / 受訓單位標籤指派（DP §3）

```python
async def get_users_assignments(db, user_ids: list[str]) -> dict[str, AssignmentView]
async def assign(db, *, user_id: str, roles: set[str], groups: set[str], operator_id: str) -> None
```

> **命名對應**：DP 契約文字稱 ET 之群組為 `tags`（受訓單位標籤），平台 registry 之泛化欄位名為 `groups`（`AssignmentView.groups`）。ET provider 實作依 registry 簽章使用 `groups`，語意即受訓單位標籤。

| 項目 | 規則 |
|------|------|
| `roles` | 子集 `{ADMIN, TEACHER, STUDENT}`；非法代碼 → `ET_ROLE_003` |
| `groups` | `ET_TAG.TAG_ID`（字串化）集合；須屬啟用中（`IS_ACTIVE=true`）標籤，否則 `ET_ROLE_002`。**停用標籤不可新增指派，既有指派保留** |
| 批次讀取 | `get_users_assignments` 一次回一頁使用者之現況（避免 N+1）；查無指派者回**空集合 View**（非缺 key） |
| 最後異動 | View 帶 `last_modified_by` / `last_modified_date`，來源為 `ET_USER_ROLE` / `ET_USER_TAG` 之 `UPDATED_*` |
| 自我保護 | operator 取消自己之管理者角色 → raise `AppError`（`ET_ROLE_001`）；DP 端統一映射為 `DP-MSG-DP06-001` 呈現。**不檢核**「至少 1 名管理者」（per spec.md 設計取捨） |
| 稽核 | 指派異動由 **ET** 於同交易內經 `AuditLogService` 寫入 `DP_AUDIT_LOG`（`MODULE=ET`、`FUNC_NAME=ET-ROLES`） |
| 貼標追溯 | **新增**標籤指派時觸發補加入該標籤所有「已發布且未關閉」課程並寄彙整信；**移除**時既有 `ET_ENROLLMENT` 不變動（見 [spec_us1.md](../spec_us1.md) / [spec_us8.md](../spec_us8.md)）。此為 ET 業務判定，DP 不介入 |

## SRVET004 — 受控主檔維護：受訓單位標籤庫（DP §3.1）

```python
async def list_controlled(db, kind: str, *, enabled_only: bool = False) -> list[ControlledItemView]
async def create_controlled(db, kind: str, *, code: str, name: str, operator_id: str) -> None
async def rename_controlled(db, kind: str, *, code: str, new_name: str, operator_id: str) -> None
async def set_controlled_enabled(db, kind: str, *, code: str, enabled: bool, operator_id: str) -> SetEnabledResult
async def list_audiences(db, *, enabled_only: bool = True) -> list[ControlledItemView]
```

ET 之受控主檔僅一類：**受訓單位標籤庫 `ET_TAG`**（`kind='TAG'`）。

| 項目 | 規則 |
|------|------|
| 儲存 | **ET 自持表 `ET_TAG`**（非 `DP_PARAM`）；`code` 為 `TAG_ID` 字串化、`name` 為 `TAG_NAME` |
| `is_builtin` | 內建種子（全體 / 護理師 / 行政人員 / 軍人 / 醫檢師）回 `true`，供 DP 決定是否提供操作入口 |
| 「全體」保護 | `IS_ALL=true` 之標籤**不可停用、不可改名**；ET 於 `set_controlled_enabled` / `rename_controlled` 伺服器端拒絕（`ET_TAG_001`）。**前端隱藏僅為 UX，保護必須在 ET** |
| 停用語意 | soft-retire：停用後不可再掛至新課程，已掛之既有課程與 `ET_COURSE_TAG` 不受影響（比照 DM AUDIENCE） |
| 不刪除 | 僅停用，不提供刪除 |
| 唯一性 | `TAG_NAME` 唯一 |
| 稽核 | 經 `AuditLogService` 寫 `DP_AUDIT_LOG`（`MODULE=ET`、`FUNC_NAME=ET-ROLES`） |

> ⚠️ **與 DP 契約現行文字不一致（待 DP 對齊，見 #182）**：`module-callbacks.md` §3 / §3.1 目前仍寫「ET 之受訓單位標籤存 `DP_PARAM`、由 DP 直接維護、**不走本轉接層**」，並稱此為「ET 與 DM 之刻意差異」。該敘述已不成立——DP 程式碼 `dp/roles/service.py` 之 `group_options()` 為模組無關實作（取 provider → `list_audiences()`，不讀 `DP_PARAM`），且 DM 已於 2026-08-06（#127）改為自持表。**ET 依本檔實作（走轉接層）**，DP 側文件對齊由 #182 處理。
>
> ⚠️ **DP 端尚未接上受控主檔維護**：`list_controlled` / `set_controlled_enabled` 等目前全 backend 無 DP 呼叫者（僅 DM 實作、無消費端）。ET 交付本介面後，實際生效仍待 #182。

## SRVET005 — 使用者模組角色摘要（DP §4）

```python
async def et_has_any_role(db: AsyncSession, user_id: str) -> bool
```

- DP 入口 / 側欄據以決定 ET 群組是否顯示（最小知悉）
- **fail-closed**：未註冊或查無角色回 `False`
- 註：ET 學員角色於帳號建立當下即授予（SRVET002），故一般使用者恆為 `true`

## SRVET006 — 排程 job handler（DP §5）

```python
# app/et/schedules/handlers.py
async def weekly_stat_job() -> None    # SCHET001：每週統計快照 + 週報 + 0% 未看提醒
async def daily_window_job() -> None   # SCHET002：每日到期關閉 + 截止前加急提醒
```

| 項目 | 規則 |
|------|------|
| 簽章 | `async`、**無參數**；handler 自管其 DB session（`AsyncSessionLocal`） |
| 登錄 | `DP_SCHEDULE.HANDLER_REF` 填完整 dotted path（如 `app.et.schedules.handlers.weekly_stat_job`）；引擎白名單已含 `app.et.` |
| 現況 | `DP_SCHEDULE` 已預留 SCHET001 / SCHET002 兩列、`IS_ENABLED=false`；ET 提供 handler 並填入 `HANDLER_REF` 後由平台開啟 |
| 例外 | 由引擎捕捉並記 `DP_SCHEDULE_LOG`（FAILED），不外拋阻斷排程器；ET 端仍應逐課程容錯，避免單筆失敗中斷整批 |
| 執行時間 | 由 `DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` / `ET_URGENT_REMIND_DAYS` 控制（經 `ParamService` 讀取） |
| 寄信 | 一律經 `NotifyService`（平台唯一發信服務 → `DP_EMAIL_LOG` outbox）；**平台不支援附件**，週報逐學員明細以 CSV 下載連結提供（見 [spec_us14.md](../spec_us14.md) FR-ET-US14-11） |

---

## Error Codes

於 [`docs/ref/error-codes.md`](../../../ref/error-codes.md) §ET 登記：

| error_code | HTTP | error_message | 觸發 |
|------------|------|---------------|------|
| `ET_AUTH_001` | 403 | 需要教育訓練模組權限 | ET 模組存取閘：已登入但無任何 ET 角色 |
| `ET_ROLE_001` | 403 | 無法停用自己之管理者角色 | SRVET003 自我保護；DP 映射為 `DP-MSG-DP06-001` |
| `ET_ROLE_002` | 422 | 指定之受訓單位標籤無效或未啟用 | SRVET003 指派值檢核 |
| `ET_ROLE_003` | 422 | 指定之角色代碼無效 | SRVET003 角色代碼檢核 |
| `ET_TAG_001` | 422 | 內建標籤不可停用或改名 | SRVET004「全體」等內建標籤保護 |

> 命名比照 DM 既有慣例（`DM_AUTH_001` / `DM_ROLE_001~003`）。`ET_ROLE_001` 之 DP 端映射依 DP 契約「以 `_ROLE_001` 結尾判別」之約定。

---

## 依賴狀態（提醒 SD）

| 項目 | 狀態 |
|------|------|
| DP 端四個聚合閘 + 排程白名單 + `DP_SCHEDULE` 預留列 | ✅ 已就緒，等 ET 註冊 |
| DP 後台受控主檔維護（SRVET004 之消費端） | ⚠️ **未接上**，見 #182 |
| DP `module-callbacks.md` §3 / §3.1 之 ET 段落 | ⚠️ **stale**，待 #182 對齊 |
| DP 真授權閘掛 router | ⚠️ 目前為暫行案（任何登入者可存取），**待 ET 註冊 checker 後才能啟用**，見 #113 |

> **雙向依賴**：ET 註冊 checker 是 DP 收尾（#113）的前置——DP 後台現階段對所有登入者開放，正是因為 fail-closed 閘在無模組註冊時會鎖死整個後台。

---

## 變更紀錄

| 日期 | 版本 | 說明 |
|------|------|------|
| 2026-08-19 | 1.0 | 首版（#181）。回填 SRVET001 ~ SRVET006 編碼；定案 ET 端簽章、`ET_TAG` 受控主檔語意、「全體」保護落點與 5 個 error code；標註 §3.1 與 DP 契約現行文字之不一致（待 #182 對齊）及 DP 端未接消費端之現況 |
