---
description: 前端共用模組清單，開發 frontend 時載入
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# 前端共用模組

開發新功能前先確認是否有現成模組，禁止重複造輪子。

---

### `CrudPageLayout` · `src/components/CrudPageLayout.tsx`
所有 CRUD 列表頁骨架。**禁止手動拼裝 `<Box>` + `<Paper>`，一律用此元件。**

```tsx
// 標準用法（80%）
<CrudPageLayout
  icon={<Settings />} title="頁面標題"
  filterContent={...} actions={...}
  table={<AppTable columns={columns} data={items} rowKey="id" loading={isPending} />}
  pagination={<Pagination page={page} total={meta?.total ?? 0} onPageChange={setPage} />}
  form={formVisible && <SomeForm />}
/>

// 客製化用法（20%）
<CrudPageLayout>
  <CrudPageLayout.Header icon={...} title="..." />
  <CrudPageLayout.Filter>...</CrudPageLayout.Filter>
  <CrudPageLayout.Actions>...</CrudPageLayout.Actions>
  <CrudPageLayout.Content>...</CrudPageLayout.Content>
  <CrudPageLayout.Pagination>...</CrudPageLayout.Pagination>
</CrudPageLayout>
```
`editMode="formCard"`（預設）或 `"inline"`（行內編輯，搭配 `useInlineEdit`）

**注意**：`title` 傳純字串即可，內部自動呼叫 `usePageTitle` 解析標題與功能代碼，不需手動呼叫。

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

### `CrudActions` · `src/components/CrudActions.tsx`
「重新整理 + 新增」按鈕組。**CRUD 頁面 actions 一律使用，禁止手寫重複的 Button 組合。**

```tsx
<CrudActions onRefresh={refresh} onAdd={openCreate} />
<CrudActions onRefresh={refresh} />  // 唯讀頁面，省略 onAdd 不渲染新增按鈕
```

---

### `statusColumn<T>()` · `src/utils/columnFactories.tsx`
is_active 狀態欄位工廠。**表格有 is_active 欄位時一律使用，禁止手寫 StatusChip 渲染。**

```tsx
statusColumn<Site>()                    // 預設讀取 is_active（T 須含 is_active: number）
statusColumn<Device>("device_status")   // 指定其他欄位
```

---

### `useInlineEdit` · `src/hooks/useInlineEdit.ts`
管理行內新增/編輯狀態，搭配 `editMode="inline"` 使用。

```tsx
const { isAdding, editingId, editValues, saving, startAdd, startEdit, cancel, setField, save } =
  useInlineEdit<T>({ onSave: async (values) => { /* call API */ } })
```

---

### `usePagedQuery` · `src/hooks/usePagedQuery.ts`
後端分頁查詢。**禁止裸用 `useQuery` 或在 `useEffect` 內呼叫 axios。**
ESLint `no-restricted-syntax` 會攔截直接呼叫 `fetch`/`axios`，但別名匯入（如 `import api from '../services/http'`）無法攔截，需 Code Review 把關。

```tsx
const { data, isPending } = usePagedQuery(
  QUERY_KEYS.xxx.list({ page, limit }),
  () => xxxApi.list({ page, limit }),
)
const items = data?.data ?? []
const meta  = data?.meta  // { total, page, limit, total_pages }
```

---

### `QUERY_KEYS` · `src/constants/queryKeys.ts`
所有 query key 統一管理。新增模組時在此補上對應群組（全小寫 + 連字號）。

```tsx
QUERY_KEYS.xxx.list({ page, limit })   // 列表
QUERY_KEYS.xxx.detail(id)              // 單筆
```

---

### `STORAGE_KEYS` · `src/constants/storage.ts`
localStorage 存取一律用此常數，禁止硬編碼字串。**僅用於非敏感的 UI 偏好 / 一次性旗標**
（如歡迎橫幅已顯示、清單頁面大小），禁止存放認證 token 或任何機密。

```tsx
localStorage.setItem(STORAGE_KEYS.WELCOME_DISMISSED, "1")
```

> ⚠️ **Access token 一律 memory-only，禁止落 localStorage**（US1 決策）。
> JWT access token 只存記憶體（`AuthProvider` React state ＋ `services/http.ts` 模組變數），
> 由 `setAuthToken()` 同步給 axios interceptor；重整即失效、需重新登入。理由：localStorage 對所有同源
> JS 完全可讀，是 XSS 竊取 session token 的頭號目標；memory-only 把 token 暴露窗口縮到最短，
> 搭配短 TTL（15 分）＋ 活動換發維持體驗。參考實作見 `src/auth/AuthProvider.tsx`、`src/services/http.ts`。

---

### `Pagination` · `src/components/Pagination.tsx`
`total === 0` 時自動隱藏。切換 pageSize 時元件內部自動 `onPageChange(1)`。

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

