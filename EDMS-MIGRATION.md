# EDMS 遷移落地清單（從 TBMS 拆出 ET + DM）

> 本檔為「教育訓練（ET）+ 文件管理（DM）」獨立系統 **EDMS** 的建置 checklist，
> 來源為 TBMS 主專案（`../TBMS`）。逐項打勾即可。
>
> **產生日期**：2026-07-03（依當時 TBMS `main` HEAD `55a768a6`）

---

## 0. 已拍板決策

| 項目 | 決定 |
|------|------|
| 形式 | 新 Git repo，ET + DM 合併為 EDMS |
| 表名前綴 | **沿用 `DP_`** |
| 戰時離線（Offline-First） | **否** |
| MFA 多因子驗證 | **否** |
| 寄信功能（帳號開通/密碼重設） | **是** |
| 權限 RBAC（角色 × 選單） | **是** |
| 使用者管理（DP03） | **是** |
| 認證 | **自建**（獨立帳號，不與 TBMS 共用） |

> 「沿用 DP_ 前綴」的紅利：`core/permission.py`、`core/scheduler_leader.py` 對 `app.dp`
> 的耦合**不需修改**（只要 EDMS 保留 `app.dp` 平台模組放 user/roles/menus/audit）；
> models 表名也幾乎照抄。

---

## 1. 現況快照（EDMS repo 已完成部分）

- [x] Git repo 已建立（`.git`）
- [x] `CLAUDE.md`、`README.md`、`.gitignore` 已建
- [x] `docs/requirements/RQET.md`、`RQDM.md` 已搬
- [x] `docs/_refs/10-教育訓練文件管理模組.md`、`11-文件管理模組.md` 已搬
- [x] `docs/specs/{et,dm}`、`use-cases/{et,dm}`、`wireframes/{et,dm}` 目錄已建
- [x] `docs/guides/`（sti-plan / sti-sa-precheck / sti-sa-publish）已搬
- [x] `.claude/rules` 17 條、`commands` 24 個、`agents` 5 個、`skills` 6 個已搬
- [ ] `backend/` 空 → 待建（見 §3、§4）
- [ ] `frontend/` 空 → 待建

---

## 2. `.claude/` 差異補齊

### 2.1 rules（現 17／建議 19）
- [ ] `sti-architecture-constraints.md` — TBMS 版含「戰時離線 + JWT」。EDMS 不要離線，
      **但仍需確認其他架構硬約束**（是否有非離線的組織級規範）。建議帶過來後刪離線段。
- [ ] `sti-schedule-rules.md` — 條件式：ET/DM 若用 APScheduler 排程才需要（如帳號閒置停用、
      文件到期通知）。用得到再補。

### 2.2 agents（現 5／缺 1 必要）
- [ ] `e2e-runner.md` — ⚠️ **`/sti-implement` 步驟 12 會呼叫**，缺了跑 E2E 會失敗。要補。
- [ ] （選）`architect`、`planner`、`build-error-resolver`、`doc-updater`、`refactor-cleaner`

### 2.3 commands
- [ ] （選）`speckit.*` — 若走規格驅動開發需補，並搭配 `.specify/` 模板；
      若只走 `/sti-sa` 流程則可不用。

### 2.4 skills
- [ ] （選）`backend-patterns`、`frontend-patterns`
- [x] 已正確排除 `learned/`、`continuous-learning*/`（綁舊 repo 記憶，不帶）

---

## 3. 後端 DB 起手包

### 3.1 依賴（`backend/pyproject.toml`）
- [ ] `sqlalchemy[asyncio]>=2.0.48`
- [ ] `asyncpg>=0.31.0`
- [ ] `alembic>=1.18.4`
- [ ] `pydantic-settings>=2.14.2`
- [ ] `greenlet`（多為隱含依賴）
- [ ] dev：`pytest`、`pytest-asyncio`、`pytest-xdist`、`httpx`
- [ ] `[tool.ruff]` 排除 `alembic/versions/`
- [ ] 改 `[project] name` / `description` → EDMS

### 3.2 core（`backend/app/core/`）
原封帶：
- [ ] `db.py`（engine / session / Base / get_db）
- [ ] `base_model.py`（BaseModel + 3 變體）
- [ ] `pagination.py`（paginate helper）
- [ ] `encryption.py`（EncryptedString，AES-256-GCM）
- [ ] `exceptions.py`（AppError）
- [ ] `utils.py`、`instance.py`（`instance.py` 註解範例 `tbms-server-01` 輕改）

