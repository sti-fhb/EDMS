---
description: API 路徑與目錄結構規範，開發後端時載入
paths:
  - "backend/**/*.py"
---

# API 路徑與目錄結構規範

## 後端目錄結構

```
backend/app/
├── core/           # 跨模組共用（auth、db、pagination、exceptions 等）
├── services/       # 跨模組公開 Service 出口（__init__.py 唯一出口）
├── dp/             # 基礎平台模組（Deployment Platform）
│   ├── user/       # 認證與個人資料（登入、登出、忘記密碼、/me）
│   ├── users/      # 人員管理 CRUD（列表、新增、修改、刪除、站點/角色指派）
│   ├── menus/      # 選單管理
│   ├── roles/      # 角色管理
│   ├── sites/      # 站點管理
│   ├── params/     # 系統參數
│   ├── schedules/  # 排程管理（APScheduler）
│   └── audit/      # 稽核日誌
├── bc/             # 採血模組
├── bs/             # 血液庫存模組
├── cp/             # 成分製備模組
├── tl/             # 輸血模組
└── ma/             # 維護管理模組
```

## 前端目錄結構

前端模組目錄對應後端模組，命名一致：

```
frontend/src/
├── dp/
│   ├── user/       # 對應 backend/app/dp/user/（認證）
│   ├── users/      # 對應 backend/app/dp/users/（人員管理）
│   ├── menus/      # 對應 backend/app/dp/menus/
│   ├── roles/
│   ├── sites/
│   ├── params/
│   └── schedules/
├── bc/
├── bs/
...
```

> 前端路由路徑（瀏覽器 URL）與後端 API 路徑各自獨立，不需強制對應。

## API 路徑規則

### 公開端點（不需 JWT）

```
POST /api/login
POST /api/forgot-password
POST /api/reset-password
GET  /api/sites             ← 登入頁站點下拉選單（僅回傳啟用站點的 site_id + site_name）
GET  /api/version
GET  /health
```

### 業務模組端點（需 JWT）

格式：`/api/{module}/{sub-module}/{resource}`

```
# dp 模組
GET  /api/dp/user/me
PUT  /api/dp/user/me
PUT  /api/dp/user/me/password
GET  /api/dp/menus
GET  /api/dp/menus/me
GET  /api/dp/roles
GET  /api/dp/sites
GET  /api/dp/params
GET  /api/dp/schedules
GET  /api/dp/api-keys

# 其他業務模組（格式相同）
GET  /api/bs/blood-units
GET  /api/bc/donors
```

### 對外系統端點（需 API Key）

格式：`/api/external/{module}/{resource}`

認證方式：`Authorization: Bearer <client>_live_<secret>` → 後端用 `get_api_client` Dependency 驗證。

#### 目錄結構

各業務模組的對外端點放在自身模組的 `external/` 子資料夾：

```
backend/app/
├── bc/
│   └── external/
│       └── router.py   ← 對外 API，router level 掛 get_api_client
├── bs/
│   └── external/
│       └── router.py
```

> 目錄按「領域歸屬」組織（`{module}/external/`），URL 按「認證邊界」組織（`/api/external/{module}/`），順序相反是刻意設計。

#### Dependency 掛載規則

**必須在 `APIRouter` 宣告時掛上 `get_api_client`，禁止只在個別 method 上注入。**

router 自身的 prefix 只寫模組段（`"/bc"`），不含 `/external`；`/external` 由 `main.py` 的 `include_router` prefix 統一加上。

```python
# ✅ 正確：bc/external/router.py
from app.core.api_key import get_api_client, ApiClientPayload

router = APIRouter(prefix="/bc", dependencies=[Depends(get_api_client)])

@router.get("/some-resource")
async def some_resource(db: AsyncSession = Depends(get_db)):
    ...

# 若 handler 需要取用 client payload，可在 method 上額外宣告
# FastAPI Dependency 有 request-scoped 快取，同一 request 不會重複執行
@router.get("/another-resource")
async def another_resource(
    client: ApiClientPayload = Depends(get_api_client),
    db: AsyncSession = Depends(get_db),
):
    ...

# ❌ 錯誤：只在 method 注入 — 新增 endpoint 時容易遺漏，造成未驗證的公開端點
router = APIRouter(prefix="/bc")

@router.get("/some-resource")
async def some_resource(
    client: ApiClientPayload = Depends(get_api_client),
):
    ...
```

#### main.py 注冊方式

對外 router 統一用 `prefix="/api/external"`，與業務模組的 `prefix="/api"` 明確區隔，一眼辨識認證邊界：

```python
# backend/main.py

# 業務模組（JWT）
app.include_router(sites_router, prefix="/api")      # → /api/dp/sites
app.include_router(roles_router, prefix="/api")      # → /api/dp/roles

# 對外模組（API Key）— 統一用 /api/external
app.include_router(bc_external_router, prefix="/api/external")   # → /api/external/bc/...
app.include_router(bs_external_router, prefix="/api/external")   # → /api/external/bs/...
```

- 對外端點不注入 `get_jwt_payload`，僅注入 `get_api_client`
- 錯誤碼：`DP_APIKEY_001`（格式不符）、`DP_APIKEY_002`（不存在/已撤銷）、`DP_APIKEY_003`（已過期）

## 資源命名規則

| 類型 | 規則 | 範例 |
|------|------|------|
| Collection（可列舉的資料集）| **複數** + kebab-case | `/menus`、`/blood-units`、`/ref-codes` |
| Singleton（每個 context 唯一一筆）| **單數** | `/user/me`、`/profile` |
| 目錄名稱 | 依模組語意決定，不強制複數 | `dp/user/`、`dp/menus/` 均合理 |

> 判斷標準：問「這個資源有沒有多筆？」— 有 → 複數；每個使用者/context 只有一筆 → 單數。

## Contract 類型判斷（SRV vs API）

spec contract 文件的編碼前綴決定實作方式：

| 編碼前綴 | 範例 | 呼叫方 | 實作 | 目錄 | 認證 |
|---------|------|--------|------|------|------|
| `SRV` | SRVBC002 | TBMS 內部其他模組 | Python Service 呼叫 | 不在 `external/` | 無 |
| `API` | APILB007 | 外部系統 | HTTP 端點 | `{module}/external/router.py` | Bearer API Key |

- ❌ `SRV` 開頭的 contract 不得放入 `external/router.py`，不得套用 `get_api_client`
- ❌ `API` 開頭的 contract 不得以純 Python Service 呼叫實作

## 禁止事項

- ❌ API path 出現非業務字詞：`/admin`、`/auth`（改用 `/user`、`/schedules`）
- ❌ 業務模組 endpoint 缺少頂層模組前綴（如直接 `/menus` 而非 `/api/dp/menus`）
- ❌ 前端 service 呼叫路徑與後端 API 路徑不一致
