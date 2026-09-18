import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SurveySection } from "./SurveySection"
import type { SurveyDetail } from "./surveySchemas"

const noop = () => {}

const BASE_PROPS = {
  readOnly: false,
  isDraftCourse: true,
  onCreate: noop,
  onOpen: noop,
  onDeactivate: noop,
  onDelete: noop,
}

function makeSurvey(overrides: Partial<SurveyDetail> = {}): SurveyDetail {
  return {
    survey_id: 1,
    course_id: 10,
    survey_name: "課後滿意度問卷",
    is_active: true,
    version: 0,
    frozen: false,
    responded_count: 0,
    pending_count: 0,
    questions: [
      {
        sq_id: 100,
        question_type: "SINGLE",
        stem: "您對本課程是否滿意？",
        sort_order: 1,
        version: 0,
        options: [
          { so_id: 1, option_text: "滿意", sort_order: 1 },
          { so_id: 2, option_text: "不滿意", sort_order: 2 },
        ],
      },
    ],
    ...overrides,
  }
}

describe("SurveySection：尚未建立", () => {
  it("survey 為 null 時顯示空狀態與新增鈕", () => {
    render(<SurveySection {...BASE_PROPS} survey={null} />)
    expect(screen.getByText("尚未建立課後問卷")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "新增問卷" })).toBeEnabled()
  })

  it("載入中（undefined）時新增鈕停用", () => {
    // `null` = 確定沒有問卷、`undefined` = 還在載入。兩者都顯示空狀態，但載入中不該
    // 讓使用者按下去——那會對一個還不知道有沒有問卷的課程送出建立請求。
    render(<SurveySection {...BASE_PROPS} survey={undefined} />)
    expect(screen.getByRole("button", { name: "新增問卷" })).toBeDisabled()
  })

  it("新增模式（課程尚未建立）時停用並說明原因", () => {
    render(<SurveySection {...BASE_PROPS} survey={null} disabled />)
    expect(screen.getByRole("button", { name: "新增問卷" })).toBeDisabled()
    expect(screen.getByText("請先儲存草稿後再新增問卷")).toBeInTheDocument()
  })

  it("名稱留空按建立會擋下並提示", async () => {
    const onCreate = vi.fn()
    render(<SurveySection {...BASE_PROPS} survey={null} onCreate={onCreate} />)
    await userEvent.click(screen.getByRole("button", { name: "新增問卷" }))
    await userEvent.click(screen.getByRole("button", { name: "建立" }))

    expect(screen.getByText("請輸入問卷名稱")).toBeInTheDocument()
    expect(onCreate).not.toHaveBeenCalled()
  })

  it("輸入名稱後建立會帶去除空白的值", async () => {
    const onCreate = vi.fn()
    render(<SurveySection {...BASE_PROPS} survey={null} onCreate={onCreate} />)
    await userEvent.click(screen.getByRole("button", { name: "新增問卷" }))
    await userEvent.type(screen.getByLabelText(/問卷名稱/), "  滿意度  ")
    await userEvent.click(screen.getByRole("button", { name: "建立" }))

    expect(onCreate).toHaveBeenCalledWith("滿意度")
  })

  it("唯讀時不顯示新增鈕", () => {
    render(<SurveySection {...BASE_PROPS} survey={null} readOnly />)
    expect(screen.queryByRole("button", { name: "新增問卷" })).not.toBeInTheDocument()
  })
})

describe("SurveySection：摘要卡（#238 題目管理已移入 Dialog）", () => {
  it("顯示問卷標籤、名稱與題數", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.getByText("問卷")).toBeInTheDocument()
    expect(screen.getByText("課後滿意度問卷")).toBeInTheDocument()
    expect(screen.getByText(/1 題/)).toBeInTheDocument()
  })

  it("不顯示填答狀況——那屬 ET-9 的問卷結果區塊", () => {
    // 且在 ET-4 / ET-8 交付前恆為 0，顯示了也只是佔位（2026-08-31 實測回饋）
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey({ responded_count: 18, pending_count: 10 })} />)
    expect(screen.queryByText(/填答狀況/)).not.toBeInTheDocument()
  })

  it("不再直接列出題目內容——那是 Dialog 的事", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.queryByText("您對本課程是否滿意？")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
  })

  it("點編輯開啟視窗", async () => {
    const onOpen = vi.fn()
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} onOpen={onOpen} />)
    await userEvent.click(screen.getByRole("button", { name: "編輯" }))
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it("零題時提醒會擋住發布", () => {
    // #204 之第七項發布檢核；在這裡先講比讓教師按了發布才發現好
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey({ questions: [] })} />)
    expect(screen.getByText(/至少須有 1 題才能發布課程/)).toBeInTheDocument()
  })

  it("停用中的問卷顯示標記", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey({ is_active: false })} isDraftCourse={false} />)
    expect(screen.getByText("已停用")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "停用問卷" })).not.toBeInTheDocument()
  })

  it("顯示區塊層級錯誤訊息", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} error="已有學員填答，題目與選項不可修改" />)
    expect(screen.getByText("已有學員填答，題目與選項不可修改")).toBeInTheDocument()
  })
})

