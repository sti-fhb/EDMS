---
description: 後端共用模組清單，開發 backend 時載入
paths:
  - "backend/**/*.py"
---

# 後端共用模組

開發新功能前先確認是否有現成模組，禁止重複造輪子。

---

## 架構分層與 Model 歸屬

- 分層：`router → service → repository`，不跨層呼叫
- Model 歸屬：`models.py` 放在「擁有該 Table CRUD 生命週期」的子模組下，不放在最先使用它的模組
- 跨子模組引用 Model：同一頂層模組（如 `dp`）內允許直接 `from app.dp.sites.models import Site`；SQLAlchemy relationship 對端用字串前向參考（`Mapped["User"] = relationship("User", ...)`），runtime 自動解析

---

### `paginate()` · `app/core/pagination.py`
所有列表 API 分頁邏輯一律使用，禁止自行寫 count + offset/limit。`limit` 上限 100。

```python
from app.core.pagination import paginate, PaginatedResult

stmt = select(Site).where(Site.deleted == 0).order_by(Site.site_id)
# stmt 不得含 offset/limit
return await paginate(db, stmt, page=page, limit=limit, schema=SiteResponse)
# 回傳：{ "data": [...], "meta": { total, page, limit, total_pages } }
```

---

### `get_api_client` · `app/core/api_key.py`
外部系統 API Key 驗證 Dependency（DP14）。解析 `Authorization: Bearer <client>_live_...` → SHA-256 hash → DB 查詢。回傳 `ApiClientPayload(client_name, key_id)`。

```python
from app.core.api_key import get_api_client, ApiClientPayload

@router.get("/external/bc/some-resource")
async def some_resource(
    client: ApiClientPayload = Depends(get_api_client),
    db: AsyncSession = Depends(get_db),
):
    ...
```

對外端點不注入 `get_jwt_payload`，僅注入 `get_api_client`。錯誤碼：`DP_APIKEY_001`（格式不符）、`DP_APIKEY_002`（不存在/已撤銷）、`DP_APIKEY_003`（已過期）。

---

### `get_jwt_payload` · `app/core/auth.py`
所有需要認證的 endpoint 一律使用。驗證 Access Token（15min JWT），不查 DB。`payload.sub` 與 `payload.site_id` 均為 `str`，不需型別轉換。

```python
from app.core.auth import JwtPayload, get_jwt_payload

@router.get("/items")
async def get_items(payload: JwtPayload = Depends(get_jwt_payload), db: AsyncSession = Depends(get_db)):
    user_id = payload.sub       # str
    site_id = payload.site_id   # str
    roles   = payload.roles     # list[str]
```
禁止將 payload 標註為 `dict`，禁止自行解析 Authorization header。

---

### `AppError` · `app/core/exceptions.py`
所有錯誤一律使用，禁止自訂例外 class 或直接 raise `HTTPException`。

```python
from app.core.exceptions import AppError

# error_code 必填，查 docs/ref/error-codes.md；無對應 code 用 "UNKNOWN"
raise AppError(status_code=404, detail="站點不存在", error_code="DP_SITE_001")
```

回應格式（由 `main.py` 的 `app_error_handler` 統一轉換）：
```json
{ "error_code": "DP_SITE_001", "error_message": "站點不存在" }
```

---

### `BaseModel` / `BaseModelNoResId` / `BaseModelHardDelete` / `AuditLogBaseModel` · `app/core/base_model.py`
所有 Table 必須繼承下表其中一個 base，共用的標準欄位（`CREATED_USER`、`CREATED_DATE`、`UPDATED_USER`、`UPDATED_DATE`、`RES_ID`、`DELETED`）自動取得，**不需重複定義**。（EDMS 為單一組織、無站點維度，標準欄位不含 SITE；見 docs/specs/dp/data-model.md、research.md §1。）

| 基底 | 適用情境 |
|------|----------|
| `BaseModel` | 一般 Table（含 `RES_ID` + `DELETED`），新模組預設使用 |
| `BaseModelNoResId` | `RES_ID` 已被業務欄位佔用的 Table |
| `BaseModelHardDelete` | 硬刪除例外表（含 `RES_ID`，**無 `DELETED`**）|
| `BaseModelNoDelete` | 可更新但永不刪除的 outbox / log 表（含 `UPDATED_*`，**無 `RES_ID` / 無 `DELETED`**，如 `DP_EMAIL_LOG`）|
| `AuditLogBaseModel` | append-only 記錄表（如 `DP_AUDIT_LOG` / `DP_PWD_HIST` / `DP_SCHEDULE_LOG`），僅含 `CREATED_USER`、`CREATED_DATE` |

```python
from app.core.base_model import BaseModel

# 一般 Table（含 RES_ID + DELETED）— 新模組最常見場景
class DpParamMaster(BaseModel):
    __tablename__ = "DP_PARAM_M"
    PARAM_ID: Mapped[str] = mapped_column("PARAM_ID", String(50), primary_key=True)
    # 標準欄位自動繼承，不需重複定義
```

> `BaseModelNoResId` / `BaseModelHardDelete` / `AuditLogBaseModel` 的 code 範例與適用情境：見 `docs/ref/sti-backend-ref.md#basemodel-用法`

**刪除策略**：
- 預設軟刪除（`DELETED = 1`）；所有查詢預設加 `WHERE DELETED = 0`；Service 層 `delete` 方法改為 `update DELETED = 1`
- 不在例外清單內的表一律軟刪除，且必須繼承 `BaseModel` / `BaseModelNoResId` / `BaseModelHardDelete` / `AuditLogBaseModel` 之一
- 既有「無 DELETED 例外表」與「無 BaseModel 例外表」清單，以及新增例外時的更新點：見 `docs/ref/sti-backend-ref.md#刪除策略例外表清單`

