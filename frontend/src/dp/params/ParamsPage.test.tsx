import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { UserEvent } from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ParamsPage } from "./ParamsPage"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 點某列（依列內文字定位）右側的「編輯」展開編輯面板。 */
async function openEditByRow(user: UserEvent, rowText: string) {
  const rowEl = screen.getByText(rowText).closest("tr")
  if (!rowEl) throw new Error(`找不到含「${rowText}」的列`)
  await user.click(within(rowEl).getByRole("button", { name: "編輯" }))
}

/**
 * 有狀態的平台 VALUE 參數 handler：PUT 寫入的 description 會反映到後續 GET，
 * 供驗證「儲存後表格說明欄即時更新」。回傳收到的 PUT bodies 供斷言。
 */
function useStatefulValueParam() {
  const bodies: Record<string, unknown>[] = []
  let description: string | null = null

  server.use(
    http.get("/api/dp/params", () =>
      HttpResponse.json([
        {
          param_id: "JWT",
          param_name: "JWT 設定",
          param_type: "VALUE",
          detail_lock: false,
          description: "JWT 存取與換發相關參數",
          scope: "platform",
          details: [
            {
              param_key: "ACCESS_TTL_MIN",
              param_name: "閒置自動登出（分鐘）",
              param_value: "15",
              description,
              sort_order: null,
              is_enabled: true,
            },
          ],
        },
      ]),
    ),
    http.put("/api/dp/params/:id/details/:key", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      bodies.push(body)
      description = (body.description as string | null) ?? null
      return HttpResponse.json({
        param_key: "ACCESS_TTL_MIN",
        param_name: "閒置自動登出（分鐘）",
        param_value: body.param_value ?? "15",
        description,
        sort_order: null,
        is_enabled: true,
      })
    }),
  )
  return bodies
}

