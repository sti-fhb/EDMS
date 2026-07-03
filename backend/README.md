# EDMS Backend

EDMS（教育訓練文件管理系統）後端，FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL。

## 快速開始（最小骨架）

```bash
uv sync
cp .env.example .env          # 填入你的 postgres 密碼與 edms 資料庫
uv run alembic upgrade head   # 在 edms DB 建立 alembic_version 表
uv run fastapi dev main.py    # http://127.0.0.1:8000/health
uv run pytest                 # 執行測試
```

## 現況

目前為 **最小可運行骨架**：`app/core`（config / db / base_model / exceptions / pagination /
request_context / utils）+ health/version 端點 + 空的 alembic。認證、業務模組於後續 task 引入。
