---
description: 後端模組邊界與隔離規則，開發 backend 時載入
paths:
  - "backend/**/*.py"
---

# 模組邊界規則（API-First 隔離原則）

## 核心原則

各業務模組使用同一個 PostgreSQL 資料庫，
但透過規範**禁止跨模組直接存取**，降低耦合。

## 允許 / 禁止清單

| | 規則 | 說明 |
|--|------|------|
| ✅ 允許 | 呼叫對方模組 `services/__init__.py` 暴露的 Service | 透過公開介面溝通 |
| ❌ 禁止 | 直接 import 對方模組的 Repository / Model | 不能繞過 Service 層 |
| ❌ 禁止 | 在模組 A 的 SQL 直接 JOIN 模組 B 的 table | 不能跨模組直接讀寫資料 |

## 跨模組呼叫範例

```python
# ✅ 正確：透過 services/__init__.py 暴露的 Service
from app.services import ModuleAService

class ModuleBService:
    async def get_info(self, record_id: str, db: AsyncSession):
        svc = ModuleAService()
        return await svc.get_record(record_id, db)

# ❌ 禁止：直接 import 其他模組的 Repository
from app.repositories.module_a_repository import SomeRepository
```

## 例外：報表/查詢類功能（唯讀）

報表與跨模組查詢功能得直接 JOIN 其他模組 table，條件：

- 僅限 SELECT，禁止任何 INSERT / UPDATE / DELETE
- 不得在 SQL 內重新實作他模組的業務規則（狀態判斷等一律以擁有者模組定義為準）
- 該功能 spec 須列出所引用的外模組 table 清單
- 寫入路徑與業務邏輯不適用本例外，仍一律走對方模組 Service；查詢結果若作為寫入或狀態判斷的依據，同樣視為業務邏輯
