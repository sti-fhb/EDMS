---
description: 前端頁面 UI 規範，開發前端時載入
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# 前端頁面 UI 規範

## 強制規則

開發新的前端頁面或修改既有頁面佈局時，**必須**先閱讀並遵循：

- `docs/ref/ui-design-guide.md` — 頁面級 UI 規範（佈局、元件樣式、色彩、RWD）

## 適用情境

- 新增 CRUD 列表頁、掃碼作業頁、報表頁、明細頁等任何功能頁面
- 新增或修改共用 UI 元件（卡片、篩選列、狀態 Badge 等）
- 修改既有頁面佈局或交互模式

## 已有共用元件 — 必須使用

以下元件已封裝完成，**禁止自行重新實作**：

| 元件 | 路徑 | 用途 |
|------|------|------|
| `CrudPageLayout` | `src/components/CrudPageLayout.tsx` | **CRUD 列表頁骨架**（標題列 + 篩選 / 操作 + 表格 + 分頁 + 表單 slot；props 版） |
| `AppShell` | `src/layouts/AppShell.tsx` | 登入後主佈局（頂列 + 可收合側欄 + 內容區） |
| `Sidebar` | `src/components/Sidebar.tsx` | 側欄導覽（項目來自 `layouts/navItems.ts` 的 `NAV_GROUPS`） |
| `AppHeader` | `src/components/AppHeader.tsx` | 頂部 Navbar（標題 + 個資選單 + 側欄切換） |
| `AppTable` | `src/components/AppTable.tsx` | 統一表格（`AppColumn<T>` 定義欄位） |
| `FormCard` | `src/components/FormCard.tsx` | 表單卡片容器（綠色 2px 邊框、max-width 600、展開式） |
| `Pagination` | `src/components/Pagination.tsx` | 分頁列（含 pageSize selector） |
| `CrudActions` | `src/components/CrudActions.tsx` | 重新整理 + 新增 按鈕組 |
| `useNotification` | `src/contexts/NotificationContext.tsx` | 通知 / 確認對話框 |

> ⚠️ 下列元件**目前 EDMS 不存在**（TBMS 母專案有、EDMS 未 bootstrap 或不適用），勿引用：`AppLayout`、`Breadcrumb`、`ScreenHeader`、`StatusChip`、`ProtectedRoute`、`useWarMode` / 戰時模式。狀態標籤目前各頁自行以 MUI `Chip` 呈現；登入守衛由 `RootLayout` + `LoginOverlay` 處理。詳見 `sti-frontend-modules.md`「規劃中／尚未實作」。

### CRUD 列表頁必須使用 `CrudPageLayout`

所有 CRUD 列表頁**禁止手動拼裝** `<Box>` + `<Paper>` 版面，**必須使用 `<CrudPageLayout>`**。

```tsx
// ✅ 正確：使用 CrudPageLayout
<CrudPageLayout
  icon={<Settings />}
  title="系統參數管理"
  filterContent={<TextField size="small" placeholder="搜尋..." />}
  actions={<Button variant="contained" size="small">新增</Button>}
  table={<AppTable columns={columns} data={items} rowKey="id" loading={loading} />}
  pagination={<Pagination page={page} total={total} onPageChange={setPage} />}
  form={formVisible && <RefCodeForm ... />}
/>

// ❌ 錯誤：手動拼裝版面
<Box>
  <Stack direction="row" alignItems="center" spacing={1}>
    <Settings /> <Typography variant="h5">系統參數管理</Typography>
  </Stack>
  <Paper variant="outlined" sx={{ p: 2 }}>
    <Box sx={{ display: "flex", justifyContent: "space-between" }}>...</Box>
    <AppTable ... />
    <Pagination ... />
  </Paper>
  <FormCard ... />
</Box>
```

> 表單以 `form` slot 傳入、於表格下方展開 `FormCard`（`CrudPageLayout` 目前無 `editMode` prop、無行內編輯模式；`useInlineEdit` 尚未實作）。

## 尚未封裝的元件 — 依規範實作

以下元件尚未封裝為共用元件，開發時**依 `ui-design-guide.md` 對應章節的規範實作**。

| 元件 | 對應章節 | 說明 |
|------|---------|------|
| 掃碼輸入區 | §9 | 淺黃背景、黃色虛線邊框 |

## 色彩與 Icon 規範

- **禁止硬編碼色碼**，一律使用 MUI Theme Token（`palette.primary.main` 等）或 `useTheme()` 取得
  - 掃碼輸入區用 `warning.light`（背景）/ `warning.dark`（邊框），muiTheme.ts 已對齊 ui-design-guide §9 色碼
- Icon 對照表見 `ui-design-guide.md` §24，使用 `@mui/icons-material`
- 色彩對照表見 `ui-design-guide.md` §23

## 快速參考（完整規範見 ui-design-guide.md）

| 元素 | 規範摘要 |
|------|---------|
| 卡片 | 白底、`1px solid #dee2e6`、圓角 `8px`、內距 `1rem` |
| 表格 | 字體 `0.88rem`、表頭 `#f8f9fa`、啟用 hover 高亮 |
| 表單 | 卡片內展開（非 Modal）、綠色 2px 邊框、`max-width: 500~600px` |
| 按鈕 | 主要 = `contained primary`、次要 = `outlined`、危險 = `outlined error` |
| 按鈕大小 | 一般 `size="small"`，掃碼確認可用預設大小 |
| RWD | Desktop > 992px、Tablet ≤ 991px（Sidebar overlay）、Mobile ≤ 767px |
