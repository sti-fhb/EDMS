import { screen, waitFor, within } from "@testing-library/react"
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

  it("ET 分頁之群組欄位標題為「受訓對象」，不沿用 DM 的用詞（#538 改名）", async () => {
    server.use(http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])))
    renderWithProviders(<RolesPage />)
    await screen.findByText("王曉明")
    // 正反各一條、同一種查詢方式：只斷言「不該出現」時，改掉用詞之外的任何事都驗不到
    expect(screen.getByRole("columnheader", { name: "受訓對象" })).toBeInTheDocument()
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

  it("DM 之配對編輯視窗說明句講的是文件（與下一條 ET 成對）", async () => {
    // 預設 handler 為 DM、選項含 UNIT → 配對模式。少了這條，下一條的「不出現『此人可見的
    // 文件』」在 DM 那句被改掉時會恆真（#538 才把這句從寫死改成依模組）
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("王曉明")).closest("tr")!
    await user.click(within(row).getByRole("button", { name: "編輯" }))
    expect(await screen.findByText(/此人可見的文件/)).toBeInTheDocument()
    expect(screen.queryByText(/此人會被帶入的課程/)).not.toBeInTheDocument()
  })

  it("ET 列表以「單位 + 職位」顯示配對，單位未指定者標示出來（#538 AC 13）", async () => {
    // 空白無從區分「尚未設定單位」與「不限單位」，而前者會讓該學員安靜地漏掉所有指定單位的課程
    server.use(
      http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])),
      http.get("/api/dp/roles/:module/group-options", () =>
        HttpResponse.json([
          { code: "102", name: "國防醫學院三軍總醫院", kind: "UNIT" },
          { code: "5", name: "護理師", kind: "AUDIENCE" },
        ]),
      ),
      http.get("/api/dp/roles/:module/assignments", () =>
        HttpResponse.json({
          data: [
            {
              user_id: "u1",
              user_name: "王曉明",
              email: "ming@example.com",
              status: "ACTIVE",
              locked_until: null,
              roles: ["ET_STUDENT"],
              groups: ["102:5", ":5"],
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
    expect(await screen.findByText("國防醫學院三軍總醫院 + 護理師")).toBeInTheDocument()
    expect(screen.getByText("（單位未指定）+ 護理師")).toBeInTheDocument()
  })

  it("ET 之群組編輯視窗為配對模式，說明句講的是課程而非文件（#538）", async () => {
    server.use(
      http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])),
      // #538 起 ET 也回單位（kind=UNIT）與職位兩類 → 自動進配對模式，DP 不寫死模組
      http.get("/api/dp/roles/:module/group-options", () =>
        HttpResponse.json([
          { code: "102", name: "國防醫學院三軍總醫院", kind: "UNIT" },
          { code: "5", name: "護理師", kind: "AUDIENCE" },
          { code: "6", name: "行政人員", kind: "AUDIENCE" },
        ]),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<RolesPage />)
    const row = (await screen.findByText("王曉明")).closest("tr")!
    await user.click(within(row).getByRole("button", { name: "編輯" }))
    expect(await screen.findByText("編輯受訓對象")).toBeInTheDocument()
    expect(screen.queryByText("編輯可見對象")).not.toBeInTheDocument()
    // 說明句依模組：ET 講「帶入的課程」。正反同一種查法——只寫反向的話文案一改就恆真
    expect(screen.queryByText(/此人會被帶入的課程/)).toBeInTheDocument()
    expect(screen.queryByText(/此人可見的文件/)).not.toBeInTheDocument()
  })

  describe("配對視窗：沒選完的新列擋下儲存（手測回饋）", () => {
    function setupEt() {
      const captured: { body?: { roles: string[]; groups: string[] } } = {}
      server.use(
        http.get("/api/dp/roles/modules", () => HttpResponse.json(["ET"])),
        http.get("/api/dp/roles/:module/group-options", () =>
          HttpResponse.json([
            { code: "102", name: "國防醫學院三軍總醫院", kind: "UNIT" },
            { code: "5", name: "護理師", kind: "AUDIENCE" },
          ]),
        ),
        http.get("/api/dp/roles/:module/assignments", () =>
          HttpResponse.json({
            data: [
              {
                user_id: "u1",
                user_name: "王曉明",
                email: "ming@example.com",
                status: "ACTIVE",
                locked_until: null,
                roles: ["ET_STUDENT"],
                groups: [":5"], // 改版前留下的「單位未指定」——不可被擋、不可被丟
                last_modified_by: null,
                last_modified_by_name: null,
                last_modified_date: null,
              },
            ],
            meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
          }),
        ),
        http.put("/api/dp/roles/:module/assignments/:userId", async ({ request }) => {
          captured.body = (await request.json()) as NonNullable<typeof captured.body>
          return new HttpResponse(null, { status: 204 })
        }),
      )
      return captured
    }

    /** 依序為第 1 組單位、第 1 組職位、第 2 組單位、第 2 組職位（Select 的名稱取自標籤，各列同名）。 */
    const combos = (dialog: HTMLElement) => within(dialog).getAllByRole("combobox")

    async function openDialog(user: ReturnType<typeof userEvent.setup>) {
      renderWithProviders(<RolesPage />)
      const row = (await screen.findByText("王曉明")).closest("tr")!
      await user.click(within(row).getByRole("button", { name: "編輯" }))
      return screen.findByRole("dialog")
    }

    it("只選單位就儲存 → 不送出、職位欄標紅、出現提示；刪掉該列後可存且既有列保留", async () => {
      const user = userEvent.setup()
      const captured = setupEt()
      const dialog = await openDialog(user)
      // 尚未儲存前不標紅、不出現提示——還沒做錯就不責備
      expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument()

      await user.click(within(dialog).getByRole("button", { name: "新增受訓對象" }))
      await user.click(combos(dialog)[2])
      await user.click(await screen.findByRole("option", { name: "國防醫學院三軍總醫院" }))
      await user.click(within(dialog).getByRole("button", { name: "儲存" }))

      expect(await within(dialog).findByRole("alert")).toHaveTextContent("有未選完的列")
      expect(captured.body).toBeUndefined()
      // 紅框落在沒選的那一欄；已選的單位欄、既有的「單位未指定」列都不標
      expect(combos(dialog)[3]).toHaveAttribute("aria-invalid", "true")
      expect(combos(dialog)[2]).not.toHaveAttribute("aria-invalid", "true")
      expect(combos(dialog)[0]).not.toHaveAttribute("aria-invalid", "true")

      await user.click(within(dialog).getByRole("button", { name: "移除第 2 組" }))
      await user.click(within(dialog).getByRole("button", { name: "儲存" }))

      await waitFor(() => expect(captured.body).toBeDefined())
      expect(captured.body?.groups).toEqual([":5"])
    })

    it("新增後兩欄皆空也擋下", async () => {
      const user = userEvent.setup()
      const captured = setupEt()
      const dialog = await openDialog(user)
      await user.click(within(dialog).getByRole("button", { name: "新增受訓對象" }))
      await user.click(within(dialog).getByRole("button", { name: "儲存" }))

      expect(await within(dialog).findByRole("alert")).toBeInTheDocument()
      expect(combos(dialog)[2]).toHaveAttribute("aria-invalid", "true")
      expect(combos(dialog)[3]).toHaveAttribute("aria-invalid", "true")
      expect(captured.body).toBeUndefined()
    })
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
