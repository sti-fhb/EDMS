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
        last_item_id: null,
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

  describe("進度與解鎖（#274）", () => {
    it("重新進入定位至上次檢視之項目（AC 11）", async () => {
      // 第 1 章第 1 項是教材、第 2 項是測驗；`last_item_id` 指向測驗 → 應直接開在測驗
      mockStructure({ last_item_id: 101 })
      renderWithProviders(<EtLearnPage />)

      expect(await screen.findByRole("button", { name: "開始測驗" })).toBeInTheDocument()
    })

    it("鎖定項目點擊時擋下並提示（AC 6 / ET-MSG-ET05-001）", async () => {
      mockStructure({ chapters: lockedChapters() })
      const user = userEvent.setup()
      renderWithProviders(<EtLearnPage />)

      await user.click(await screen.findByText("基本概念測驗"))

      // **提示而非靜默無反應**——學員需要知道為什麼點不動
      expect(await screen.findByText("請先完成本章節之影片學習")).toBeInTheDocument()
      // 內容區沒有切過去（測驗入口不該出現）
      expect(screen.queryByRole("button", { name: "開始測驗" })).not.toBeInTheDocument()
    })

    it("側欄三態顯示真實狀態（AC 14）", async () => {
      // `last_item_id` 指向第 2 章，故第 1 章那兩項不是「進行中」——`itemDisplayState`
      // 讓 active 蓋過 completed，兩者放在同一項上就驗不到完成標記。
      mockStructure({ chapters: threeStateChapters(), last_item_id: 102 })
      renderWithProviders(<EtLearnPage />)
      await screen.findByText("採血流程概論")

      expect(screen.getAllByTestId("CheckCircleIcon")).toHaveLength(1) // 已完成 ✓
      expect(screen.getByTestId("ArrowCircleRightIcon")).toBeInTheDocument() // 進行中 →
      expect(screen.getByTestId("LockIcon")).toBeInTheDocument() // 鎖定 🔒
    })
  })
})

/** 已完成 ✓ / 進行中 → / 鎖定 🔒 三態同時出現的側欄形狀。 */
function threeStateChapters() {
  const [first] = lockedChapters()
  return [
    first,
    {
      chapter_id: 11,
      chapter_name: "第二章 進階操作",
      sort_order: 2,
      items: [
        {
          item_id: 102,
          item_type: "MATERIAL" as const,
          sort_order: 1,
          title: "進階操作示範",
          material_id: 1002,
          quiz_id: null,
          locked: false,
          completed: false,
        },
      ],
    },
  ]
}

/** 第 1 項已完成、第 2 項（測驗）鎖定——章節內依序解鎖（裁示 Q2=A）的側欄形狀。 */
function lockedChapters() {
  return [
    {
      chapter_id: 10,
      chapter_name: "第一章 採血基本流程",
      sort_order: 1,
      items: [
        {
          item_id: 100,
          item_type: "MATERIAL" as const,
          sort_order: 1,
          title: "採血流程概論",
          material_id: 1000,
          quiz_id: null,
          locked: false,
          completed: true,
        },
        {
          item_id: 101,
          item_type: "QUIZ" as const,
          sort_order: 2,
          title: "基本概念測驗",
          material_id: null,
          quiz_id: 2000,
          locked: true,
          completed: false,
        },
      ],
    },
  ]
}