改了帶：
- [ ] `config.py` → `APP_NAME`/`MAIL_FROM`/CORS 換 EDMS；⚠️ **刪成分/醫務 Service URL**；
      保留 `DATABASE_URL`、`DB_POOL_SIZE/MAX_OVERFLOW/RECYCLE`、`ENCRYPTION_KEY`

### 3.3 Alembic（`backend/alembic/`）
- [ ] 複製 `alembic.ini`、`alembic/env.py`（非同步版）、`script.py.mako`
- [ ] ⚠️ **`alembic/versions/` 清空**（既有 migration 全綁 TBMS 業務表）
- [ ] `env.py` 的 `target_metadata` 指向 EDMS 的 Base
- [ ] 建 EDMS 第一支 base schema migration

### 3.4 設定檔（env）
- [ ] `.env.example` 留 DB 區塊：`DATABASE_URL=postgresql+asyncpg://...`、`DB_POOL_*`、`ENCRYPTION_KEY`
- [ ] 刪 TBMS 業務專屬 env（成分/醫務 service URL 等）
- [ ] `ENCRYPTION_KEY` 各環境獨立產生（Base64、解碼後 32 bytes），不進 git

### 3.5 測試 DB 骨架（`backend/tests/`）
- [ ] 複製 `conftest.py`、`tests/_xdist_db.py`、`integration/conftest.py`
      （apply_migrations / test_engine / db fixtures）
- [ ] test DB 名 `test_tbms` → `test_edms`（含 xdist `worker_database_url` 前綴）

---

## 4. 認證起手包（自建帳號版）

**組態**：DP_ 前綴沿用｜無戰時離線｜無 MFA｜要寄信｜要權限｜要使用者管理

### 4.1 依賴
- [ ] `PyJWT>=2.13.0`
- [ ] `passlib[bcrypt]>=1.7.4`
- [ ] `cryptography>=48.0.1`（DB 起手包已含）
- [ ] `fastapi-mail`（寄信）

### 4.2 core 認證基礎建設
原封帶：
- [ ] `auth.py`（`decode_jwt` / `JwtPayload` / `get_jwt_payload` / `require_admin`）
- [ ] `request_context.py`（client IP）
- [ ] `operator.py`（OperatorInfo / get_operator）
- [ ] `permission.py` ✅ **不用改**（沿用 DP_，`app.dp.menus/roles` 路徑不變）
- [ ] （選）`api_key.py`（EDMS 要對外 API 才帶）
- [ ] config 補：`JWT_SECRET_KEY`、`JWT_ALGORITHM`、Access TTL 15分、Refresh TTL 8小時、SMTP 設定

### 4.3 認證模組 `app/dp/user/`（複製 → 砍 MFA）
- [ ] `router.py` — 帶；**刪 `login_verify`、`login_resend`（MFA 端點）**，login 改單步直接回 token
- [ ] `service.py` — 帶；移除 MFA 分支，保留登入 / refresh / logout / Token Rotation / 單一登入踢出
- [ ] `repository.py`、`schemas.py`（移除 MFA schema）
- [ ] `models.py`（DP_USER / DP_SESSION / DP_PWD_RESET，表名沿用）
- [ ] `password_policy.py`
- [ ] `email.py`、`email_urls.py`、`account_activation.py`（✅ 寄信）
- [ ] `query_service.py`（視需要）
- [ ] ❌ **刪除 `mfa.py`**

保留端點：`login`（單步）、`refresh_token`、`logout`、`forgot_password`、`reset_password`、
`confirm_account`、`change_password`、`get_me`、`update_profile`、`get_password_policy`、`get_my_client_ip`

### 4.4 權限 RBAC（要）
- [ ] `app/dp/roles/`（角色 CRUD）
- [ ] `app/dp/menus/`（選單/功能權限樹）

### 4.5 使用者管理 DP03（要）
- [ ] `app/dp/users/`（使用者 CRUD、停用、身份別）
- [ ] 分工：`dp/user`=認證、`dp/users`=管理