### `extractApiError` · `src/utils/extractApiError.ts`
從 catch 提取後端錯誤訊息（優先讀 `error_message`，其次 `detail`）。

```tsx
catch (err) { message.error(extractApiError(err, '操作失敗')) }
```

---

### `useAuth` · `src/hooks/useAuth.ts`
取得登入者資訊，module-level 快取。登出時須呼叫 `clearUserCache()`。

```tsx
const { user, loading } = useAuth()
// user: { full_name, station_name, roles } | null
```

---

### `useMenu` · `src/hooks/useMenu.ts`
取得角色選單樹。登出時須呼叫 `clearMenuCache()`。

```tsx
const { menu, loading } = useMenu()
const label = getMenuLabelByPath('/donors')
```
**登出時**：必須同時呼叫 `clearUserCache()` 與 `clearMenuCache()`。

---

### `useWarMode` · `src/contexts/WarModeContext.tsx`

```tsx
const { isWarMode, toggleWarMode } = useWarMode()
```

---

### `ProtectedRoute` · `src/components/ProtectedRoute.tsx`
未登入自動導向 `/login`，包住所有需要登入的路由。

```tsx
// router/index.tsx
<Route element={<ProtectedRoute />}>
  <Route path="/dp/sites" element={<SiteListPage />} />
</Route>
```

---

### `date.ts` · `src/utils/date.ts`
時間顯示一律用此模組，禁止 `new Date(...).toLocaleString(...)` 或自行時區換算。

| 場景 | 工具 |
|------|------|
| 完整時間（`YYYY/MM/DD HH:mm:ss` 本地） | `formatLocalDatetime(value)` |
| 僅日期 | `formatDate(value)` |
| 日期時間無秒 | `formatDateTime(value)` |
| 相對時間 | `fromNow(value)` |
| `datetime-local` input → API | `localInputToUTC(value)` |
| API → `datetime-local` input | `utcToLocalInput(value)` |

---

### `AppLayout` · `src/components/AppLayout.tsx`
Sidebar（260px）+ Navbar（48px）+ Content 主佈局，直接使用，不需自行組裝。

### `Sidebar` · `src/components/Sidebar.tsx`
新增模組時在 `src/components/sidebarIcons.ts` 補上 icon 映射（key = `MenuItem.name`）。

---

## 頁面組合範本

> 以下為 `useCrudForm` + `CrudPageLayout` + `CrudActions` + `statusColumn` + `usePagedQuery` + `useNotification` 的標準組合。

```tsx
// ── Hook（useXxx.ts）──
export function useXxx() {
  const { message, confirm } = useNotification()
  const {
    formVisible, editingRecord, saving, setSaving,
    openCreate, openEdit, closeForm,
  } = useCrudForm<Xxx>()

  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(10)

  const { data, isPending, invalidate } = usePagedQuery(
    QUERY_KEYS.xxx.list({ page, limit }),
    () => xxxApi.list({ page, limit }),
  )
  const items = data?.data ?? []
  const meta = data?.meta

  const handleSave = useCallback(async (values: XxxCreate | XxxUpdate) => {
    setSaving(true)
    try {
      if (editingRecord) {
        await xxxApi.update(editingRecord.id, values as XxxUpdate)
        message.success('更新成功')
      } else {
        await xxxApi.create(values as XxxCreate)
        message.success('新增成功')
      }
      closeForm()
      invalidate()
    } catch (err) {
      message.error(extractApiError(err, editingRecord ? '更新失敗' : '新增失敗'))
    } finally {
      setSaving(false)
    }
  }, [editingRecord, message, closeForm, invalidate, setSaving])

  return {
    items, loading: isPending, total: meta?.total ?? 0, page, setPage,
    refresh: invalidate, formVisible, editingRecord, saving,
    openCreate, openEdit, closeForm, handleSave,
  }
}

// ── Page（XxxListPage.tsx）──
export const XxxListPage = () => {
  const { items, loading, total, page, setPage, refresh,
    formVisible, editingRecord, saving, openCreate, openEdit, closeForm, handleSave,
  } = useXxx()

  const columns: AppColumn<Xxx>[] = useMemo(() => [
    { key: 'name', title: '名稱', dataIndex: 'name' },
    statusColumn<Xxx>(),
    { key: 'actions', title: '操作', render: (_v, r) => (
      <Button size="small" onClick={() => openEdit(r)}>編輯</Button>
    )},
  ], [openEdit])

  return (
    <CrudPageLayout
      icon={<Settings />}
      title="XXX 管理"
      actions={<CrudActions onRefresh={refresh} onAdd={openCreate} />}
      table={<AppTable columns={columns} data={items} rowKey="id" loading={loading} />}
      pagination={<Pagination page={page} total={total} onPageChange={setPage} />}
      form={formVisible && <XxxForm editingRecord={editingRecord} saving={saving}
        onSave={handleSave} onCancel={closeForm} />}
    />
  )
}
```
