---
description: 前端共用模組清單，開發 frontend 時載入
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# 前端共用模組

開發新功能前先確認是否有現成模組，禁止重複造輪子。

> **本清單以 EDMS 實際程式碼為準**（前端 toolkit 自 US4 起逐步 bootstrap）。EDMS 為單一組織、無 station /
> war-mode 維度。文末「規劃中／尚未實作」列出目前**不存在**、勿直接引用的符號。

---

### `CrudPageLayout` · `src/components/CrudPageLayout.tsx`
CRUD 列表頁骨架（標題列 + 篩選 / 操作 + 表格 + 分頁 + 表單 slot）。**禁止手動拼裝 `<Box>` + `<Paper>`。**
目前僅 **props 版 API**（無 compound 子元件、無 `editMode` prop、無 `usePageTitle`；`title` 傳純字串直接顯示）。

```tsx
<CrudPageLayout
  icon={<Settings />}
  title="頁面標題"
  filterContent={...}          // 篩選列（TextField / Tabs 等）
  actions={<CrudActions .../>} // 右上操作區
  table={<AppTable columns={columns} data={items} rowKey="id" loading={isPending} />}
  pagination={<Pagination page={page} total={meta?.total ?? 0} onPageChange={setPage} />}
  form={formVisible && <SomeForm />}  // 表格下方展開的表單
/>
```

---

### `useCrudForm<T>` · `src/hooks/useCrudForm.ts`
CRUD 表單狀態管理。**新建 CRUD hook 時一律使用，禁止手寫 formVisible / editingRecord / saving 開關邏輯。**
不包含 `handleSave`（各頁 API 簽名不同），由各頁 hook 自行實作。

```tsx
const {
  formVisible, editingRecord, saving, setSaving,
  openCreate, openEdit, closeForm,
} = useCrudForm<RefCode>({
  onClose: () => setExtraState(null),  // 選填：關閉時額外清理
})
```

若需覆寫 `openCreate`（如清除額外狀態），包一層 `useCallback` 即可：
```tsx
const { openCreate: baseOpenCreate, closeForm, ...rest } = useCrudForm<User>()
const openCreate = useCallback(() => { resetExtra(); baseOpenCreate() }, [baseOpenCreate])
```

---

### `AppTable<T>` · `src/components/AppTable.tsx`
統一表格。欄位以 `AppColumn<T>` 定義；`rowKey` 取列的唯一鍵（欄位名或函式）。

```tsx
import type { AppColumn } from "../../components/AppTable"

const columns: AppColumn<Row>[] = [
  { key: "name", title: "名稱", dataIndex: "name" },          // dataIndex 直取值
  { key: "status", title: "狀態", render: (_v, r) => <Chip .../> }, // render 優先於 dataIndex
  { key: "actions", title: "操作", render: (_v, r) => <Button .../> },
]
<AppTable columns={columns} data={items} rowKey="id" loading={isPending} emptyText="查無資料" />
```
`AppColumn`：`{ key, title, dataIndex?, align?, width?, render? }`。

---

### `FormCard` · `src/components/FormCard.tsx`
CRUD 表單卡片殼（**非 Modal**，綠色 2px 邊框、展開時捲動至此、Enter 送出）。單一 `onSave` / `onCancel`。

```tsx
<FormCard title="編輯" onSave={handleSave} onCancel={closeForm} saving={saving}>
  <TextField ... />
</FormCard>
```

---

### `CrudActions` · `src/components/CrudActions.tsx`
「重新整理 + 新增」按鈕組。**CRUD 頁面 actions 一律使用。**

```tsx
<CrudActions onRefresh={refresh} onAdd={openCreate} />
<CrudActions onRefresh={refresh} onAdd={openCreate} addLabel="建立帳號" />  // 自訂新增鈕文字
<CrudActions onRefresh={refresh} />  // 唯讀頁面，省略 onAdd 不渲染新增按鈕
```