### 4.6 三張核心表（沿用表名）
- [ ] `DP_USER`：帳號 / 密碼 hash / 狀態 / 鎖定計數 / LAST_LOGIN；`EMAIL` 用 `EncryptedString`
- [ ] `DP_SESSION`：Refresh Token（單一登入 UPSERT 覆蓋）
- [ ] `DP_PWD_RESET`：`TOKEN_TYPE` 只留 **`ACCOUNT_CONFIRM` + `PWD_RESET`**（無 `MFA_OTP`）

### 4.7 稽核（跨模組共通）
- [ ] `app/dp/audit/` + `AuditLogService`（`DP_AUDIT_LOG`，append-only）
- [ ] CUD 操作在 Service 層呼叫 `log_action()`，`res_id` 必填

---

## 5. 文件（`docs/ref/`）補齊

- [x] `ui-design-guide.md`（已在）
- [ ] `jwt_refresh_token_說明.md` → 帶；**刪 MFA 整節 + 戰時離線論述**，表名沿用不改
- [ ] `sti-backend-ref.md` → 帶用法；**例外表清單 / 已加密欄位清單清空重建**
- [ ] `error-codes.md` → 帶格式，錯誤碼內容依 EDMS 重編
- [ ] `Alembic 多人平行開發 Migration 處理指南.md` → 原封帶
- [ ] `dev-workflow.md` → 帶
- [ ] （選）`schedule-guide.md`（用排程才需要）
- [ ] ❌ 不帶：`RUDP001 PPT`、`dp-sequence-切換指引.md`、`gcp/vm/cloudflare` 等 infra（TBMS 生產專屬）

---

## 6. ET / DM 業務文件（大多已搬）

- [x] `docs/requirements/RQET.md`、`RQDM.md`
- [x] `docs/_refs/10-教育訓練文件管理模組.md`、`11-文件管理模組.md`
- [ ] `docs/specs/dm/DM-模組建構概念.md`（確認已搬入）
- [ ] `docs/requirements/RQ0.md` → **重寫**一份只含 ET/DM 的需求總索引（勿整份照搬 TBMS）
- [ ] `docs/specs/et/`、`use-cases/et/`、`wireframes/et/` → ET 待補（原 TBMS 無 spec/UC/wireframe）

---

## 7. 全域換名 / 清業務字串（搬完必做）

在 EDMS repo 跑，凡命中就決定「換名」或「刪除」：
```bash
grep -rniE "TBMS|國軍捐血管理系統|捐血|血品|血型|test_tbms|SRVCP|SRVMA|SRVBS|SRVBC" .
```
已知熱點：
- [ ] `frontend/src/components/AppHeader.tsx`、`hooks/usePageTitle.ts`（「國軍捐血管理系統」標題）
- [ ] `frontend/src/constants/storage.ts`（`tbms_war_mode` 等 key）
- [ ] `frontend/src/constants/queryKeys.ts`（刪業務模組 query keys）
- [ ] `frontend/src/utils/bloodDisplay.ts`（❌ 血品專屬，不帶）
- [ ] `CLAUDE.md` 的「詳細規則索引」表 → 對齊 EDMS 實際留下的 rules

---

## 8. 驗收

```bash
cd backend
uv sync                       # 依賴可裝
uv run alembic upgrade head   # migration 可跑（versions 為 EDMS 自己的）
uv run pytest -q              # 測試框架可啟動

# 認證/權限測試
uv run pytest tests/**/*login* tests/**/*auth* tests/**/*role* -q

# 殘留檢查（應查無 MFA / 業務字串）
grep -rniE "mfa|otp|login_verify|login_resend" backend/app/dp/user/
grep -rniE "TBMS|捐血|血品|SRVCP|SRVMA" backend/
```

---

## 附錄：不帶清單（明確排除）

- ❌ 業務模組：`bc`（採血）、`cp`（成分）、`tl`（檢驗）、`bs`（供應）、`ma`（醫務）、`lb`（標籤）
- ❌ 血品/條碼專屬：`tools/isbt_barcode.py`、`utils/bloodDisplay.ts`
- ❌ TBMS 生產 infra：`docs/infra/*`（GCP/VM/Cloudflare/DB 真實值）、`scripts/gen_rudp001_ppt.py`
- ❌ 舊 repo 記憶：`.claude/skills/learned/`、`continuous-learning*/`
- ❌ Alembic `versions/`（既有 migration 全綁 TBMS 業務表）