describe("SurveySection：刪除與停用互補（#238）", () => {
  it("草稿課程：有垃圾桶、**沒有**停用鈕", () => {
    // 停用的作用是讓學員端不再顯示填寫入口，而草稿課程學員本來就看不到——
    // 那裡放停用只是一顆沒有效果的按鈕（2026-08-31 實測回饋）
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} isDraftCourse />)
    expect(screen.getByRole("button", { name: "刪除問卷" })).toBeEnabled()
    expect(screen.queryByRole("button", { name: "停用問卷" })).not.toBeInTheDocument()
  })

  it("已發布課程：有停用鈕、**沒有**垃圾桶", () => {
    // 後端另以 ET_SURVEY_007 把關，前端隱藏僅為 UX——不該讓教師按了才知道不行
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} isDraftCourse={false} />)
    expect(screen.getByRole("button", { name: "停用問卷" })).toBeEnabled()
    expect(screen.queryByRole("button", { name: "刪除問卷" })).not.toBeInTheDocument()
  })

  it("點垃圾桶通知呼叫端", async () => {
    const onDelete = vi.fn()
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} onDelete={onDelete} />)
    await userEvent.click(screen.getByRole("button", { name: "刪除問卷" }))
    expect(onDelete).toHaveBeenCalledOnce()
  })

  it("唯讀時不顯示垃圾桶", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} readOnly />)
    expect(screen.queryByRole("button", { name: "刪除問卷" })).not.toBeInTheDocument()
  })
})

describe("SurveySection：凍結", () => {
  const frozen = makeSurvey({ frozen: true, responded_count: 3 })

  it("不再顯示「已凍結」標記——原因改由停用的編輯鈕自己說明", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.queryByText("已凍結")).not.toBeInTheDocument()
  })

  it("編輯鈕停用", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.getByRole("button", { name: "編輯" })).toBeDisabled()
  })

  it("停用的編輯鈕帶出原因與仍可做的事（#335）", async () => {
    // 一顆灰掉而不說明原因的按鈕，教師無法判斷是壞了還是不該按。
    // 提示須同時講「不能做什麼」與「還能做什麼」，否則資訊量比原本的 Chip 更少。
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    // disabled 按鈕帶 `pointer-events: none`，user-event 預設會拒絕對它操作。
    // Tooltip 掛在外層 `<span>`（disabled 元素不發滑鼠事件），指標進入按鈕區域時
    // 事件會冒泡到該 span——關掉這道檢查才模擬得出使用者實際的滑入動作。
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await user.hover(screen.getByRole("button", { name: "編輯" }))
    const tip = await screen.findByRole("tooltip")
    expect(tip).toHaveTextContent(/已有學員填答/)
    expect(tip).toHaveTextContent(/僅可停用問卷/)
  })

  it("未凍結時編輯鈕沒有提示", async () => {
    // 防止 Tooltip 的 title 寫成常數——那會讓每張卡片都掛一個沒意義的提示。
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} />)
    await userEvent.hover(screen.getByRole("button", { name: "編輯" }))
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
  })

  it("停用問卷仍可按——AC 21 明訂凍結後教師僅可停用", () => {
    // 把停用也鎖掉，凍結後整張卡片就變成死的，教師無路可走。
    // 能凍結代表已有填答，也就必然是已發布課程，故以 isDraftCourse={false} 呈現。
    render(<SurveySection {...BASE_PROPS} survey={frozen} isDraftCourse={false} />)
    expect(screen.getByRole("button", { name: "停用問卷" })).toBeEnabled()
  })

  it("唯讀者即使凍結仍可檢視——那是他看內容的唯一入口", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} readOnly />)
    expect(screen.getByRole("button", { name: "檢視" })).toBeEnabled()
  })
})

describe("SurveySection：唯讀（非擁有者）", () => {
  it("僅保留檢視入口", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} readOnly />)
    expect(screen.getByRole("button", { name: "檢視" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "停用問卷" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "刪除問卷" })).not.toBeInTheDocument()
  })
})