---

### `usePagedQuery` · `src/hooks/usePagedQuery.ts`
後端分頁查詢。**禁止裸用 `useQuery` 或在 `useEffect` 內呼叫 axios。**
ESLint `no-restricted-syntax` 會攔截直接呼叫 `fetch`/`axios`，但別名匯入（如 `import api from '../services/http'`）無法攔截，需 Code Review 把關。

```tsx
const { data, isPending, invalidate } = usePagedQuery(
  QUERY_KEYS.xxx.list({ page, limit }),
  () => xxxApi.list({ page, limit }),
)
const items = data?.data ?? []
const meta  = data?.meta  // { total, page, limit, total_pages }
```

---

### `useDebouncedValue<T>` · `src/hooks/useDebouncedValue.ts`
去抖動值：`value` 停止變動 `delayMs` 後才更新回傳值。用於輸入即時查詢（避免每字元一次 request）。

```tsx
const debounced = useDebouncedValue(keyword, 350)
useEffect(() => { search(debounced) }, [debounced, search])
```

---

### `QUERY_KEYS` · `src/constants/queryKeys.ts`
所有 query key 統一管理。新增模組時在此補上對應群組（全小寫 + 連字號）。

```tsx
QUERY_KEYS.xxx.list({ page, limit })   // 列表
```

---

### `Pagination` · `src/components/Pagination.tsx`
`total === 0` 時自動隱藏。切換 pageSize 時自動回第 1 頁。

```tsx
<Pagination page={page} total={meta?.total ?? 0} onPageChange={setPage} />
<Pagination page={page} total={meta?.total ?? 0} onPageChange={setPage}
  pageSize={limit} onPageSizeChange={setLimit} />
```

---

### `useNotification` · `src/contexts/NotificationContext.tsx`
全域通知與確認對話框，禁止使用原生 `alert` / `confirm`。

```tsx
const { message, confirm } = useNotification()
message.success('操作成功') / message.error('操作失敗')
confirm({ title: '確認刪除', content: '...', okText: '確認', danger: true, onOk: async () => {...} })
```

---

### `toApiError` · `src/services/http.ts`
把 axios 例外正規化為 `{ status, errorCode, errorMessage, retryAfter? }`（對齊後端 `error_code` / `error_message`）。

```tsx
import { toApiError } from "../services/http"
catch (err) { message.error(toApiError(err).errorMessage) }
```

---

### `useAuth` · `src/auth/useAuth.ts`
取得認證狀態（`AuthContext`），須在 `<AuthProvider>` 內使用。**回傳 `AuthState`**（非使用者個資）：

```tsx
const { token, isAuthenticated, mustChangePwd, sessionExpired, login, logout, clearMustChangePwd } = useAuth()
```
> Access token 為 **memory-only**（`AuthProvider` state ＋ `services/http.ts` 模組變數），重整即失效、需重新登入——不落 localStorage（XSS 防護，US1 決策）。
> 使用者個資（姓名 / Email）另由 `GET /dp/user/me`（`profileApi.getMe`，`PROFILE_ME_QUERY_KEY`）取得，非放在 `useAuth`。

---

### `date.ts` · `src/utils/date.ts`
時間顯示用此模組，禁止 `new Date(...).toLocaleString(...)` 或自行時區換算。
目前僅提供 **`formatDateTime(value)`**（`YYYY/MM/DD HH:mm` 本地，null/undefined 回空字串）。其餘格式化函式尚未建，需要時於此新增。

---

### `Sidebar` · `src/components/Sidebar.tsx`
統一 shell 左側導覽，於 `src/layouts/AppShell.tsx` 使用。導覽項目來自 **`src/layouts/navItems.ts` 的 `NAV_GROUPS`**（模組群組可收合），非 API 選單樹、無 icon 映射檔。新增後台功能項在 `navItems.ts` 的對應群組補上即可。

