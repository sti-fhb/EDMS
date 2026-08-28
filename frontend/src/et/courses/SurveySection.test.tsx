import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SurveySection } from "./SurveySection"
import type { SurveyDetail } from "./surveySchemas"

const noop = () => {}

const BASE_PROPS = {
  readOnly: false,
  onCreate: noop,
  onRename: noop,
  onDeactivate: noop,
  onSaveQuestion: noop,
  onDeleteQuestion: noop,
  onReorder: noop,
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

describe("SurveySection：已建立", () => {
  it("列出題目與選項摘要", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.getByText("您對本課程是否滿意？")).toBeInTheDocument()
    expect(screen.getByText("滿意 / 不滿意")).toBeInTheDocument()
    expect(screen.getByText("Q1")).toBeInTheDocument()
  })

  it("顯示填答統計", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey({ responded_count: 18, pending_count: 10 })} />)
    expect(screen.getByText("填答狀況：已填 18 / 未填 10")).toBeInTheDocument()
  })

  it("點新增題目展開編輯器", async () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} />)
    await userEvent.click(screen.getByRole("button", { name: "新增題目" }))
    expect(screen.getByRole("button", { name: "儲存題目" })).toBeInTheDocument()
  })

  it("停用中的問卷顯示標記且不再有停用鈕", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey({ is_active: false })} />)
    expect(screen.getByText("已停用")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "停用問卷" })).not.toBeInTheDocument()
  })

  it("顯示區塊層級錯誤訊息", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} error="已有學員填答，題目與選項不可修改" />)
    expect(screen.getByText("已有學員填答，題目與選項不可修改")).toBeInTheDocument()
  })
})

describe("SurveySection：凍結（AC 21）", () => {
  const frozen = makeSurvey({ frozen: true, responded_count: 3 })

  it("顯示凍結提示", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.getByText(/題目與選項已凍結/)).toBeInTheDocument()
  })

  it("隱藏新增題目與編輯 / 刪除鈕", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "編輯第 1 題" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "刪除第 1 題" })).not.toBeInTheDocument()
  })

  it("停用問卷仍可按——AC 21 明訂凍結後教師僅可停用", () => {
    // 把停用也鎖掉，凍結後整張卡片就變成死的，教師無路可走。
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.getByRole("button", { name: "停用問卷" })).toBeEnabled()
  })

  it("拖拉手把收起", () => {
    render(<SurveySection {...BASE_PROPS} survey={frozen} />)
    expect(screen.queryByLabelText("拖曳調整第 1 題順序")).not.toBeInTheDocument()
  })
})

describe("SurveySection：唯讀（非擁有者）", () => {
  it("所有操作入口皆不顯示", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} readOnly />)
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "停用問卷" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("拖曳調整第 1 題順序")).not.toBeInTheDocument()
  })

  it("問卷名稱欄位停用", () => {
    render(<SurveySection {...BASE_PROPS} survey={makeSurvey()} readOnly />)
    expect(screen.getByLabelText(/問卷名稱/)).toBeDisabled()
  })
})
