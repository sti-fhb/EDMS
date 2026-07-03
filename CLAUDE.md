# EDMS 專案技術規範

## 語言偏好

預設使用**繁體中文**（回應、文件、程式碼註解、docstring、commit message）。思考過程不限語言，以推理品質優先。程式碼本體保留原始語言。

## 技術棧

| 層級 | 技術 | 版本 |
|------|------|------|
| 前端 | React + MUI | React 19、MUI 7 |
| 前端路由 | React Router | v7 |
| 前端查詢快取 | TanStack Query | v5 |
| 後端 | FastAPI | 0.115+ |
| ORM | SQLAlchemy + Alembic | SQLAlchemy 2 |
| 資料庫 | PostgreSQL | 17 |

## 前端架構原則

- 一律使用 TypeScript（`.ts` / `.tsx`），禁止新增 `.js` / `.jsx` 檔案
- 依功能/領域組織，不依型別：每個模組自含 pages、hooks、services、schemas
- Client-side 分頁：僅限資料量 < 200 筆的管理類設定資料，使用 `usePagination` hook；其餘一律後端分頁

## 啟動開發環境 SOP

1. 啟動或測試前，先確認 `backend/.env` 與 `frontend/.env` 存在。若不存在，提醒開發者從 `.env.example` 複製
2. 不要自行猜測啟動方式，一律先讀取 `README.md`「啟動開發環境」章節並照著執行

## 詳細規則索引

下列 rules 檔各自帶有 `paths:` frontmatter，Claude 開發對應路徑的程式碼時會自動載入到 context。新增 rule 時必須補上 frontmatter，否則不會被載入。

| 主題 | 檔案 |
|------|------|
| 命名慣例（檔案 / 函式 / class / DB） | `.claude/rules/sti-naming-conventions.md` |
| 程式碼風格（immutability、安全、註解） | `.claude/rules/sti-coding-style.md` |
| API 路徑與目錄結構 | `.claude/rules/sti-api-routes.md` |
| API Error Code 命名 | `.claude/rules/sti-error-codes.md` |
| CI 合規（ruff / ESLint / 覆蓋率門檻） | `.claude/rules/sti-ci-compliance.md` |
| 測試規範（TDD、MSW、整合測試） | `.claude/rules/sti-testing.md` |
| 後端模組邊界（API-First 隔離） | `.claude/rules/sti-backend-boundaries.md` |
| 後端共用模組（分層、paginate、AppError、BaseModel、刪除策略） | `.claude/rules/sti-backend-modules.md` |
| 後端應用層 log | `.claude/rules/sti-backend-logging.md` |
| Alembic migration | `.claude/rules/sti-alembic-rules.md` |
| 前端共用模組（CrudPageLayout、useCrudForm、usePagedQuery 等） | `.claude/rules/sti-frontend-modules.md` |
| 前端頁面 UI 規範 | `.claude/rules/sti-ui-design.md` |
| Zod 表單驗證 | `.claude/rules/sti-zod-conventions.md` |
| Spec / UC / RQ 文件撰寫（禁建模工具字眼與 GUID） | `.claude/rules/sti-spec-style.md` |
| Spec / Wireframe 目錄結構（對齊 BS 典範模式） | `.claude/rules/sti-spec-structure.md` |
| Git 工作流程（commit 格式） | `.claude/rules/git-workflow.md` |

## 參考文件

- 認證機制（JWT + Refresh Token）：`docs/ref/jwt_refresh_token_說明.md`（待補：排到認證模組、開始設計登入時撰寫 EDMS 版）
- UI 設計指引：`docs/ref/ui-design-guide.md`
- 後端共用模組補充（BaseModel 變體、刪除策略例外表、AuditLog 用法）：`docs/ref/sti-backend-ref.md`（待補：開發中遇到第一個刪除/加密例外時建檔）
