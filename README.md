# EDMS — 教育訓練文件管理系統

> 國軍醫院血液中心**內部人員線上教育訓練平台**，獨立部署於主系統 TSBMS 之外。
> 與文件管理模組（DM）共用使用者帳號；教材文件由 DM 提供。

## SA 文件

系統需求分析文件存放於 [`docs/`](docs/)：

| 目錄 | 說明 |
|------|------|
| [`docs/refs/`](docs/refs/) | 需求分析資料（source of truth）|
| [`docs/requirements/`](docs/requirements/) | 需求清單（RQET）|
| [`docs/use-cases/`](docs/use-cases/) | 使用案例（UCET）|
| [`docs/specs/`](docs/specs/) | Speckit 設計文件（spec、data-model、contracts、tasks 等）|
| [`docs/wireframes/`](docs/wireframes/) | 畫面原型 + 截圖 |

### 需求代碼與對應檔案

本系統為單模組部署，與 DM 模組透過共用 user table 整合：

| 代碼 | 模組 | 需求文件 | 分析資料 |
|------|------|---------|----------|
| ET | 教育訓練（Education & Training）| [`docs/requirements/RQET.md`](docs/requirements/RQET.md) | [`docs/refs/10-教育訓練文件管理模組.md`](docs/refs/10-教育訓練文件管理模組.md) |
| DM | 文件管理（介接）| TSBMS_SA repo `requirements/RQDM.md` | TSBMS_SA repo `_refs/11-文件管理模組.md` |

> ET 透過 SRVDM001 / SRVDM002 介接 DM 模組（取得訓練教材文件清單與內容）；介接契約見 [`docs/specs/contracts/`](docs/specs/contracts/)。

---

## 專案目錄

```text
EDMS/
├── frontend/src/
│   ├── pages/          # 各畫面（ET01~ET08 + 登入頁）
│   ├── components/     # 共用元件（MUI）
│   ├── contexts/       # React Context（AuthContext 等）
│   ├── hooks/          # 共用 custom hooks
│   ├── services/       # 共用 API 層（axios instance）
│   ├── schemas/        # Zod 驗證 schema
│   └── ...
├── backend/app/
│   ├── api/            # FastAPI endpoints（依 US 分群）
│   ├── core/           # 共用（auth、base_model、pagination、AppError）
│   ├── services/       # 業務邏輯 service 層
│   ├── repositories/   # DB 存取層
│   ├── models/         # SQLAlchemy models
│   └── alembic/        # Migration
├── docs/
│   ├── refs/           # 需求分析資料（source of truth）
│   ├── requirements/   # 需求清單（RQET）
│   ├── use-cases/      # 使用案例（UCET）
│   ├── specs/          # Speckit 設計文件
│   │   ├── spec.md             # 功能規格總檔
│   │   ├── spec_us1~12.md      # 12 個 US 規格
│   │   ├── plan.md             # 實作計畫
│   │   ├── data-model.md       # ERD + DDL
│   │   ├── tasks.md            # 開發任務
│   │   ├── issues.md           # GitHub Issues 拆分
│   │   └── contracts/          # 介接契約
│   └── wireframes/     # 畫面原型 + 截圖
└── .claude/            # Claude Code 規則
    └── rules/          # PG 細部規則
```

---

## 環境需求

| 工具 | 版本 | 用途 |
|------|------|------|
| Git | 最新版 | 版本控制 |
| Python | 3.12+ | 後端 |
| uv | 最新版 | Python 套件管理 |
| Node.js | 18+ | 前端 |
| pnpm | 最新版 | Node 套件管理 |
| PostgreSQL | 17 | 資料庫（與 DM 模組共用 user table，可同庫不同 schema 或獨立 DB）|
| SMTP Server | — | 寄送邀請信 / 密碼重設信 / Email 變更驗證信 |

### 安裝環境工具

各工具安裝步驟（Windows / WSL / macOS）請參考 TBMS repo 的 README「環境需求」章節（版本與安裝指令相同）。

---

## 首次設定

> 以下指令以 Bash（WSL / macOS / Linux）為主。Windows 使用者請將 `cp` 替換為 `copy`。

### 1. Clone 專案
```bash
git clone <EDMS_REPO_URL>
cd EDMS
```

