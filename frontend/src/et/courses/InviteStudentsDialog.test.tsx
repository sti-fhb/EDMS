import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"
import { InviteStudentsDialog } from "./InviteStudentsDialog"

const BASE_PROPS = {
  open: true,
  courseId: 7,
  courseName: "採血作業新進人員訓練",
  invitationCode: "83052617",
  onClose: () => {},
}

/** 開啟視窗並切到「邀請碼」頁籤。 */
async function openCodeTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: /邀請碼/ }))
}

describe("InviteStudentsDialog：Email 邀請流程", () => {
  it("輸入 Email 後按下一步顯示唯讀預覽", async () => {
    const user = userEvent.setup()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)

    await user.type(screen.getByLabelText("學員 Email"), "a@x.gov.tw,b@x.gov.tw")
    await user.click(screen.getByRole("button", { name: "下一步" }))

    await waitFor(() => {
      expect(screen.getByText("信件內容由管理者統一維護，僅可預覽、不可編輯")).toBeInTheDocument()
    })
    // FR-ET-US8-07：教師不可編輯主旨與內文
    expect(screen.getByLabelText("主旨")).toHaveAttribute("readonly")
    expect(screen.getByLabelText("內文")).toHaveAttribute("readonly")
    expect(screen.getByText(/以第 1 筆收件人為預覽範例/)).toBeInTheDocument()
  })

  it("預覽出現後才有確認寄出，寄出成功關閉視窗", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} onClose={onClose} />)

    expect(screen.queryByRole("button", { name: "確認寄出" })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText("學員 Email"), "a@x.gov.tw")
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "確認寄出" })).toBeInTheDocument())

    await user.click(screen.getByRole("button", { name: "確認寄出" }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it("修改 Email 清單後預覽消失，避免寄出與畫面不符的內容", async () => {
    const user = userEvent.setup()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)

    await user.type(screen.getByLabelText("學員 Email"), "a@x.gov.tw")
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await waitFor(() => expect(screen.getByLabelText("主旨")).toBeInTheDocument())

    await user.type(screen.getByLabelText("學員 Email"), ",c@x.gov.tw")

    expect(screen.queryByLabelText("主旨")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "下一步" })).toBeInTheDocument()
  })

  it("格式錯誤時不打 API，直接在欄位下方指出是哪幾筆", async () => {
    const user = userEvent.setup()
    let called = false
    server.use(
      http.post("/api/et/courses/:courseId/invitations/preview", () => {
        called = true
        return HttpResponse.json({ subject: "", body: "", recipient_sample: "", recipient_count: 0 })
      }),
    )
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)

    await user.type(screen.getByLabelText("學員 Email"), "broken")
    await user.click(screen.getByRole("button", { name: "下一步" }))

    expect(await screen.findByText("以下 Email 格式不正確：broken")).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it("部分寄送失敗時不關閉視窗並列出失敗的 Email", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(
      http.post("/api/et/courses/:courseId/invitations", () =>
        HttpResponse.json({ sent: 1, failed: ["b@x.gov.tw"] }),
      ),
    )
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} onClose={onClose} />)

    await user.type(screen.getByLabelText("學員 Email"), "a@x.gov.tw,b@x.gov.tw")
    await user.click(screen.getByRole("button", { name: "下一步" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "確認寄出" })).toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "確認寄出" }))

    // 鎖定「部分寄送失敗」那一則 Alert：畫面上另有說明用的 info Alert，
    // 而輸入框裡也有同一組 Email——用 role 或全頁文字搜尋都會撞到別的節點。
    const alert = (await screen.findByText(/部分 Email 寄送失敗/)).closest('[role="alert"]')
    expect(alert).toHaveTextContent("b@x.gov.tw")
    expect(onClose).not.toHaveBeenCalled()
  })

  it("顯示將寄出的封數", async () => {
    const user = userEvent.setup()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)
    await user.type(screen.getByLabelText("學員 Email"), "a@x.gov.tw,b@x.gov.tw,a@x.gov.tw")
    // 重複者去重後為 2 封
    expect(screen.getByText("將寄出 2 封邀請信")).toBeInTheDocument()
  })
})

describe("InviteStudentsDialog：邀請碼頁籤", () => {
  it("顯示邀請碼、複製連結與 QR Code", async () => {
    const user = userEvent.setup()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)
    await openCodeTab(user)

    expect(screen.getByText("83052617")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "複製邀請連結" })).toBeInTheDocument()
    expect(screen.getByTitle("課程邀請 QR Code")).toBeInTheDocument()
  })

  it("複製邀請連結會寫入剪貼簿", async () => {
    const user = userEvent.setup()
    // 順序要緊：`userEvent.setup()` 會自行接管 `navigator.clipboard`，先設會被它蓋掉。
    // 又：jsdom 的 `navigator.clipboard` 只有 getter，`Object.assign` 會拋 TypeError。
    const writeText = vi.fn()
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} />)
    await openCodeTab(user)

    await user.click(screen.getByRole("button", { name: "複製邀請連結" }))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("code=83052617"))
  })

  it("尚無邀請碼時提示發布後才會產生，而非顯示空白", async () => {
    const user = userEvent.setup()
    renderWithProviders(<InviteStudentsDialog {...BASE_PROPS} invitationCode={null} />)
    await openCodeTab(user)

    expect(screen.getByText("課程發布後系統才會自動產生邀請碼。")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "複製邀請連結" })).not.toBeInTheDocument()
  })
})
