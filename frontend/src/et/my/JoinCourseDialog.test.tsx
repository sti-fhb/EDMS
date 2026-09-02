import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { JoinCourseDialog } from "./JoinCourseDialog"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const noop = () => {}

function renderDialog(overrides: Partial<Parameters<typeof JoinCourseDialog>[0]> = {}) {
  const props = { open: true, onClose: noop, onJoined: noop, onAlreadyJoined: noop, ...overrides }
  return renderWithProviders(<JoinCourseDialog {...props} />)
}

function codeInput() {
  return screen.getByLabelText(/邀請碼/)
}

describe("ET04 加入新課程視窗", () => {
  it("查詢鈕在未滿 8 碼前為停用（AC 5）", async () => {
    const user = userEvent.setup()
    renderDialog()

    const query = screen.getByRole("button", { name: "查詢" })
    expect(query).toBeDisabled()

    await user.type(codeInput(), "1234567")
    expect(query).toBeDisabled()

    await user.type(codeInput(), "8")
    expect(query).toBeEnabled()
  })

  it("輸入框只接受數字並截斷至 8 碼", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "12ab34cd5678999")

    // 非數字被濾掉、超過 8 碼被截斷——在輸入端擋掉，而不是等送出才報錯。
    expect(codeInput()).toHaveValue("12345678")
  })

  it("整串貼上時濾非數字的結果與逐字輸入一致", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(codeInput())
    await user.paste("12ab34cd5678999")

    // ⚠️ 這條與上一條**不是重複的**：逐字輸入時受控值永遠不超過 8，碰不到
    // `maxLength`；整串貼上會先被 HTML 層截成 8 個「字元」（"12ab34cd"），濾完只剩
    // "1234"。實測回報的正是這個——上一條測試看不出來。
    expect(codeInput()).toHaveValue("12345678")
  })

  it("查詢通過後顯示課程資訊供確認（AC 6）", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.getByText(/王教師/)).toBeInTheDocument()
    expect(screen.getByText(/章節數：5/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "確認加入" })).toBeInTheDocument()
  })

  it("確認加入後回報課程並關閉（AC 7）", async () => {
    const user = userEvent.setup()
    const onJoined = vi.fn()
    renderDialog({ onJoined })

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))
    await user.click(await screen.findByRole("button", { name: "確認加入" }))

    await waitFor(() => expect(onJoined).toHaveBeenCalledWith(1, false))
  })

  it("邀請碼無效時於視窗內顯示錯誤（AC 8）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({ error_code: "ET_ENROLL_001", error_message: "邀請碼無效，請確認後重試" }, { status: 404 }),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "99999999")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // inline Alert 而非 Snackbar——錯誤要與輸入框並存才看得出是哪一次輸入錯了。
    expect(await screen.findByText("邀請碼無效，請確認後重試")).toBeInTheDocument()
  })

  it("課程關閉中時顯示對應訊息（AC 9）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({ error_code: "ET_ENROLL_002", error_message: "此課程目前關閉中" }, { status: 409 }),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText("此課程目前關閉中")).toBeInTheDocument()
  })

  it("已被移除者顯示請聯繫教師（SA Q1 裁示 C）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json(
          { error_code: "ET_ENROLL_003", error_message: "您已被移除出此課程，如需重新加入請聯繫教師" },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    expect(await screen.findByText(/請聯繫教師/)).toBeInTheDocument()
  })

  it("已加入之課程不進預覽、直接導向（AC 10）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({
          course_id: 7,
          course_name: "已加入的課",
          owner_name: "王教師",
          chapter_count: 3,
          already_joined: true,
          open_start_at: null,
        }),
      ),
    )
    const user = userEvent.setup()
    const onAlreadyJoined = vi.fn()
    renderDialog({ onAlreadyJoined })

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    await waitFor(() => expect(onAlreadyJoined).toHaveBeenCalledWith(7, false, "已加入的課"))
    // 不該停在預覽畫面等使用者再按一次「確認加入」——他已經在這門課了。
    expect(screen.queryByRole("button", { name: "確認加入" })).not.toBeInTheDocument()
  })

  it("起始時間未到時預覽顯示開放時間（SA Q2 裁示 A）", async () => {
    server.use(
      http.post("/api/et/enrollments/preview", () =>
        HttpResponse.json({
          course_id: 9,
          course_name: "尚未開放的課",
          owner_name: "王教師",
          chapter_count: 2,
          already_joined: false,
          open_start_at: "2099-01-01T09:00:00Z",
        }),
      ),
    )
    const user = userEvent.setup()
    renderDialog()

    await user.type(codeInput(), "12345678")
    await user.click(screen.getByRole("button", { name: "查詢" }))

    // 不提示的話學員加入成功卻在清單看不到課程（AC 4），會以為失敗而反覆重試。
    expect(await screen.findByText(/將於.*開放學習/)).toBeInTheDocument()
  })
})
