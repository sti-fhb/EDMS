import { act, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"

import { AppHeader } from "./AppHeader"
import { AuthContext } from "../auth/authContext"
import type { AuthState } from "../auth/authContext"
import { renderWithProviders } from "../test/renderWithProviders"
import { server } from "../test/server"

const authStub: AuthState = {
  token: "t",
  isAuthenticated: true,
  mustChangePwd: false,
  sessionExpired: false,
  login: async () => {},
  logout: async () => {},
  clearMustChangePwd: () => {},
}

const ME_PATH = "/api/dp/user/me"

/** 本檔註冊過的 MSW listener，afterEach 一律移除，避免跨測試累積。 */
const listeners: (() => void)[] = []

afterEach(() => {
  listeners.splice(0).forEach((off) => off())
})

/**
 * 蒐集本次測試期間實際送出的請求路徑。
 *
 * ⚠️ 守衛類測試**必須斷言「有沒有送出請求」而非「畫面上有沒有姓名」**：
 * `findByRole("button", { name: "登出" })` 在登出鈕同步渲染的當下就 resolve，而 MSW 回應要再過
 * 幾個 tick 才到——以 `queryByText("測試員")` 做負向斷言者，在 `enabled` 守衛被拿掉後**仍然全綠**
 * （Security Review 以變異檢查實測確認）。那是一組看起來有守、實際上守不住的假證據。
 */
function trackRequestPaths(): string[] {
  const paths: string[] = []
  const handler = ({ request }: { request: Request }) => {
    paths.push(new URL(request.url).pathname)
  }
  server.events.on("request:start", handler)
  listeners.push(() => server.events.removeListener("request:start", handler))
  return paths
}

/** 讓已排入的請求有機會真的送出（負向斷言前必須等，否則等於什麼都沒驗）。 */
async function flushRequests(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })
}

/** 頂列需讀 /me 取姓名，故一律經 renderWithProviders（含 QueryClient）。 */
function renderHeader(overrides: Partial<AuthState> = {}, initialEntry = "/profile") {
  return renderWithProviders(
    <AuthContext.Provider value={{ ...authStub, ...overrides }}>
      <Routes>
        <Route path="/profile" element={<AppHeader />} />
        <Route path="/" element={<div>主頁</div>} />
      </Routes>
    </AuthContext.Provider>,
    undefined,
    [initialEntry],
  )
}

describe("AppHeader 使用者區（#421 對齊主專案）", () => {
  it("顯示登入者姓名", async () => {
    renderHeader()
    expect(await screen.findByText("測試員")).toBeInTheDocument()
  })

  it("點姓名導向 /profile（個人資料維護）", async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <AuthContext.Provider value={authStub}>
        <Routes>
          <Route path="/" element={<AppHeader />} />
          <Route path="/profile" element={<div>個人資料頁</div>} />
        </Routes>
      </AuthContext.Provider>,
      undefined,
      ["/"],
    )
    await user.click(await screen.findByRole("button", { name: /測試員/ }))
    expect(await screen.findByText("個人資料頁")).toBeInTheDocument()
  })

  it("登出鈕為獨立按鈕（非下拉選單），點擊後導回主頁", async () => {
    const user = userEvent.setup()
    renderHeader()
    // 對齊 TBMS：姓名與登出並排，不再收在 AccountCircle 下拉選單裡
    expect(screen.queryByRole("button", { name: "個資選單" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "登出" }))
    expect(await screen.findByText("主頁")).toBeInTheDocument()
  })

  it("須強制變更密碼時不送出 /me（守衛的現役分支）", async () => {
    // `RootLayout` 之強制變更密碼頁殼與 `Outlet` 同時掛載，故未完成變更時本元件仍在頁殼背後渲染。
    const paths = trackRequestPaths()
    renderHeader({ mustChangePwd: true })
    await screen.findByRole("button", { name: "登出" })
    await flushRequests()
    expect(paths).not.toContain(ME_PATH)
  })

  it("未登入時不送出 /me（守衛的防禦性分支）", async () => {
    // 現行 `RootLayout` 未登入時直接回 `<LoginOverlay />`、不渲染 `Outlet`，故此路徑實際不會
    // 觸發。保留斷言是為了：掛載時機若再改回「先渲染再以 overlay 覆蓋」，這條會先紅。
    const paths = trackRequestPaths()
    renderHeader({ isAuthenticated: false })
    await screen.findByRole("button", { name: "登出" })
    await flushRequests()
    expect(paths).not.toContain(ME_PATH)
  })

  it("守衛放行時確實會送出 /me（證明上兩條的負向斷言抓得到東西）", async () => {
    // 沒有這條，上面兩條無法區分「守衛有效」與「測試根本等不到請求」——
    // 實測過：舊版以 `queryByText` 斷言姓名不顯示者，在守衛被拿掉後仍全綠。
    const paths = trackRequestPaths()
    renderHeader()
    await screen.findByText("測試員")
    expect(paths).toContain(ME_PATH)
  })

  it("標題不含 EDMS 字樣，且點擊導回主頁", async () => {
    const user = userEvent.setup()
    renderHeader()
    const title = screen.getByRole("button", { name: "回主頁" })
    expect(title.textContent).not.toContain("EDMS")
    await user.click(title)
    expect(await screen.findByText("主頁")).toBeInTheDocument()
  })
})
