---
description: 測試規範，開發前後端時載入
paths:
  - "backend/**/*.py"
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
---

# 測試規範

## 最低測試覆蓋率：80%

## 測試驅動開發（TDD）

強制工作流程：
1. 先寫測試（RED）
2. 執行測試 — 應該**失敗**
3. 撰寫最小實作（GREEN）
4. 執行測試 — 應該**通過**
5. 重構（IMPROVE）
6. 確認覆蓋率（80%+）

---

## 後端測試（Python / pytest）

測試類型：
1. **Unit Tests** — 個別函式，不連 DB，放 `tests/unit/`，加 `pytestmark = pytest.mark.unit`
2. **Integration Tests** — API Endpoint + 真實 DB，放 `tests/integration/`，加 `pytestmark = pytest.mark.integration`
3. **E2E Tests** — Playwright，關鍵業務流程（規劃中）

### integration vs unit 取捨

新增整合測試前先自問：**拿掉真 DB，這條還驗得了嗎？** 驗得了 → 寫成 unit，不寫 integration。

整合測試只驗「接線」，每個端點僅保留：
- happy path：寫入後讀回，驗證確實持久化
- 一條代表性的 DB 相關業務規則（重複 → 409、軟刪除後查不到、流水號遞增等）
- auth 邊界抽樣驗一次（同模組不必每端點都重測 401）

以下一律寫 unit，禁止寫成 integration：
- 輸入驗證（422：缺必填、空 body、多餘欄位、`limit` 超上限）
- Pydantic schema 形狀、欄位互斥
- 純函式業務規則、error code 對應
- 重複的 401（同一 auth dependency 已被其他 test 覆蓋）

以下一律**不寫任何測試**（unit / integration 皆不寫）：
- migration / seed 的 schema 驗收（表存在、欄位型別、欄位數、PK / FK、`DELETED` 有無、某 seed 已存在、某型別已轉成 timestamptz）；schema 與 seed 變更由對應模組的 service / API integration test 間接覆蓋，詳見 `sti-alembic-rules.md`

### 測試目錄結構

- 新模組測試檔案必須放置於 `backend/tests/{integration|unit}/{module}/` 子目錄，不得平鋪於 `integration/`、`unit/` 上層。
- 子目錄須有 `__init__.py`。
- 例外：`test_core_*.py`（`app/core/` 基礎設施）留上層。

### 後端測試檔案命名規則

格式：`test_{模組}_{功能}.py`

| 範例 | 說明 |
|------|------|
| `test_dp_sites_crud.py` | dp 模組 sites 功能的 CRUD 測試 |
| `test_dp_user_forgot_password.py` | dp 模組 user 功能的忘記密碼測試 |
| `test_core_jwt.py` | core 模組 JWT 單元測試 |
| `test_core_pagination.py` | core 模組分頁單元測試 |

- 前端測試：與被測檔案同名同目錄（`SiteListPage.test.tsx`），不需模組前綴

執行指令：
```bash
pytest -m unit          # 快速，不需 DB
pytest -m integration   # 需要 DB
pytest                  # 全部
pytest --cov            # 含覆蓋率（CI 使用）
```

設定說明：
- `asyncio_mode = "auto"`，不需每個測試加 `@pytest.mark.asyncio`
- 覆蓋率設定在 `[tool.coverage]`，本地 `pytest` 不強制跑，CI 用 `pytest --cov`

### 整合測試 Auth Fixture 規則

- 需要認證的 test 一律用 `http_client` / `admin_headers` / `non_admin_headers` fixture 參數
- 禁止在 test body 內自行建立 `AsyncClient` 並呼叫 login
- 例外：專門測試 login / auth 流程的 test（如 `test_dp_user_auth.py`）

---

## 前端測試（TypeScript / Vitest）

### 核心原則

**寫整合測試，不寫元件單元測試。**

React 官方與 Testing Library 作者的共同建議：
> 測試使用者能看到的行為，不測實作細節。

整合測試（頁面操作流程）的價值遠高於單元測試（元件渲染、CSS 值）。

### 技術棧

- **Vitest** — 測試執行器
- **Testing Library** — 從使用者角度操作 DOM（`screen.getByRole`、`userEvent`）
- **MSW（Mock Service Worker）** — 在網路層攔截 API，不 mock 模組