describe("ParamsPage 系統參數維護流程", () => {
  it("載入後平台頁籤條列 VALUE 參數與影響全平台警告，並有 DM 頁籤", async () => {
    renderWithProviders(<ParamsPage />)

    // 條列：VALUE 明細各一列（顯示中文名 + 目前值）
    expect(await screen.findByText("閒置自動登出（分鐘）")).toBeInTheDocument()
    expect(screen.getByText("15")).toBeInTheDocument()
    expect(screen.getByText(/變更將影響全平台/)).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "平台（共用）" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "文件管理（DM）" })).toBeInTheDocument()
  })

  it("編輯平台參數值 → 先出現影響全平台確認 → 確認後提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.type(field, "10")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 平台級警告確認對話框（PARAMS-005）
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText(/影響全平台/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "確定儲存" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })

  it("取消平台級警告 → 欄位還原為原值、不儲存", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.type(field, "9")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "取消" }))

    // 還原為原值 15（不因取消而殘留未儲存的 9）
    expect(await screen.findByLabelText("閒置自動登出（分鐘）")).toHaveValue("15")
  })

  it("清空欄位儲存 → 提示請輸入內容、不跳確認", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const field = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(field)
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("請輸入內容")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    // 空值不留白，還原為原值 15
    expect(screen.getByLabelText("閒置自動登出（分鐘）")).toHaveValue("15")
  })

  it("編輯中切換到另一列 → 欄位顯示新列原值（不殘留舊輸入）", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    // 開第一列、輸入未儲存的值
    await openEditByRow(user, "閒置自動登出（分鐘）")
    const first = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(first)
    await user.type(first, "999")

    // 直接切到另一列（同為 platform VALUE）：面板應以新列原值重掛，不殘留 999
    await openEditByRow(user, "單次登入時效上限（小時）")
    expect(await screen.findByLabelText("單次登入時效上限（小時）")).toHaveValue("8")
  })

  it("DM 鎖定清單：編輯展開後代碼唯讀、無新增入口", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "文件管理（DM）" }))
    await openEditByRow(user, "文件分類")

    expect(await screen.findByText("SOP")).toBeInTheDocument()
    expect(screen.getByText("代碼鎖定")).toBeInTheDocument()
    // 鎖定清單不提供新增入口
    expect(screen.queryByRole("button", { name: "新增" })).not.toBeInTheDocument()
  })

  it("VALUE 型可同時改值與說明（單次 PUT、單次確認），儲存後表格說明欄即時更新", async () => {
    const bodies = useStatefulValueParam()
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    const value = await screen.findByLabelText("閒置自動登出（分鐘）")
    await user.clear(value)
    await user.type(value, "10")
    await user.type(screen.getByLabelText("說明"), "閒置逾時自動登出")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    // 平台級確認只跳一次（值與說明合併為同一次 PUT）
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "確定儲存" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ param_value: "10", description: "閒置逾時自動登出" })
    expect(await screen.findByText("閒置逾時自動登出")).toBeInTheDocument()
    // 儲存成功後編輯面板收起（對齊通知範本）
    await waitFor(() => expect(screen.queryByLabelText("說明")).not.toBeInTheDocument())
  })

  it("VALUE 型：驗證失敗 / 取消確認時面板不收起", async () => {
    useStatefulValueParam()
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    // 值清空 → 驗證失敗，面板保留
    await openEditByRow(user, "閒置自動登出（分鐘）")
    await user.clear(await screen.findByLabelText("閒置自動登出（分鐘）"))
    await user.click(screen.getByRole("button", { name: "儲存" }))
    expect(await screen.findByText("請輸入內容")).toBeInTheDocument()
    expect(screen.getByLabelText("說明")).toBeInTheDocument()

    // 平台級確認按取消 → 面板保留
    await user.click(screen.getByRole("button", { name: "儲存" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "取消" }))
    expect(screen.getByLabelText("說明")).toBeInTheDocument()
  })

  it("清空說明 → 送出 null，表格說明欄回顯 —", async () => {
    const bodies = useStatefulValueParam()
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    await user.type(await screen.findByLabelText("說明"), "先填再清")
    await user.clear(screen.getByLabelText("說明"))
    await user.click(screen.getByRole("button", { name: "儲存" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "確定儲存" }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ param_value: "15", description: null })
  })

  it("說明超過 500 字元 → 前端擋下並提示，不送出", async () => {
    const bodies = useStatefulValueParam()
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await openEditByRow(user, "閒置自動登出（分鐘）")
    fireEvent.change(await screen.findByLabelText("說明"), { target: { value: "x".repeat(501) } })
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("說明長度不可超過 500 字元")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it("LIST 型清單項可改說明（與名稱合併為單次 PUT）", async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.put("/api/dp/params/:id/details/:key", async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({
          param_key: "NURSE",
          param_name: "護理師",
          param_value: null,
          description: "臨床護理人員",
          sort_order: 1,
          is_enabled: true,
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await openEditByRow(user, "受訓單位標籤")

    await user.type(await screen.findByLabelText("NURSE 說明"), "臨床護理人員")
    await user.click(screen.getByRole("button", { name: "儲存" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
    expect(bodies[0]).toEqual({ param_name: "護理師", description: "臨床護理人員" })
    // LIST 型一個面板管多筆、逐項儲存，存完不收起
    expect(screen.getByLabelText("NURSE 說明")).toBeInTheDocument()
  })

  it("LIST 型清空說明 → 送出 null（與 VALUE 型語意一致）", async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.put("/api/dp/params/:id/details/:key", async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({
          param_key: "NURSE",
          param_name: "護理師",
          param_value: null,
          description: null,
          sort_order: 1,
          is_enabled: true,
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await openEditByRow(user, "受訓單位標籤")

    // 種子說明為 null，先填再清，驗證清空送 null 而非空字串
    const desc = await screen.findByLabelText("NURSE 說明")
    await user.type(desc, "暫填")
    await user.clear(desc)
    await user.click(screen.getByRole("button", { name: "儲存" }))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ param_name: "護理師", description: null })
  })

  it("模組清單編輯展開後新增項目 → 提示已即時生效", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await openEditByRow(user, "受訓單位標籤")

    await user.type(screen.getByLabelText("新增代碼"), "DOCTOR")
    await user.type(screen.getByLabelText("新增名稱"), "醫師")
    await user.click(screen.getByRole("button", { name: "新增" }))

    expect(await screen.findByText("已儲存並即時生效")).toBeInTheDocument()
  })

  it("新增清單項可一併填說明，POST 帶 description；留白則不帶此欄", async () => {
    const bodies: Record<string, unknown>[] = []
    server.use(
      http.post("/api/dp/params/:id/details", async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(
          {
            param_key: "DOCTOR",
            param_name: "醫師",
            param_value: null,
            description: null,
            sort_order: null,
            is_enabled: true,
          },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<ParamsPage />)
    await screen.findByText("閒置自動登出（分鐘）")

    await user.click(screen.getByRole("tab", { name: "教育訓練（ET）" }))
    await openEditByRow(user, "受訓單位標籤")

    await user.type(screen.getByLabelText("新增代碼"), "DOCTOR")
    await user.type(screen.getByLabelText("新增名稱"), "醫師")
    await user.type(screen.getByLabelText("新增說明"), "臨床醫師")
    await user.click(screen.getByRole("button", { name: "新增" }))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ param_key: "DOCTOR", param_name: "醫師", description: "臨床醫師" })

    // 說明留白 → 不帶 description 欄（POST 省略即為 NULL）
    await user.type(screen.getByLabelText("新增代碼"), "TECH")
    await user.type(screen.getByLabelText("新增名稱"), "醫檢師")
    await user.click(screen.getByRole("button", { name: "新增" }))
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toEqual({ param_key: "TECH", param_name: "醫檢師" })
  })
})