---

## 頁面組合範本

> `useCrudForm` + `CrudPageLayout` + `CrudActions` + `AppTable` + `usePagedQuery` + `useNotification` 的標準組合。

```tsx
// ── Hook（useXxx.ts）──
export function useXxx() {
  const { message } = useNotification()
  const { formVisible, editingRecord, saving, setSaving, openCreate, openEdit, closeForm } = useCrudForm<Xxx>()

  const [page, setPage] = useState(1)
  const { data, isPending, invalidate } = usePagedQuery(
    QUERY_KEYS.xxx.list({ page }),
    () => xxxApi.list({ page }),
  )
  const items = data?.data ?? []

  const handleSave = useCallback(async (values: XxxCreate | XxxUpdate) => {
    setSaving(true)
    try {
      if (editingRecord) { await xxxApi.update(editingRecord.id, values as XxxUpdate); message.success('更新成功') }
      else { await xxxApi.create(values as XxxCreate); message.success('新增成功') }
      closeForm(); invalidate()
    } catch (err) {
      message.error(toApiError(err).errorMessage)
    } finally { setSaving(false) }
  }, [editingRecord, message, closeForm, invalidate, setSaving])

  return { items, loading: isPending, total: data?.meta?.total ?? 0, page, setPage,
    refresh: invalidate, formVisible, editingRecord, saving, openCreate, openEdit, closeForm, handleSave }
}

// ── Page（XxxListPage.tsx）──
export const XxxListPage = () => {
  const { items, loading, total, page, setPage, refresh,
    formVisible, editingRecord, saving, openCreate, openEdit, closeForm, handleSave } = useXxx()

  const columns: AppColumn<Xxx>[] = useMemo(() => [
    { key: 'name', title: '名稱', dataIndex: 'name' },
    { key: 'actions', title: '操作', render: (_v, r) => (
      <Button size="small" onClick={() => openEdit(r)}>編輯</Button>
    )},
  ], [openEdit])

  return (
    <CrudPageLayout
      icon={<Settings />} title="XXX 管理"
      actions={<CrudActions onRefresh={refresh} onAdd={openCreate} />}
      table={<AppTable columns={columns} data={items} rowKey="id" loading={loading} />}
      pagination={<Pagination page={page} total={total} onPageChange={setPage} />}
      form={formVisible && <XxxForm editingRecord={editingRecord} saving={saving}
        onSave={handleSave} onCancel={closeForm} />}
    />
  )
}
```

---

## 規劃中／尚未實作（勿直接引用）

以下符號目前**不存在於 EDMS 前端**（多為 TBMS 母專案有、EDMS 尚未 bootstrap 或不適用）。實作後再補回本清單：

| 符號 | 狀態 |
|------|------|
| `statusColumn` / `utils/columnFactories.tsx` | 未建（EDMS 狀態多為衍生值，非 `is_active`）|
| `useInlineEdit`、`CrudPageLayout` 的 `editMode` / compound 子元件（`.Header`…）| 未建（CrudPageLayout 僅 props 版）|
| `usePageTitle` | 未建 |
| `extractApiError`、`STORAGE_KEYS` / `constants/storage.ts` | 不存在（用 `toApiError`；localStorage 目前無共用常數）|
| `useMenu`、`useWarMode` / `WarModeContext`、`ProtectedRoute`、`AppLayout`、`sidebarIcons.ts` | 不存在（EDMS 無 API 選單樹 / war-mode；登入守衛由 `RootLayout` + `LoginOverlay` 處理；shell 為 `AppShell`）|
| `useAuth` 回 `{ full_name, station_name, roles }` + `clearUserCache` | 錯誤形狀（實為 `AuthState`，見上）|
| `date.ts` 的 `formatLocalDatetime` / `formatDate` / `fromNow` / `localInputToUTC` / `utcToLocalInput` | 未建（僅 `formatDateTime`）|