---

### `services/__init__.py` · `app/services/__init__.py`
跨頂層模組呼叫的唯一出口。新增對外 Service 時須在此登記並加入 `__all__`。

```python
from app.services import AuthService
svc = AuthService()
result = await svc.get_user(db, user_id)
```

---

### `SequenceService` · `app/dp/sequence/service.py`
業務編號取流水號一律用此服務，禁止 `SELECT COUNT(*) + 1` + SAVEPOINT retry。`next_seq(db, seq_key) -> int` 從 1 起遞增，row-level lock 序列化，無需 retry、O(1)。

```python
from app.services import SequenceService

seq = await SequenceService().next_seq(db, f"ORD-{site_id}-{yyyymm}")
if seq > 9999:
    raise AppError(status_code=500, detail="訂單編號流水號已達上限", error_code="BS_ORDER_001")
order_no = f"ORD-{site_id}-{yyyymm}-{seq:04d}"
```

- `seq_key`：≤ 30 字、`[A-Za-z0-9_-]`，違反拋 `AppError(DP_SEQ_001)`
- `seq_key` 插值來源（如 `site_id`、日期）必須來自受信任來源（JWT payload / 系統時間），禁止直接拼接使用者請求 body 內容
- 重置週期由 key 決定：月 `f"ORD-{site}-{yyyymm}"`、日 `f"BC-{site}-{yyyymmdd}"`、不重置 `"GLOBAL-XXX"`
- 上限檢查、取號儘早呼叫（持鎖至 commit）由呼叫端負責
- 切換指引：`docs/ref/dp-sequence-切換指引.md`

---

### `OperatorInfo` / `get_operator` · `app/core/operator.py`
寫入型 API（新增、更新、軟刪除）填入 `CREATED_*` / `UPDATED_*` 標準欄位時，一律透過此 Dependency 取得操作者資訊，禁止直接讀取 `payload.sub` / `payload.site_id`。

```python
from app.core.operator import OperatorInfo, get_operator

# Router：POST / PUT / DELETE 注入 operator
@router.post("")
async def create_site(
    data: SiteCreate,
    db: AsyncSession = Depends(get_db),
    operator: OperatorInfo = Depends(get_operator),
):
    return await _service.create(db, data, operator)

# Repository：create 填 CREATED_*，update/soft_delete 填 UPDATED_*
async def create(self, db, data: dict, operator: OperatorInfo) -> Site:
    record = Site(
        **data,
        created_user=operator.user_id,
        created_date=utcnow(),
        created_site=operator.site_id,
    )

async def update(self, db, site_id: str, data: dict, operator: OperatorInfo) -> Site | None:
    await db.execute(
        update(Site).where(...).values(
            **data,
            updated_user=operator.user_id,
            updated_date=utcnow(),
            updated_site=operator.site_id,
        )
    )
```

GET endpoint 不需注入 `operator`（router-level `get_jwt_payload` 認證即可）。

#### 暫行授權規則（全域權限機制實作前）

目前 JWT 不含 `res_ids`，全域 res_id 授權機制尚未實作。在此之前：

- **GET**：router-level `dependencies=[Depends(get_jwt_payload)]` 做 JWT 驗證即可
- **POST / PUT / DELETE**：只需注入 `get_operator`（內部已呼叫 `get_jwt_payload`），**不加 `require_admin`**
- 禁止以 `require_admin` 作為臨時替代方案（role 名稱判斷與 res_id 設計脫鉤）

各 Router 宣告方式：

```python
# 目前（JWT 驗證）
router = APIRouter(
    prefix="/dp/sites",
    dependencies=[Depends(get_jwt_payload)],
)

# 將來（全域授權機制就緒後，只改這一行）
router = APIRouter(
    prefix="/dp/sites",
    dependencies=[require_permission("site")],  # factory 產生的 Dependency
)
```

遷移時只需改 router 宣告，不需逐 endpoint 修改。

---


### `AuditLogService` · `app/services/__init__.py`（跨模組呼叫）

新模組**預設不需要寫 audit log**。僅以下操作須寫，目前都集中在 DP 模組，新功能落在這四類時才需要呼叫 `AuditLogService`：

- 登入 / 登出
- 使用者資料異動（個人資料、密碼變更、profile 更新等）
- 角色異動（新增、修改、刪除）
- 權限異動（角色功能權限變更，如 set_menus）

> 詳細用法（呼叫範例、`action_type` / `res_id` 來源、`before_value` / `after_value` 原則）：見 `docs/ref/sti-backend-ref.md#auditlogservice-用法`

---

### Pydantic Schema 規則
- 回應用 Schema 必須加 `model_config = {"from_attributes": True}`
- Update 一律用 `data.model_dump(exclude_unset=True)`
- Repository 只呼叫 `flush()`，不呼叫 `commit()`（commit 由 service 層或 middleware 負責）

---

### 時間處理

- 欄位型別：`DateTime(timezone=True)`（PostgreSQL `TIMESTAMPTZ`）；禁止 `DateTime()` naive
- 當前時間：`from app.core.utils import utcnow` → `utcnow()`；禁止 `datetime.utcnow()` / `datetime.now()` / `.replace(tzinfo=None)` / DB `NOW()` / `server_default=func.now()`
- 比較運算：兩側皆 aware；外部進來的 naive 先補 `dt.replace(tzinfo=timezone.utc)`

```python
# ✅
now = utcnow()
if token.expired_time < utcnow(): ...

# ❌
now = datetime.utcnow()
now = datetime.now(timezone.utc).replace(tzinfo=None)
```
