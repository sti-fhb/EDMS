import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { HttpResponse, http } from "msw"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtLearnPage } from "./LearnPage"
import type { LearnStructure } from "./learnSchemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

const navigate = vi.fn()
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>()
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ courseId: "1" }) }
})

beforeEach(() => navigate.mockReset())

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
        survey: null,
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

  it("測驗項目就地顯示測驗資訊，可直接開始作答（AC 10）", async () => {
    // 影片與文件都是點了就看得到內容；測驗沒有理由先給一顆按鈕、按了才跳到另一頁看
    // 題數與及格分數。原本的 `/et/quizzes/:quizId` 引導頁已移除。
    mockStructure({})
    const user = userEvent.setup()
    renderWithProviders(<EtLearnPage />)

    await user.click(await screen.findByText("基本概念測驗"))

    // 資訊直接出現在內容區，不需要再跳一頁
    expect(await screen.findByText("題數")).toBeInTheDocument()
    expect(screen.getByText("及格分數")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /開始作答/ }))

    expect(navigate).toHaveBeenCalledWith("/et/attempts/800")
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

  describe("進度與解鎖（#274）", () => {
    it("重新進入定位至上次檢視之項目（AC 11）", async () => {
      // 第 1 章第 1 項是教材、第 2 項是測驗；`last_item_id` 指向測驗 → 應直接開在測驗
      mockStructure({ last_item_id: 101 })
      renderWithProviders(<EtLearnPage />)

      expect(await screen.findByRole("button", { name: /開始作答/ })).toBeInTheDocument()
    })

    it("鎖定項目點擊時擋下並提示（AC 6 / ET-MSG-ET05-001）", async () => {
      mockStructure({ chapters: lockedChapters() })
      const user = userEvent.setup()
      renderWithProviders(<EtLearnPage />)

      await user.click(await screen.findByText("基本概念測驗"))

      // **提示而非靜默無反應**——學員需要知道為什麼點不動
      expect(await screen.findByText("請先完成本章節之影片學習")).toBeInTheDocument()
      // 內容區沒有切過去（測驗面板不該出現）
      expect(screen.queryByRole("button", { name: /開始作答/ })).not.toBeInTheDocument()
    })

    it("側欄顯示課程進度（完成項目數 ÷ 總項目數）", async () => {
      mockStructure({ chapters: threeStateChapters(), last_item_id: 102 })
      renderWithProviders(<EtLearnPage />)

      // 3 項中 1 項完成
      expect(await screen.findByText(/課程進度 1 \/ 3（33%）/)).toBeInTheDocument()
    })

    it("教師預覽不顯示課程進度條", async () => {
      // 恆為 0% 的進度條只會讓教師以為自己「什麼都沒完成」
      mockStructure({ is_owner: true })
      renderWithProviders(<EtLearnPage />)
      await screen.findByText("第一章 採血基本流程")

      expect(screen.queryByText(/課程進度/)).not.toBeInTheDocument()
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

  describe("課後問卷入口（#284 / AC 18–21）", () => {
    it("可填時顯示「填寫課後問卷」並可進入問卷頁", async () => {
      const user = userEvent.setup()
      mockStructure({
        survey: { survey_id: 5, survey_name: "課後滿意度問卷", state: "FILLABLE", submitted_at: null },
      })
      renderWithProviders(<EtLearnPage />)

      await user.click(await screen.findByRole("button", { name: "填寫課後問卷" }))

      expect(screen.getByText(/具名、一人一次/)).toBeInTheDocument()
      expect(navigate).toHaveBeenCalledWith("/et/courses/1/survey")
    })

    it("已送出時改顯示「查看我的填答」與送出時間", async () => {
      mockStructure({
        survey: {
          survey_id: 5,
          survey_name: "課後滿意度問卷",
          state: "SUBMITTED",
          submitted_at: "2026-09-08T06:30:00Z",
        },
      })
      renderWithProviders(<EtLearnPage />)

      expect(await screen.findByRole("button", { name: "查看我的填答" })).toBeInTheDocument()
      expect(screen.getByText(/已於 .* 送出/)).toBeInTheDocument()
    })

    it("課程關閉且未填時入口仍顯示（AC 10：點進去才見關閉提示）", async () => {
      mockStructure({
        is_closed: true,
        status: "CLOSED",
        survey: { survey_id: 5, survey_name: "課後滿意度問卷", state: "COURSE_CLOSED", submitted_at: null },
      })
      renderWithProviders(<EtLearnPage />)

      expect(await screen.findByRole("button", { name: "填寫課後問卷" })).toBeInTheDocument()
    })

    it("未完課（HIDDEN）時整塊不渲染", async () => {
      mockStructure({
        survey: { survey_id: 5, survey_name: "課後滿意度問卷", state: "HIDDEN", submitted_at: null },
      })
      renderWithProviders(<EtLearnPage />)
      await screen.findByText("第一章 採血基本流程")

      expect(screen.queryByRole("button", { name: /課後問卷|我的填答/ })).not.toBeInTheDocument()
      expect(screen.queryByText(/具名、一人一次/)).not.toBeInTheDocument()
    })

    it("課程無問卷（null）時整塊不渲染", async () => {
      mockStructure({ survey: null })
      renderWithProviders(<EtLearnPage />)
      await screen.findByText("第一章 採血基本流程")

      expect(screen.queryByRole("button", { name: /課後問卷|我的填答/ })).not.toBeInTheDocument()
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
