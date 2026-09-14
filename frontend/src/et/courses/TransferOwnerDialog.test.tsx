import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { TransferOwnerDialog } from "./TransferOwnerDialog"
import { TRANSFER_REASON_MAX_LENGTH, type TeacherOption } from "./schemas"
import { renderWithProviders } from "../../test/renderWithProviders"

const TEACHERS: TeacherOption[] = [
  { user_id: "U2", user_name: "李教師" },
  { user_id: "U3", user_name: "張教師" },
]

function renderDialog(props: Partial<Parameters<typeof TransferOwnerDialog>[0]> = {}) {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  renderWithProviders(
    <TransferOwnerDialog
      open
      submitting={false}
      courseName="採血作業訓練"
      currentOwnerName="王教師"
      teachers={TEACHERS}
      error={null}
      onSubmit={onSubmit}
      onClose={onClose}
      {...props}
    />,
  )
  return { onSubmit, onClose }
}

/** 選一位接收教師（Autocomplete 需先開啟選單再點選項）。 */
async function pickTeacher(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(screen.getByRole("combobox", { name: /接收教師/ }))
  await user.click(await screen.findByRole("option", { name: new RegExp(label) }))
}

describe("ET02 轉讓擁有者視窗", () => {
  it("顯示課程與目前擁有者，讓管理者確認轉讓的是哪一門課", () => {
    renderDialog()
    expect(screen.getByText(/採血作業訓練/)).toBeInTheDocument()
    expect(screen.getByText(/王教師/)).toBeInTheDocument()
  })

  it("常駐警語說明原擁有者將僅可閱覽、會寫稽核、且可轉讓回去", () => {
    // 三件事都要說：前兩件是後果，第三件避免管理者因為「怕不可逆」而不敢用。
    renderDialog()
    const warning = screen.getByText(/原擁有者僅可閱覽/)
    expect(warning).toBeInTheDocument()
    expect(warning.textContent).toMatch(/稽核紀錄/)
    expect(warning.textContent).toMatch(/再次轉讓回去/)
  })

  it("未選教師也未填原因就送出 → 兩欄都標示，且不送出", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()

    await user.click(screen.getByRole("button", { name: "確認轉讓" }))

    expect(await screen.findByText("請選擇接收教師")).toBeInTheDocument()
    expect(screen.getByText("請填寫轉讓原因")).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("原因只有空白視同未填", async () => {
    // 與後端 `_reason_not_blank` 同一判定——`min_length` 擋不掉 "   "。
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()
    await pickTeacher(user, "李教師")
    await user.click(screen.getByRole("textbox", { name: /轉讓原因/ }))
    await user.paste("   ")

    await user.click(screen.getByRole("button", { name: "確認轉讓" }))

    expect(await screen.findByText("請填寫轉讓原因")).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("填妥後送出教師 ID 與去除前後空白的原因", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()
    await pickTeacher(user, "李教師")
    await user.click(screen.getByRole("textbox", { name: /轉讓原因/ }))
    await user.paste("  原教師離職  ")

    await user.click(screen.getByRole("button", { name: "確認轉讓" }))

    expect(onSubmit).toHaveBeenCalledWith("U2", "原教師離職")
  })

  it("原因輸入框的長度上限與後端同值", () => {
    // 🔴 契約測試。ET-7 才踩過同型的坑：前端輸入無上限、後端 `max_length=100`，
    // 使用者打到第 101 個字就 422。後端對應常數為 `TRANSFER_REASON_MAX_LEN`。
    renderDialog()
    expect(screen.getByRole("textbox", { name: /轉讓原因/ })).toHaveAttribute(
      "maxlength",
      String(TRANSFER_REASON_MAX_LENGTH),
    )
    expect(TRANSFER_REASON_MAX_LENGTH).toBe(500)
  })

  it("顯示後端回的錯誤訊息（選錯人）", () => {
    // `ET_OWNER_001` / `ET_OWNER_002` 由頁面就地轉成這個 prop——它們是「選錯人」，
    // 訊息要留在視窗裡讓管理者改選，不是飄一則 toast。
    renderDialog({ error: "接收者須具教師角色" })
    expect(screen.getByText("接收者須具教師角色")).toBeInTheDocument()
  })

  it("送出中停用送出鈕（防連點造出兩筆轉讓紀錄）", () => {
    renderDialog({ submitting: true })
    expect(screen.getByRole("button", { name: "確認轉讓" })).toBeDisabled()
  })

  it("沒有可接收的教師時給明確提示", async () => {
    // 全站只有一位教師、而他就是現任擁有者時會走到這裡（頁面已濾掉現任擁有者）。
    // 預設的 "No options" 是英文，且看不出「為什麼是空的」。
    const user = userEvent.setup()
    renderDialog({ teachers: [] })

    await user.click(screen.getByRole("combobox", { name: /接收教師/ }))

    expect(await screen.findByText("沒有可接收的教師")).toBeInTheDocument()
  })

  it("取消時清掉已填內容", async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog()
    await user.click(screen.getByRole("button", { name: "確認轉讓" }))
    expect(await screen.findByText("請選擇接收教師")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(onClose).toHaveBeenCalled()
  })
})
