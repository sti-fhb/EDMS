import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { PublishDialog } from "./PublishDialog"

const BASE_PROPS = {
  open: true,
  checking: false,
  publishing: false,
  blockers: [],
  result: null,
  quizNames: {},
  onPublish: () => {},
  onClose: () => {},
}

describe("PublishDialog：檢核中", () => {
  it("顯示檢核中且發布鈕停用", () => {
    render(<PublishDialog {...BASE_PROPS} checking />)
    expect(screen.getByText("檢核中…")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "確認發布" })).toBeDisabled()
  })
})

describe("PublishDialog：條件已滿足", () => {
  it("發布鈕可按", () => {
    render(<PublishDialog {...BASE_PROPS} />)
    expect(screen.getByText("發布條件皆已滿足。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "確認發布" })).toBeEnabled()
  })

  it("按下發布會呼叫 onPublish", async () => {
    const onPublish = vi.fn()
    render(<PublishDialog {...BASE_PROPS} onPublish={onPublish} />)
    await userEvent.click(screen.getByRole("button", { name: "確認發布" }))
    expect(onPublish).toHaveBeenCalledOnce()
  })

  it("發布進行中停用按鈕，避免重複送出", () => {
    render(<PublishDialog {...BASE_PROPS} publishing />)
    expect(screen.getByRole("button", { name: "確認發布" })).toBeDisabled()
  })
})

describe("PublishDialog：有缺漏", () => {
  const blockers = [
    { code: "NO_TAG", message: "課程至少須掛 1 個受訓單位標籤", target_id: null },
    { code: "NO_SCHEDULE", message: "課程起訖時間須填寫完整", target_id: null },
  ]

  it("全部缺漏都列出——只報第一項會讓教師修一次再被擋一次", () => {
    render(<PublishDialog {...BASE_PROPS} blockers={blockers} />)
    expect(screen.getByText("課程至少須掛 1 個受訓單位標籤")).toBeInTheDocument()
    expect(screen.getByText("課程起訖時間須填寫完整")).toBeInTheDocument()
  })

  it("每條缺漏附上「去哪裡修」的導引", () => {
    render(<PublishDialog {...BASE_PROPS} blockers={blockers} />)
    expect(screen.getByText("請於「基本資料」選擇受訓單位標籤")).toBeInTheDocument()
    expect(screen.getByText("請於「基本資料」填寫課程起訖時間")).toBeInTheDocument()
  })

  it("有缺漏時發布鈕停用", () => {
    render(<PublishDialog {...BASE_PROPS} blockers={blockers} />)
    expect(screen.getByRole("button", { name: "確認發布" })).toBeDisabled()
  })

  it("測驗類缺漏補上測驗名稱", () => {
    // 後端只回 target_id——名稱是使用者輸入，回摻進錯誤訊息等於原樣吐回。
    // 頁面本來就有課程詳細，自行對照即可。
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[{ code: "QUIZ_NO_QUESTION", message: "測驗至少須有 1 題", target_id: 42 }]}
        quizNames={{ 42: "第一章小考" }}
      />,
    )
    expect(screen.getByText("測驗至少須有 1 題（測驗「第一章小考」）")).toBeInTheDocument()
  })

  it("對照不到名稱時仍顯示原訊息，不顯示 undefined", () => {
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[{ code: "QUIZ_NO_QUESTION", message: "測驗至少須有 1 題", target_id: 999 }]}
        quizNames={{}}
      />,
    )
    expect(screen.getByText("測驗至少須有 1 題")).toBeInTheDocument()
  })

  it("同一代碼的多個測驗各自成列", () => {
    // key 若只用 code，兩筆 QUIZ_POINTS 會撞——React 會警告且可能漏render 其中一筆。
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 1 },
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 2 },
        ]}
        quizNames={{ 1: "小考A", 2: "小考B" }}
      />,
    )
    expect(screen.getByText("測驗各題配分總和須等於 100（測驗「小考A」）")).toBeInTheDocument()
    expect(screen.getByText("測驗各題配分總和須等於 100（測驗「小考B」）")).toBeInTheDocument()
  })
})

describe("PublishDialog：發布成功", () => {
  const result = { course_id: 1, status: "PUBLISHED", invitation_code: "01234567", version: 1 }

  it("顯示邀請碼與不可變更的說明", () => {
    render(<PublishDialog {...BASE_PROPS} result={result} />)
    expect(screen.getByText("01234567")).toBeInTheDocument()
    expect(screen.getByText("課程邀請碼（發布後永久不可變更）")).toBeInTheDocument()
  })

  it("成功後不再顯示發布鈕", () => {
    render(<PublishDialog {...BASE_PROPS} result={result} />)
    expect(screen.queryByRole("button", { name: "確認發布" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "關閉" })).toBeInTheDocument()
  })

  it("成功態即使帶著舊的 blockers 也不顯示缺漏", () => {
    // 發布成功後 blockers 可能還留在 state 裡；成功態必須完全覆蓋，
    // 否則會同時看到「已發布」與「條件未滿足」兩種相反的訊息。
    render(
      <PublishDialog
        {...BASE_PROPS}
        result={result}
        blockers={[{ code: "NO_TAG", message: "課程至少須掛 1 個受訓單位標籤", target_id: null }]}
      />,
    )
    expect(screen.queryByText("課程至少須掛 1 個受訓單位標籤")).not.toBeInTheDocument()
  })
})
