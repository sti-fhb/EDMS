import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { describe, expect, it, vi } from "vitest"

import { EtLearnPage } from "./LearnPage"
import type { LearnStructure } from "./learnSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ courseId: "1" }) }
})

function mockStructure(overrides: Partial<LearnStructure>) {
  server.use(
    http.get("/api/et/courses/:courseId/learn", () =>
      HttpResponse.json({
        course_id: 1,
        course_name: "採血作業新進人員訓練",
        status: "PUBLISHED",
        is_owner: false,
        is_closed: false,
        playback_rates: [0.75, 1.0, 1.25, 1.5, 2.0],
        chapters: [
          {
            chapter_id: 10,
            chapter_name: "第一章 採血基本流程",
            sort_order: 1,
            items: [
              {
                item_id: 100,
                item_type: "MATERIAL",
                sort_order: 1,
                title: "採血流程概論",
                material_id: 1000,
                quiz_id: null,
                locked: false,
                completed: false,
              },
              {
                item_id: 101,
                item_type: "QUIZ",
                sort_order: 2,
                title: "基本概念測驗",
                material_id: null,
                quiz_id: 2000,
                locked: false,
                completed: false,
              },
            ],
          },
        ],
        ...overrides,
      }),
    ),
  )
}

describe("ET05 章節學習頁", () => {
  it("顯示課程名稱、章節與項目（AC 1）", async () => {
    mockStructure({})
    renderWithProviders(<EtLearnPage />)

    expect(await screen.findByText("採血作業新進人員訓練")).toBeInTheDocument()
    expect(screen.getByText("第一章 採血基本流程")).toBeInTheDocument()
    expect(screen.getByText("採血流程概論")).toBeInTheDocument()
    expect(screen.getByText("基本概念測驗")).toBeInTheDocument()
  })

  it("首次進入定位至第 1 章第 1 項（AC 2）", async () => {
    mockStructure({})
    renderWithProviders(<EtLearnPage />)

    // 第一個項目是教材 → 內容區載入該教材（MSW 預設回「採血流程概論」教材內容）
    expect(await screen.findByText("採血流程概論教材")).toBeInTheDocument()
  })

  it("測驗項目顯示開始測驗入口，點擊提示尚未開放（AC 10）", async () => {
    mockStructure({})
    const user = userEvent.setup()
    renderWithProviders(<EtLearnPage />)

    await user.click(await screen.findByText("基本概念測驗"))

    const start = await screen.findByRole("button", { name: "開始測驗" })
    await user.click(start)
    // `ET-6` 未實作——提示而非 navigate 到不存在的路由（那會是白畫面）
    expect(await screen.findByText("線上測驗尚未開放")).toBeInTheDocument()
  })

  it("課程已關閉時顯示唯讀提示，且內容照常呈現（AC 23 / 裁示 Q2=A）", async () => {
    mockStructure({ is_closed: true, status: "CLOSED" })
    renderWithProviders(<EtLearnPage />)

    expect(await screen.findByText(/此課程目前關閉中/)).toBeInTheDocument()
    // 關閉限制的是寫入，不是讀取——章節項目不得被過濾掉
    expect(screen.getByText("採血流程概論")).toBeInTheDocument()
  })

  it("擁有者進入時顯示預覽模式提示（裁示 Q1=A）", async () => {
    mockStructure({ is_owner: true })
    renderWithProviders(<EtLearnPage />)

    // 明示身分，避免教師以為自己正在累積進度
    expect(await screen.findByText(/預覽模式/)).toBeInTheDocument()
    expect(screen.getByText(/不會累積學習進度/)).toBeInTheDocument()
  })

  it("非在籍者顯示後端的錯誤訊息", async () => {
    server.use(
      http.get("/api/et/courses/:courseId/learn", () =>
        HttpResponse.json({ error_code: "ET_LEARN_002", error_message: "您尚未加入此課程" }, { status: 403 }),
      ),
    )
    renderWithProviders(<EtLearnPage />)

    expect(await screen.findByText("您尚未加入此課程")).toBeInTheDocument()
  })

  it("整頁不出現課後問卷入口（`ET-15` 未實作）", async () => {
    mockStructure({})
    renderWithProviders(<EtLearnPage />)
    await screen.findByText("第一章 採血基本流程")

    // wireframe 側欄底部有這顆按鈕，但本 issue 不做——照抄會做出永遠不動作的元件
    expect(screen.queryByRole("button", { name: /問卷/ })).not.toBeInTheDocument()
  })
})