### 2. 後端設定
```bash
cd backend

# 安裝依賴
uv sync

# 複製環境設定
cp .env.example .env
```
編輯 `backend/.env`，填入：
- `DATABASE_URL`：PostgreSQL 連線字串（**與 DM 模組共用 user table，需協調 schema**）
- `JWT_SECRET_KEY`：自訂一組隨機字串
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD`：Email Server 連線資訊
- `EMAIL_FROM_ADDRESS`：寄件人 Email
- `DM_API_BASE_URL`：DM 模組 API 位址（用於 SRVDM001 / SRVDM002 介接）

### 3. 前端設定
```bash
cd frontend

# 安裝依賴
pnpm install

# 複製環境設定
cp .env.example .env
```

> 前端 `.env` 預設只需 `VITE_API_BASE_URL=/api`，搭配 Vite proxy 使用。

### 4. 資料庫 Migration
```bash
cd backend
uv run alembic upgrade head
```

Migration 執行完成後，會自動建立以下 seed 資料：

| Table | 資料 | 說明 |
|------|------|------|
| `ET_MODULE` | 7 筆 | 業務模組（採血 / 成分 / 檢驗 / 供應 / 醫務 / 報表與標籤 / 其他）|
| `ET_PARAM` | 8 筆 | 系統參數（VIDEO_ALLOWED_FORMATS / VIDEO_MAX_SIZE_MB / PASSWORD_RESET_TTL_MIN / INVITATION_CODE_LENGTH 等）|
| `USER` + `ET_USER_ROLE` | 1 筆 | 第一個管理者（由 IT 於部署時提供 Email 與初始密碼 hash）|

> **第一個管理者**：由 IT 透過 Seed Script 寫入；之後管理者可彼此互相指派 / 取消管理者角色。設定方式詳見 [`docs/specs/plan.md`](docs/specs/plan.md) §系統初始化。

---

## 測試帳號

執行 `alembic upgrade head` 後，可使用以下示範帳號登入：

| 帳號（Email）| 密碼 | 角色 | 業務模組 | 說明 |
|------|------|------|---------|------|
| `admin@edms.local` | `changeme` | 管理者 | 全部 | 系統初始管理者 |
| `teacher@edms.local` | `changeme` | 教師 | 採血 | 教師示範帳號 |
| `student@edms.local` | `changeme` | 學員 | 採血 | 學員示範帳號 |

> 示範帳號由 seed migration 建立；正式部署時請刪除或更換密碼。

---

## 啟動開發環境

後端與前端需**分開兩個終端機視窗**啟動。

### 後端（終端機 1）
```bash
cd backend
uv run fastapi dev main.py --port 8001 --host 127.0.0.1
```
- API：`http://localhost:8001`
- Swagger 文件：`http://localhost:8001/docs`

> **務必加 `--host 127.0.0.1`**：不指定時 `fastapi dev` 的綁定位址會在不同次啟動間飄移（127.0.0.1 或 ::1）。前端 vite proxy 已固定連 `127.0.0.1`（見 `frontend/vite.config.ts`），後端也釘 `127.0.0.1` 兩邊才一致，否則登入 / `/api` 請求會出現「系統連線異常」（Windows 上 `localhost` 優先解析成 IPv6 `::1` 之坑）。

### 前端（終端機 2）
```bash
cd frontend
pnpm dev
```
- 前端：`http://localhost:5174`

> Port 採 8001 / 5174 以避免與 TBMS（8000 / 5173）同機共存衝突；可於 `.env` 調整。

---

## Docker 部署

### 架構總覽

```
                    ┌─────────────────────────────────────────┐
                    │           Docker Compose                │
  Cloudflare        │                                         │
  Tunnel     ──────►│  edms-nginx (:80)                       │
                    │    ├─ /api/*  ──► edms-backend (:8001)  │
                    │    └─ /*      ──► 靜態檔案 (React SPA)  │
                    │                                         │
                    │  edms-backend (:8001)                    │
                    │    └─ FastAPI + uvicorn                  │
                    │                                         │
                    │  edms-db (:5432)                         │
                    │    └─ PostgreSQL 17（與 DM 共用）        │
                    └─────────────────────────────────────────┘
```

| 容器 | 映像檔 | 說明 |
|------|--------|------|
| `edms-nginx` | nginx:alpine（multi-stage build） | 前端靜態檔案 + 反向代理 |
| `edms-backend` | python:3.12-slim + uv | FastAPI 後端 API |
| `edms-db` | postgres:17 | PostgreSQL 資料庫（與 DM 共用 user table）|

### 本機 Docker 開發