### MSW vs vi.mock 的差異

```
vi.mock("../../services/authService")
→ 在 JS 模組層攔截，axios / interceptor / 錯誤處理 完全繞過
→ 測試的是「有沒有呼叫這個函式」，不是使用者流程

MSW
→ 在網路層攔截，axios 真實發出 request，MSW 假扮 server 回應
→ axios interceptor、401 處理、response 解析 都會跑到
→ 測試的是「使用者操作後看到什麼」
```

**禁止在整合測試中使用 `vi.mock` 攔截 API service。** 應改用 MSW。

### MSW 設定

- `src/test/server.ts` — 定義所有模組的 API handlers（Mock API server）
- `src/test/setup.ts` — 自動啟動/重置/關閉 MSW server（不需手動匯入）；全域 `asyncUtilTimeout = 3000ms`（應對 CI 非同步延遲）
- 新增模組時，在 `server.ts` 對應區塊加入 handlers

**單一測試需要覆蓋預設 handler：**
```typescript
import { server } from '../../test/server'
import { http, HttpResponse } from 'msw'

it('伺服器錯誤時顯示錯誤訊息', async () => {
  server.use(
    http.post('/api/auth/login', () =>
      HttpResponse.json({ detail: '伺服器錯誤' }, { status: 500 })
    )
  )
  // ... 測試邏輯
})
// afterEach 會自動 resetHandlers，不影響其他測試
```

### MUI 共用元件測試方式

MUI 共用元件（AppHeader、Sidebar、Pagination、AppTable 等）需 MUI ThemeProvider（部分還需 Query / Notification / Router）。

**使用 `renderWithProviders`（推薦）：**
```tsx
import { renderWithProviders } from '../../test/renderWithProviders'
// 已包含 MUI ThemeProvider + TanStack Query + NotificationProvider + MemoryRouter
// （EDMS 無 war-mode，故無 WarModeProvider）
renderWithProviders(<SomeMuiComponent />)
```

**或手動包裝**（僅需 Theme 的元件）：
```tsx
import { ThemeProvider } from '@mui/material/styles'
import { muiTheme } from '../styles/muiTheme'

const renderComponent = () =>
  render(
    <ThemeProvider theme={muiTheme}>
      <MemoryRouter>
        <SomeComponent />
      </MemoryRouter>
    </ThemeProvider>
  )
```

**MUI 測試注意事項：**
- MUI `sx` prop 透過 CSS class 生效，不是 inline style。避免斷言 `element.style.xxx`
- MUI Pagination 頁碼按鈕的 aria-label 為 `"Go to page N"`
- MUI Select 使用 `aria-label` 查詢，非 `role="combobox"`

### 整合測試標準範本

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../../test/renderWithProviders'
import { SomePage } from './SomePage'

// ❌ 不要這樣做
// vi.mock('../../services/someService', () => ({ fetchData: vi.fn() }))

// ✅ MSW handler 已在 src/test/server.ts 定義，這裡不需要任何 mock

describe('SomePage 使用者操作流程', () => {
  it('成功送出表單後跳轉到下一頁', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SomePage />)

    // 用 getByRole / getByLabelText — 從使用者角度找元素
    await user.type(screen.getByLabelText('帳號'), 'admin')
    await user.click(screen.getByRole('button', { name: '送出' }))

    // 驗證使用者看到的結果，不驗證「呼叫了哪個函式」
    await waitFor(() => {
      expect(screen.getByText('下一頁')).toBeInTheDocument()
    })
  })

  it('輸入錯誤時顯示錯誤訊息', async () => {
    // 若需要覆蓋預設 handler，在此用 server.use()
  })
})
```

### 測試分類與放置位置

```
frontend/src/
├── {module}/
│   └── {Page}.test.tsx     ← 整合測試（使用者操作流程）✅ 高價值
├── hooks/
│   └── {hook}.test.ts      ← 可接受（複雜 hook 邏輯）
└── test/
    ├── server.ts            ← MSW handlers
    └── setup.ts             ← 全域設定
