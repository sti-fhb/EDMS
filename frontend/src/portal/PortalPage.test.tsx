import { ThemeProvider } from "@mui/material/styles"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { PortalPage } from "./PortalPage"
import { AuthContext } from "../auth/authContext"
import type { AuthState } from "../auth/authContext"
import { server } from "../test/server"
import { STORAGE_KEYS } from "../constants/storage"
import { muiTheme } from "../styles/muiTheme"

/** 建構測試用認證狀態；PortalPage 只讀 isAuthenticated，其餘欄位給合理預設。 */
function makeAuth(isAuthenticated: boolean): AuthState {
  return {
    token: isAuthenticated ? "test-token" : null,
    isAuthenticated,
    mustChangePwd: false,
    sessionExpired: false,
    login: async () => {},
    logout: async () => {},
  }
}

/**
 * 以指定認證狀態渲染 PortalPage。PortalPage 依 useAuth 的 isAuthenticated 決定是否
 * 發送 module-summary（#41），故測試需提供 AuthContext；預設為已登入，未登入情境傳 false。
 */
function renderPortal(ui: ReactNode, { isAuthenticated = true }: { isAuthenticated?: boolean } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={muiTheme}>
        <AuthContext.Provider value={makeAuth(isAuthenticated)}>{ui}</AuthContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe("PortalPage", () => {
  it("未登入 → 不發送 module-summary、顯示載入中、不呈現卡片或錯誤", async () => {
    // 以旗標偵測端點是否被呼叫：未登入時 query 應停用、不發送請求（#41）。
    let requested = false
    server.use(
      http.get("/api/dp/user/module-summary", () => {
        requested = true
        return HttpResponse.json({ et: { has_role: true }, dm: { has_role: false } })
      }),
    )
    renderPortal(<PortalPage />, { isAuthenticated: false })
    // query 停用時維持 pending → 顯示載入指示（實際畫面由 LoginOverlay 覆蓋）
    await waitFor(() => expect(screen.getByLabelText("載入中")).toBeInTheDocument())
    expect(requested).toBe(false)
    expect(screen.queryByText("教育訓練（ET）")).not.toBeInTheDocument()
    expect(screen.queryByText("無法載入模組資訊，請稍後再試")).not.toBeInTheDocument()
  })

  it("登入後（isAuthenticated 由 false 轉 true）→ 觸發查詢並正確渲染卡片", async () => {
    // 重現 #41 情境：PortalPage 於未登入時已掛載（被 LoginOverlay 覆蓋），登入時不重新
    // mount、僅 AuthContext 值變化。共用同一 QueryClient 以貼近真實（快取跨 rerender 保留）。
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const Wrapper = ({ isAuthenticated }: { isAuthenticated: boolean }) => (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={muiTheme}>
          <AuthContext.Provider value={makeAuth(isAuthenticated)}>
            <PortalPage />
          </AuthContext.Provider>
        </ThemeProvider>
      </QueryClientProvider>
    )
    const { rerender } = render(<Wrapper isAuthenticated={false} />)
    // 未登入：顯示載入中、尚無卡片
    expect(screen.getByLabelText("載入中")).toBeInTheDocument()
    expect(screen.queryByText("教育訓練（ET）")).not.toBeInTheDocument()
    // 登入 → enabled 由 false 轉 true，查詢觸發並渲染卡片
    rerender(<Wrapper isAuthenticated={true} />)
    expect(await screen.findByText("教育訓練（ET）")).toBeInTheDocument()
  })

  it("無 DM 角色 → DM 卡呈未開通、ET 卡可進入", async () => {
    renderPortal(<PortalPage />)
    expect(await screen.findByText("教育訓練（ET）")).toBeInTheDocument()
    expect(screen.getByText("🔒 未開通")).toBeInTheDocument()
  })

  it("具 DM 角色 → DM 卡可進入（無未開通標記）", async () => {
    server.use(
      http.get("/api/dp/user/module-summary", () =>
        HttpResponse.json({ et: { has_role: true }, dm: { has_role: true } }),
      ),
    )
    renderPortal(<PortalPage />)
    expect(await screen.findByText("文件管理（DM）")).toBeInTheDocument()
    expect(screen.queryByText("🔒 未開通")).not.toBeInTheDocument()
    // ET + DM 兩張卡皆可進入
    expect(screen.getAllByRole("link", { name: "進入" })).toHaveLength(2)
  })

  it("首次登入顯示歡迎橫幅", async () => {
    renderPortal(<PortalPage />)
    expect(await screen.findByText("歡迎使用 EDMS 教育訓練文件管理系統")).toBeInTheDocument()
  })

  it("關閉歡迎橫幅後寫入旗標、不再顯示", async () => {
    const user = userEvent.setup()
    renderPortal(<PortalPage />)
    await screen.findByText("歡迎使用 EDMS 教育訓練文件管理系統")
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(localStorage.getItem(STORAGE_KEYS.WELCOME_DISMISSED)).toBe("1")
    expect(screen.queryByText("歡迎使用 EDMS 教育訓練文件管理系統")).not.toBeInTheDocument()
  })

  it("已顯示過（旗標存在）→ 不顯示歡迎橫幅", async () => {
    localStorage.setItem(STORAGE_KEYS.WELCOME_DISMISSED, "1")
    renderPortal(<PortalPage />)
    // 等入口頁載入完成（ET 卡出現）後，確認橫幅不在
    expect(await screen.findByText("教育訓練（ET）")).toBeInTheDocument()
    expect(screen.queryByText("歡迎使用 EDMS 教育訓練文件管理系統")).not.toBeInTheDocument()
  })
})