```bash
# 1. 複製環境變數
cp .env.example .env.local

# 2. 編輯 .env.local，填入 POSTGRES_PASSWORD、JWT_SECRET_KEY、SMTP_*

# 3. 啟動（自動套用 override，從原始碼 build）
docker compose up -d --build

# 4. 執行 DB Migration
docker compose exec edms-backend uv run alembic upgrade head
```

- 前端：`http://localhost`（port 80）
- 後端 API：`http://localhost:8001`
- PostgreSQL：`localhost:5441`（避免與 TBMS 5440、本機 5432 衝突）

---

## 常見問題

| 症狀 | 原因 | 解法 |
|------|------|------|
| 前端白畫面 | 缺少 `frontend/.env` | `cp .env.example .env` |
| 登入後畫面掛掉 | `pnpm install` 未執行 | `cd frontend && pnpm install` |
| 教材文件下拉為空 | DM 模組未啟動 / `DM_API_BASE_URL` 設定錯誤 | 檢查 `.env` 並確認 DM 服務可達 |
| 邀請信 / 密碼重設信未收到 | SMTP 設定錯誤或防火牆阻擋 | 檢查 `.env` 之 SMTP_* 設定；測試寄送：`uv run python -m app.scripts.smtp_test` |
| 無法登入（查無此帳號）| Seed 未執行 | `cd backend && uv run alembic upgrade head` |

---

## 本地 CI 驗證

```bash
pnpm ci:local      # 完整驗證
pnpm ci:quick      # 快速驗證
pnpm ci:backend    # 只跑後端
pnpm ci:frontend   # 只跑前端
```

涵蓋的檢查與覆蓋率門檻同 TBMS 慣例（diff-cover ≥ 80%）。

### 整合測試環境設定（integration tests）

整合測試（`pytest -m integration`）需要真實 PostgreSQL 與獨立測試庫，首次執行前需：

1. **建立 `backend/.env.test`**（本機檔，已被 `.gitignore` 排除）：
   ```bash
   cd backend
   cp .env.example .env.test
   # 編輯 .env.test，將 DATABASE_URL 的庫名改為 test_edms（保留本機帳密）：
   # DATABASE_URL=postgresql+asyncpg://postgres:<你的密碼>@localhost:5432/test_edms
   ```
   > 庫名**必須含 `test`**，`apply_migrations` fixture 會 assert 防呆，避免誤動正式庫。測試庫不存在時 fixture 會自動建立。

2. **確認 `psql` 在 PATH**：conftest 以 `psql` 子程序做建庫 / DROP SCHEMA 維護。
   Windows 若已裝 PostgreSQL，將 `C:\Program Files\PostgreSQL\<版本>\bin` 加入使用者 PATH 即可（免另裝）。

3. **執行**：
   ```bash
   uv run pytest -m integration      # 只跑整合測試
   uv run pytest -n auto             # 全套並行（每個 xdist worker 自帶獨立庫 test_edms_gwNN）
   ```

> CI（GitHub-hosted）不讀 `.env.test`，改由 workflow 直接注入 `DATABASE_URL`；runner 已內建 `psql`。

---

## 常用指令

### 後端
```bash
# 新增 migration
cd backend
uv run alembic revision --autogenerate -m "描述變更內容"

# 套用 migration
uv run alembic upgrade head

# 回滾一版
uv run alembic downgrade -1
```

#### 完整重建（清除所有 table + 重建 + 重塞資料）

```bash
psql -U postgres -d edms -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
cd backend
uv run alembic upgrade head
```

### 前端
```bash
cd frontend
pnpm type-check   # 型別檢查
pnpm build        # 產生 build
```

### Wireframe 截圖（SA 用）
```bash
cd docs/wireframes/temp
npm install       # 首次執行需安裝 playwright
npx playwright install chromium
node take_screenshots.mjs
```
產出於 [`docs/wireframes/temp/screenshots/`](docs/wireframes/temp/screenshots/)。

---

## 跨 repo 依賴

| 依賴 | 來源 repo | 用途 |
|------|----------|------|
| DM 模組設計 | TSBMS_SA | ET 介接 DM 時參考契約規格 |
| RQ0 原始條目（RQET001–008）| TSBMS_SA | 需求追溯來源 |
| 共用使用者主檔（USER）schema | DM 模組 | 需與 DM 協調共用欄位定義 |

詳見 [`CLAUDE.md`](CLAUDE.md)「跨 repo 引用」章節。

---

## 版本歷程

| 版本 | 日期 | 說明 |
|------|------|------|
| v0.0.1 | 2026-06 | SA 文件搬遷自 TSBMS_SA repo |
