import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AttemptHistory } from "./AttemptHistory"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate }
})

beforeEach(() => navigate.mockReset())

describe("ET06 歷次作答紀錄", () => {
  it("依 ATTEMPT_NO 遞增列出每一次", async () => {
    // 學員想回看的往往正是第 1 次；倒序會把它推到最下面
    renderWithProviders(<AttemptHistory quizId={700} />)

    const rows = await screen.findAllByRole("row")
    // rows[0] 是表頭
    expect(rows[1]).toHaveTextContent("第 1 次")
    expect(rows[2]).toHaveTextContent("第 2 次")
  })

  it("分數帶分母——發布後教師可改配分，只給分子會誤導", async () => {
    server.use(
      http.get("/api/et/quizzes/:quizId/attempts", () =>
        HttpResponse.json([
          {
            attempt_id: 799,
            attempt_no: 1,
            submitted_at: "2026-09-03T02:12:00Z",
            score: "60.00",
            points_total: 100,
            is_pass: false,
            status: "SUBMITTED",
          },
          {
            attempt_id: 800,
            attempt_no: 2,
            submitted_at: "2026-09-04T10:00:00Z",
            score: "60.00",
            points_total: 300,
            is_pass: false,
            status: "SUBMITTED",
          },
        ]),
      ),
    )
    renderWithProviders(<AttemptHistory quizId={700} />)

    // 兩次都是 60 分但意義完全不同——沒有分母就分不出來
    expect(await screen.findByText("60.00 / 100")).toBeInTheDocument()
    expect(screen.getByText("60.00 / 300")).toBeInTheDocument()
  })

  it("鍵盤使用者可經由列尾按鈕進入回看，且不重複導航", async () => {
    // `<tr>` 不可聚焦，整列可點只服務滑鼠
    const user = userEvent.setup()
    renderWithProviders(<AttemptHistory quizId={700} />)

    await user.click(await screen.findByRole("button", { name: "回看第 1 次作答明細" }))

    expect(navigate).toHaveBeenCalledTimes(1) // stopPropagation 生效，沒有連整列一起觸發
    expect(navigate).toHaveBeenCalledWith("/et/attempts/799/result")
  })

  it("逾時自動提交如實標示", async () => {
    server.use(
      http.get("/api/et/quizzes/:quizId/attempts", () =>
        HttpResponse.json([
          {
            attempt_id: 799,
            attempt_no: 1,
            submitted_at: "2026-09-03T02:12:00Z",
            score: "20.00",
            points_total: 100,
            is_pass: false,
            status: "TIMEOUT",
          },
        ]),
      ),
    )
    renderWithProviders(<AttemptHistory quizId={700} />)

    expect(await screen.findByText("逾時")).toBeInTheDocument()
  })

  it("零筆時整塊不顯示", async () => {
    // 一張空表格會讓學員以為系統把他的紀錄弄丟了
    server.use(http.get("/api/et/quizzes/:quizId/attempts", () => HttpResponse.json([])))
    const { container } = renderWithProviders(<AttemptHistory quizId={700} />)

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(container).toBeEmptyDOMElement()
  })

  it("查詢失敗時靜默不顯示，且不噴例外", async () => {
    // ⚠️ **刻意與「零筆」外觀相同**：這是輔助資訊，為它插一塊錯誤訊息會擠掉主要動作
    //（開始作答）。代價是使用者分不出「沒有紀錄」與「載入失敗」——已知並接受。
    server.use(
      http.get("/api/et/quizzes/:quizId/attempts", () =>
        HttpResponse.json({ error_code: "COMMON_500", error_message: "壞了" }, { status: 500 }),
      ),
    )
    const { container } = renderWithProviders(<AttemptHistory quizId={700} />)

    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(container).toBeEmptyDOMElement()
  })
})
