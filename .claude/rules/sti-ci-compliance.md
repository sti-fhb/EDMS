---
description: CI 合規規則，撰寫前後端程式碼時載入，確保符合 GitHub CI 檢查
paths:
  - "backend/**/*.py"
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# CI 合規規則

本規則列出 GitHub CI 所有檢查項目，所有 agent 撰寫程式碼時必須遵守，確保程式碼在寫的時候就符合 CI 規則。

## 後端（Python）

| CI 檢查 | 對應的撰寫規則 |
|---------|---------------|
| `ruff check` | 遵守 `backend/pyproject.toml` 的 ruff lint 規則（F/E/W/I/S/B）；`B008` 已 ignore（FastAPI `Depends()` 標準用法） |
| `ruff format` | Python 程式碼符合 ruff 格式（`line-length=120`）；不確定時執行 `cd backend && uv run ruff format .` 自動修正 |
| `pytest -m unit` | 新功能 / bug fix 必須附 unit test，標記 `@pytest.mark.unit` |
| `pytest --cov` + `diff-cover 80%` | 每個新增的 function/method 都要有對應測試，確保本次 PR 新增/修改的行覆蓋率 ≥ 80% |
| `alembic heads` | 同一時間只能有 1 個 Alembic head；新增 migration 前先執行 `/sti-alembic-check` |

### Ruff 規則速查

| 規則集 | 說明 | 常見問題 |
|--------|------|---------|
| `F` | pyflakes — 未定義名稱、未使用 import | 移除未使用的 import（`__init__.py` 除外） |
| `E` | pycodestyle errors | 行長 ≤ 120、空格規範 |
| `W` | pycodestyle warnings | 尾端空白、空行規範 |
| `I` | isort — import 排序 | import 分三區：stdlib → third-party → local |
| `S` | flake8-bandit — 安全性 | 禁止硬編碼密碼（測試檔案除外：`S101`/`S105`/`S106` 已排除） |
| `B` | flake8-bugbear — 常見 bug 模式 | 避免可變預設參數、`except Exception` 等 |

### Per-file 例外

| 檔案 | 排除規則 | 原因 |
|------|---------|------|
| `__init__.py` | `F401` | re-export 用途，允許未使用的 import |
| `tests/**` | `F811`, `S101`, `S105`, `S106` | 允許 fixture 重複定義、`assert`、硬編碼測試密碼 |

## 前端（TypeScript / React）

| CI 檢查 | 對應的撰寫規則 |
|---------|---------------|
| `pnpm lint`（ESLint） | 前端程式碼符合 ESLint 規則；禁止 `eslint-disable` 除非有明確註解說明原因 |
| `pnpm type-check`（`tsc --noEmit`） | TypeScript 型別正確；禁止 `any`、`@ts-ignore`、`@ts-expect-error`（除非有明確註解說明原因） |
| `pnpm test`（vitest） | 前端測試通過；新功能需附測試 |

## 覆蓋率規則

- **diff-cover 門檻**：本次 PR 新增/修改的行 ≥ 80% 覆蓋率
- **整體覆蓋率**：不設門檻（避免歷史欠債阻擋新功能）
