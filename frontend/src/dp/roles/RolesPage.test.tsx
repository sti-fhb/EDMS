import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { RolesPage } from "./RolesPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

describe("RolesPage 權限管理", () => {
  it("顯示可管理模組頁籤（DM）+ 使用者列與 DM 角色核取（現況勾選）", async () => {
    renderWithProviders(<RolesPage />)
    expect(await screen.findByText("文件管理（DM）")).toBeInTheDocument()
    expect(await screen.findByText("王曉明")).toBeInTheDocument()
    // DM 四角色欄；u1 現況為編輯者 → 編輯者勾選、管理者未勾選
    expect(screen.getByRole("checkbox", { name: "王曉明 編輯者" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "王曉明 管理者" })).not.toBeChecked()
  })

  it("勾選角色 → 呼叫指派並顯示即時生效提示", async () => {
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const adminBox = await screen.findByRole("checkbox", { name: "王曉明 管理者" })
    await user.click(adminBox)
    expect(await screen.findByText("角色 / 標籤已更新並即時生效")).toBeInTheDocument()
  })

  it("自我保護：模組回 403 → 顯示錯誤訊息", async () => {
    server.use(
      http.put("/api/dp/roles/:module/assignments/:userId", () =>
        HttpResponse.json({ error_code: "DP_ROLE_002", error_message: "無法取消自己的管理者角色" }, { status: 403 }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const box = await screen.findByRole("checkbox", { name: "王曉明 編輯者" })
    await user.click(box)
    expect(await screen.findByText("無法取消自己的管理者角色")).toBeInTheDocument()
  })

  it("無可管理模組 → 顯示提示、不顯示頁籤", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json([])))
    renderWithProviders(<RolesPage />)
    expect(await screen.findByText("您目前無可管理的模組權限。")).toBeInTheDocument()
    expect(screen.queryByText("文件管理（DM）")).not.toBeInTheDocument()
  })

  it("頁籤依前端定義排序：ET 左、DM 右，且預設選中 ET（後端回序不影響）", async () => {
    // 後端回的是 registry 註冊順序（DM 先註冊），畫面順序不應跟著它跑
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json(["DM", "ET"])))
    renderWithProviders(<RolesPage />)
    await screen.findByText("教育訓練（ET）")
    const tabs = screen.getAllByRole("tab")
    expect(tabs.map((t) => t.textContent)).toEqual(["教育訓練（ET）", "文件管理（DM）"])
    // 預設選中第一個＝排序後的 ET（active 由排序後的陣列衍生）
    expect(tabs[0]).toHaveAttribute("aria-selected", "true")
  })

  it("未列於顯示順序的模組代碼仍渲染，排在已知模組之後", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json(["XX", "DM", "ET"])))
    renderWithProviders(<RolesPage />)
    await screen.findByText("教育訓練（ET）")
    const tabs = screen.getAllByRole("tab")
    expect(tabs.map((t) => t.textContent)).toEqual(["教育訓練（ET）", "文件管理（DM）", "XX"])
  })

  it("帳號欄顯示 email、最後異動顯示操作者姓名（非原始 ID）", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.getByText("ming@example.com")).toBeInTheDocument() // 帳號欄＝email
    expect(screen.getByText(/系統管理員/)).toBeInTheDocument() // 最後異動＝姓名（非 "admin"）
    expect(screen.queryByText(/^admin｜/)).not.toBeInTheDocument()
  })

  it("停用帳號：列標示「已停用」、整列不可操作（#250 AC1）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("林離職")).closest("tr")!
    expect(within(row).getByText("已停用")).toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "林離職 編輯者" })).toBeDisabled()
    expect(within(row).getByRole("checkbox", { name: "林離職 管理者" })).toBeDisabled()
    expect(within(row).getByRole("button", { name: "編輯" })).toBeDisabled()
  })

  it("鎖定中帳號：列標示「已鎖定」、整列不可操作（#250 AC2）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("陳鎖定")).closest("tr")!
    expect(within(row).getByText("已鎖定")).toBeInTheDocument()
    expect(within(row).getByRole("button", { name: "編輯" })).toBeDisabled()
  })

  it("停用 / 鎖定帳號連「已持有」的角色也不可撤除（整列唯讀，SA 裁示）", async () => {
    renderWithProviders(<RolesPage />)
    // u3 陳鎖定持有閱覽者——即使是撤除方向也不可操作，降權須先啟用帳號
    const row = (await screen.findByText("陳鎖定")).closest("tr")!
    const held = within(row).getByRole("checkbox", { name: "陳鎖定 閱覽者" })
    expect(held).toBeChecked()
    expect(held).toBeDisabled()
  })

  it("正常帳號不受影響：無狀態標籤、可操作（#250 迴歸）", async () => {
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("王曉明")).closest("tr")!
    expect(within(row).queryByText("已停用")).not.toBeInTheDocument()
    expect(within(row).queryByText("已鎖定")).not.toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "王曉明 編輯者" })).toBeEnabled()
    expect(within(row).getByRole("button", { name: "編輯" })).toBeEnabled()
  })

  it("鎖定已逾時的帳號視為正常（不可誤以 locked_until 非空判定）", async () => {
    server.use(
      http.get("/api/dp/roles/:module/assignments", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "u9",
              user_name: "已解鎖",
              email: "unlocked@example.com",
              status: "ACTIVE",
              locked_until: "2020-01-01T00:00:00Z", // 早已逾時 → 自動解鎖
              roles: [],
              groups: [],
              last_modified_by: null,
              last_modified_by_name: null,
              last_modified_date: null,
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("已解鎖")).closest("tr")!
    expect(within(row).queryByText("已鎖定")).not.toBeInTheDocument()
    expect(within(row).getByRole("checkbox", { name: "已解鎖 編輯者" })).toBeEnabled()
  })

  it("群組欄位標題依模組切換：DM 為「可見對象」", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.getByRole("columnheader", { name: "可見對象" })).toBeInTheDocument()
  })

  it("ET 分頁之群組欄位標題為「受訓單位標籤」，不沿用 DM 的用詞", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])))
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    // 正反各一條、同一種查詢方式：只斷言「不該出現」時，改掉用詞之外的任何事都驗不到
    expect(screen.getByRole("columnheader", { name: "受訓單位標籤" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "可見對象" })).not.toBeInTheDocument()
  })

  it("未知模組之群組欄位標題回退為模組代碼（與頁籤同慣例），不顯示內部通稱", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json(["XX"])))
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    // 顯示代碼而非「群組」：漏掛對照時要一眼看得出來，而不是長得像正常欄位名
    expect(screen.getByRole("columnheader", { name: "XX" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "群組" })).not.toBeInTheDocument()
  })

  it("ET 之群組編輯視窗標題為「編輯受訓單位標籤」", async () => {
    server.use(
      http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])),
      // ET 的受訓單位標籤是平的一層（無 UNIT 類），不進配對模式
      http.get("/api/dp/roles/:module/group-options", () =>
        HttpResponse.json([
          { code: "5", name: "護理師", kind: "AUDIENCE" },
          { code: "6", name: "行政人員", kind: "AUDIENCE" },
        ]),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("王曉明")).closest("tr")!
    await user.click(within(row).getByRole("button", { name: "編輯" }))
    expect(await screen.findByText("編輯受訓單位標籤")).toBeInTheDocument()
    expect(screen.queryByText("編輯可見對象")).not.toBeInTheDocument()
  })

  it("無新增角色入口（角色為固定 enum）", async () => {
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    expect(screen.queryByRole("button", { name: /新增角色/ })).not.toBeInTheDocument()
  })
})

describe("RolesPage 最後異動日期（#539）", () => {
  it("以台灣時間呈現：UTC 前一天 17:30 顯示為台灣隔日", async () => {
    server.use(
      http.get("/api/dp/roles/:module/assignments", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "u1",
              user_name: "王曉明",
              email: "ming@example.com",
              status: "ACTIVE",
              locked_until: null,
              roles: ["DM_EDITOR"],
              groups: [],
              last_modified_by: "admin",
              last_modified_by_name: "系統管理員",
              last_modified_date: "2026-10-05T17:30:00Z",
            },
          ],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
        }),
      ),
    )
    renderWithProviders(<RolesPage />)
    expect(await screen.findByText("系統管理員｜2026-10-06")).toBeInTheDocument()
    expect(screen.queryByText("系統管理員｜2026-10-05")).not.toBeInTheDocument()
  })
})