```

### 哪些測試沒有價值（不要寫）

| 類型 | 範例 | 原因 |
|------|------|------|
| CSS / 樣式值測試 | `expect(style.padding).toBe('16px')` | 改 UI 就 fail，不保護行為 |
| 常數結構測試 | `expect(QUERY_KEYS.donors.all).toEqual(['donors'])` | 在測資料不是行為 |
| 「有沒有呼叫函式」測試 | `expect(loginFn).toHaveBeenCalled()` | 實作細節，重構後無意義 |
| 元件能渲染測試 | `expect(container).toBeTruthy()` | 什麼都沒測到 |

### 執行指令

```bash
pnpm test             # 跑全部測試（CI 使用）
pnpm test:watch       # 開發中 watch 模式
pnpm test:coverage    # 含覆蓋率報告
```

---

## 測試失敗排除

1. 使用 **tdd-guide** agent
2. 檢查 MSW handler 是否有對應路徑
3. 確認 `onUnhandledRequest: 'warn'` 的警告訊息（代表缺少 handler）
4. 修復實作，不要修改測試（除非測試本身有誤）

### 前端「假紅」判定（#376）

⚠️ **動手 debug 之前先判定是不是假紅。** `pnpm test` 在開發機上可能紅一批
`Error: Test timed out in 5000ms.`，而那些檔案你一個都沒改——病因是 worker 互相搶資源
（`vite.config.ts` 的 `maxWorkers` 註解有完整背景），不是測試壞了。

依序判定，任一步得到「全過」即確認假紅：

| # | 檢查 | 判讀 |
|---|------|------|
| 1 | **回報檔數 vs `find src -name "*.test.ts*" \| wc -l`** | 數字不符 ⇒ 有測試**根本沒跑**（worker 起不來）。⚠️ 這比紅更危險，而且只看「幾條紅」永遠看不到 |
| 2 | **失敗檔案是否在本次變更的影響半徑內** | 見下方「影響半徑」 |
| 3 | **牆鐘絕對值** vs 同一批檔案在閒置機器上的基準 | 遠高於基準 ⇒ 機器忙。⛔ **不要算 `environment ÷ 牆鐘`**——`maxWorkers` 上限之後那個比值方向是反的 |
| 4 | **單獨跑那一檔** | 全過 ⇒ 假紅 |

#### 影響半徑：「不是我改的檔案」不等於免責

分成兩堆——「在影響半徑內」的每一個都要單獨跑，只有半徑外的才能當假紅打發：

| 形狀 | 例子 | 可追蹤性 |
|------|------|---------|
| import graph | 改共用模組的回傳值／簽章 → 所有 import 它的元件 | ✅ grep 得到 |
| ⚠️ **同一棵 DOM 樹** | 新增一個 UI 分區，讓別支測試的 `getByText("文件分類")` 找到兩筆 | ❌ 檔案樹與 import graph 上都連不起來 |

**要問的問句**：「我這次有沒有讓**任何新東西出現在同一棵 DOM 樹上**？」有 ⇒ 所有靠文字
定位的既有查詢都在半徑內。

#### ⚠️ 量測與 A/B 的前提：這台機器是多 session 共用的

- **量開跑前的負載不夠**，負載可能**跑到一半才進來**。要在過程中取樣
  （`ps -W | grep -c node.exe`），或兩側各跑兩次
- 單次 A/B 只能證明「這兩次跑起來不一樣」，**不能**證明「因為程式碼不一樣」
- `maxWorkers` 是**每個 vitest 行程**的上限，不是機器層級的——三個 session 各跑一次就是
  3 × 4 個並行 fork，又回到原點。此時的紅不代表設定失效
- ⭐ 先問**可否性**再問實測：「我改的東西有沒有任何路徑到得了這個檔案？」答案是
  「不可能」時（例如 diff 只有註解），實測紅就是環境問題，不要反過來懷疑邏輯

#### ⛔ 兩個不要

| 做法 | 為什麼不行 |
|------|-----------|
| 調高 `testTimeout` | **遮症狀**。測試不慢，是排不到 CPU；而且真正卡住的測試會更晚才失敗 |
| `isolate: false` | 狀態洩漏的症狀是「單獨跑綠、一起跑紅」——**與假紅一模一樣**，會讓上表的判定失去依據 |

## Agent 支援

- **tdd-guide** — 新功能時**主動使用**，強制先寫測試
- **e2e-runner** — Playwright E2E 測試專家
