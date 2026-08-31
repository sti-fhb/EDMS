import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SurveyDialog } from "./SurveyDialog"
import type { SurveyDetail, SurveyTemplateRow } from "./surveySchemas"

const noop = () => {}

const TEMPLATES: SurveyTemplateRow[] = [
  { code: "DEFAULT", name: "課程回饋問卷", description: "滿意度與開放式建議", question_count: 6 },
]

const BASE_PROPS = {
  open: true,
  readOnly: false,
  templates: TEMPLATES,
  onClose: noop,
  onRename: noop,
  onApplyTemplate: noop,
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

const TEXT_QUESTION = {
  sq_id: 200,
  question_type: "TEXT" as const,
  stem: "對本課程還有什麼建議？",
  sort_order: 2,
  version: 0,
  options: [],
}

describe("SurveyDialog：題目清單", () => {
  it("列出題目與選項摘要", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.getByText("您對本課程是否滿意？")).toBeInTheDocument()
    expect(screen.getByText("滿意 / 不滿意")).toBeInTheDocument()
    expect(screen.getByText("Q1")).toBeInTheDocument()
    expect(screen.getByText("單選")).toBeInTheDocument()
  })

  it("問答題顯示作答形式而非空白摘要", () => {
    // 問答題沒有選項可摘要——留白會讓那一列看起來像壞掉的資料
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey({ questions: [TEXT_QUESTION] })} />)
    expect(screen.getByText("問答")).toBeInTheDocument()
    expect(screen.getByText("學員以文字作答")).toBeInTheDocument()
  })

  it("載入中顯示進度指示", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={null} loading />)
    expect(screen.getByRole("progressbar")).toBeInTheDocument()
  })

  it("點新增題目展開編輯器", async () => {
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} />)
    await userEvent.click(screen.getByRole("button", { name: "新增題目" }))
    expect(screen.getByRole("button", { name: "儲存題目" })).toBeInTheDocument()
  })

  it("不顯示填答狀況——那屬 ET-9 的問卷結果區塊", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey({ responded_count: 18, pending_count: 10 })} />)
    expect(screen.queryByText(/填答狀況/)).not.toBeInTheDocument()
  })

  it("關閉入口只有標題列的 ✕", () => {
    // 每項編輯都即時生效（名稱失焦即存、題目各有儲存鈕），底部再放「關閉」
    // 會讓人以為那是「儲存並關閉」（2026-08-31 實測回饋移除）
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.getByRole("button", { name: "關閉視窗" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "關閉" })).not.toBeInTheDocument()
  })
})

describe("SurveyDialog：關閉時的未存草稿", () => {
  it("沒有展開編輯器時關閉不算 dirty", async () => {
    const onClose = vi.fn()
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} onClose={onClose} />)
    await userEvent.click(screen.getByRole("button", { name: "關閉視窗" }))
    expect(onClose).toHaveBeenCalledWith(false)
  })

  it("題目編輯器展開中關閉會回報 dirty", async () => {
    // 展開中代表有還沒存的內容，直接關掉會讓它無聲消失
    // （#203 實測回饋：「有填入值按取消跳出提示」）
    const onClose = vi.fn()
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} onClose={onClose} />)
    await userEvent.click(screen.getByRole("button", { name: "新增題目" }))
    await userEvent.click(screen.getByRole("button", { name: "關閉視窗" }))
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it("編輯既有題目時關閉也算 dirty", async () => {
    const onClose = vi.fn()
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} onClose={onClose} />)
    await userEvent.click(screen.getByRole("button", { name: "編輯第 1 題" }))
    await userEvent.click(screen.getByRole("button", { name: "關閉視窗" }))
    expect(onClose).toHaveBeenCalledWith(true)
  })
})

describe("SurveyDialog：模板（#238）", () => {
  it("空問卷時顯示單一「套用模板」鈕與題數說明", () => {
    // 2026-08-31 實測回饋：由兩組改為一組，教師不必先決定用哪組
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey({ questions: [] })} />)
    expect(screen.getByRole("button", { name: "套用模板" })).toBeInTheDocument()
    expect(screen.getByText(/帶入 6 題常用題目/)).toBeInTheDocument()
  })

  it("已有題目時不顯示模板——後端亦以 ET_SURVEY_010 擋下", () => {
    // 不顯示入口是為了讓教師不必先試一次才知道不行
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} />)
    expect(screen.queryByRole("button", { name: "套用模板" })).not.toBeInTheDocument()
  })

  it("點套用帶出代碼", async () => {
    const onApplyTemplate = vi.fn()
    render(
      <SurveyDialog {...BASE_PROPS} survey={makeSurvey({ questions: [] })} onApplyTemplate={onApplyTemplate} />,
    )
    await userEvent.click(screen.getByRole("button", { name: "套用模板" }))
    expect(onApplyTemplate).toHaveBeenCalledWith("DEFAULT")
  })

  it("模板清單為空時不顯示區塊", () => {
    // templates[0] 會是 undefined——不擋的話整個視窗會炸
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey({ questions: [] })} templates={[]} />)
    expect(screen.queryByRole("button", { name: "套用模板" })).not.toBeInTheDocument()
  })

  it("唯讀時不顯示模板", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey({ questions: [] })} readOnly />)
    expect(screen.queryByRole("button", { name: "套用模板" })).not.toBeInTheDocument()
  })
})

describe("SurveyDialog：凍結", () => {
  const frozen = makeSurvey({ frozen: true, responded_count: 3 })

  it("顯示凍結提示", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={frozen} />)
    expect(screen.getByText(/題目與選項已凍結/)).toBeInTheDocument()
  })

  it("收起新增 / 編輯 / 刪除與拖拉手把", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={frozen} />)
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "編輯第 1 題" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "刪除第 1 題" })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("拖曳調整第 1 題順序")).not.toBeInTheDocument()
  })

  it("問卷名稱仍可編輯——名稱不影響已填答資料的意義", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={frozen} />)
    expect(screen.getByLabelText(/問卷名稱/)).toBeEnabled()
  })
})

describe("SurveyDialog：唯讀（非擁有者）", () => {
  it("標題為檢視且無任何編輯入口", () => {
    render(<SurveyDialog {...BASE_PROPS} survey={makeSurvey()} readOnly />)
    expect(screen.getByText("檢視課後問卷")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "新增題目" })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/問卷名稱/)).toBeDisabled()
  })
})
