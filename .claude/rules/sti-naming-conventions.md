---
description: 命名慣例規範，寫前後端或 migration 時載入
paths:
  - "backend/**/*.py"
  - "frontend/src/**/*.{ts,tsx}"
  - "backend/alembic/**/*.py"
---

# 命名慣例規範

## 規則總表

| 類別 | 規則 | 範例 |
|------|------|------|
| React 元件 / 頁面 | PascalCase | `DonorListPage.tsx`、`RefCodeFormModal.tsx` |
| Hook | camelCase + `use` 前綴 | `useAuth.ts`、`usePagedQuery.ts` |
| 前端 API 函數 | camelCase | `getDonorList()`、`updateBloodUnit()` |
| 前端型別 / Interface | PascalCase | `DonorListItem`、`PageMeta` |
| 後端 Python 函式 / 變數 / 檔案 | snake_case | `get_ref_codes()`、`donor_service.py` |
| 後端 class（Service / Repository）| PascalCase 單數 | `RefCodeService`、`AuthRepository` |
| 後端 API endpoint | kebab-case | `/ref-codes`、`/blood-units` |
| 資料庫 Table | UPPER_SNAKE_CASE，格式 `{MODULE}_{TABLE}` | `DP_SITE`、`DP_USER_ROLE`、`DP_AUDIT_LOG` |
| 資料庫欄位 | UPPER_SNAKE_CASE | `SITE_ID`、`CREATED_USER`、`IS_ACTIVE`、`DELETED` |
| 資料庫 CONSTRAINT | `{TYPE}_{模組}_{TABLE}_{DESCRIPTION}`，全 UPPER_SNAKE_CASE | `PK_DP_ROLE`、`FK_DP_ROLE_SITE`、`UQ_DP_COMPDEVICE_IP` |

## CONSTRAINT 命名規則

格式：`{TYPE}_{模組}_{TABLE}_{DESCRIPTION}`

| 區段 | 說明 | 範例 |
|------|------|------|
| TYPE | `PK_`（主鍵）/ `FK_`（外鍵）/ `UQ_`（唯一） | `PK_`、`FK_`、`UQ_` |
| 模組 | 同 Table 的模組代碼（DP、BC、CP…） | `DP_`、`BC_` |
| TABLE | Table 名去掉模組前綴的部分 | `ROLE`、`USER_ROLE`、`COMPDEVICE` |
| DESCRIPTION | FK 標明參考的目標（`_SITE`、`_USER`）；PK/UQ 可省略 | `_SITE`、`_IP` |

**範例**：

| CONSTRAINT 名稱 | 說明 |
|----------------|------|
| `PK_DP_ROLE` | DP_ROLE 主鍵 |
| `FK_DP_ROLE_SITE` | DP_ROLE → DP_SITE 外鍵 |
| `FK_DP_USER_ROLE_ROLE` | DP_USER_ROLE → DP_ROLE 外鍵（複合） |
| `UQ_DP_COMPDEVICE_IP` | DP_COMPDEVICE.CDE_IPV4 唯一 |

**規則**：
- 複合 FK 必須對齊目標 Table 的完整 PK 欄位，不可只參考部分 PK

## 重點提醒

- **前端檔案禁止使用 `.js` / `.jsx`**，一律 `.ts` / `.tsx`
- **後端 class 用單數**：`RolesService` → 應為 `RoleService`（複數僅 Table 名稱使用）
- **共用欄位**（`CREATED_USER`、`CREATED_DATE`、`UPDATED_USER`、`UPDATED_DATE`、`RES_ID`、`DELETED`）由 `BaseModel` 統一繼承，不重複定義，詳見 `sti-backend-modules.md`（EDMS 單一組織、無 SITE 維度）
