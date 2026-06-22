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
