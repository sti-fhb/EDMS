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
  quizNames: {}, chapterNames: {}, itemChapterNames: {},
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
      chapterNames={{}}
      />,
    )
    expect(screen.getByText("測驗至少須有 1 題")).toBeInTheDocument()
  })

  it("同一代碼的多個測驗合併為一列，對象並列（#412）", () => {
    // 2026-09-23 手測回報：原本兩筆 QUIZ_POINTS 各自成列，教師得自己認出「這兩條其實
    // 是同一件事」；缺漏種類一多還得捲動。
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
    expect(screen.getByText("測驗各題配分總和須等於 100（測驗「小考A」、測驗「小考B」）")).toBeInTheDocument()
    // 合併後「去哪裡修」只出現一次——重複的提示是逐條列最吵的部分
    expect(screen.getAllByText("請調整該測驗各題配分，使總和為 100")).toHaveLength(1)
  })

  it("只有一個對象時不多出頓號或空括號（#412）", () => {
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[{ code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 1 }]}
        quizNames={{ 1: "小考A" }}
      />,
    )
    expect(screen.getByText("測驗各題配分總和須等於 100（測驗「小考A」）")).toBeInTheDocument()
  })

  it("一組中只有部分對象查得到名稱時，只列查得到的（#412）", () => {
    // `BLOCKER_TARGET_KIND` 的 fail-closed 承諾延伸到合併：查不到的整個略過，
    // 不印出一組空引號。
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 1 },
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 999 },
        ]}
        quizNames={{ 1: "小考A" }}
      />,
    )
    expect(screen.getByText("測驗各題配分總和須等於 100（測驗「小考A」）")).toBeInTheDocument()
  })

  it("多種缺漏混合時，種類順序維持後端的回傳順序（#412）", () => {
    // `evaluate_publish` 的順序是「課程層 → 章節層 → 測驗層 → 文件層」，前端分組
    // 不得打亂它——`groupBlockers` 用 Map 保序即為此。
    render(
      <PublishDialog
        {...BASE_PROPS}
        blockers={[
          { code: "NO_TAG", message: "課程至少須掛 1 個受訓單位標籤", target_id: null },
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 1 },
          { code: "QUIZ_POINTS", message: "測驗各題配分總和須等於 100", target_id: 2 },
          { code: "OBSOLETE_DOC", message: "請先移除已廢止文件之引用", target_id: null },
        ]}
        quizNames={{ 1: "小考A", 2: "小考B" }}
      />,
    )
    const rows = screen.getAllByRole("listitem").map((li) => li.textContent ?? "")
    expect(rows).toHaveLength(3)
    expect(rows[0]).toContain("受訓單位標籤")
    expect(rows[1]).toContain("測驗「小考A」、測驗「小考B」")
    expect(rows[2]).toContain("已廢止文件")
  })
})

describe("PublishDialog：發布成功", () => {
  const result = { course_id: 1, status: "PUBLISHED", invitation_code: "01234567", version: 1, invited_count: 0 }

  it("顯示邀請碼，且不帶「發布後永久不可變更」的括號說明（#359 第 2 項）", () => {
    render(<PublishDialog {...BASE_PROPS} result={result} />)
    expect(screen.getByText("01234567")).toBeInTheDocument()
    expect(screen.getByText("課程邀請碼")).toBeInTheDocument()
    // 負向斷言：AC 要的是「不再顯示」。上面那條用 getByText 精確比對，理論上括號版
    // 不會通過——但那是**副作用**而非它在驗的事；文案再改一次（例如改成「邀請碼」）
    // 時它照樣綠，括號卻可能被加回來。故把「不可出現」單獨寫出來。
    //
    // 規則本身沒有消失，只是改由 ET02 手冊承載（「邀請碼於發布當下產生，之後沿用同
    // 一組」）——畫面不寫、手冊寫「看不出來的規則」是刻意的分工。
    expect(screen.queryByText(/永久不可變更/)).not.toBeInTheDocument()
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
