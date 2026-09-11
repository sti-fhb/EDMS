import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs"
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ReopenCourseDialog } from "./ReopenCourseDialog"
import { renderWithProviders } from "../../test/renderWithProviders"
import type { PublishBlocker } from "./surveySchemas"

/**
 * 再開課視窗（US11 AC 8 / #288）。
 *
 * ⚠️ 時間比較規則本身在 `reopenSchedule.test.ts`——`DateTimePicker` 在 jsdom 中無法以
 * `userEvent` 可靠填值（本專案沒有任何測試做到過），故此處只驗「視窗把驗證結果呈現
 * 出來」與缺漏清單，不重複驗規則的各邊界。
 */
/**
 * ⚠️ 必須自備 `LocalizationProvider`：`DateTimePicker` 少了它會在 render 當下丟
 * 「Can not find the date and time pickers localization context」。正式路徑由
 * `CourseEditorPage` 在頁面層提供（本視窗不自帶，以免同頁疊兩個 provider），
 * 故單獨渲染此視窗時要在測試裡補上。
 */
function renderDialog(props: Partial<Parameters<typeof ReopenCourseDialog>[0]> = {}) {
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  renderWithProviders(
    <LocalizationProvider dateAdapter={AdapterDayjs}>
      <ReopenCourseDialog
        open
        submitting={false}
        blockers={[]}
        quizNames={{}}
        onSubmit={onSubmit}
        onClose={onClose}
        {...props}
      />
    </LocalizationProvider>,
  )
  return { onSubmit, onClose }
}

describe("ET02 再開課視窗", () => {
  it("兩個時間皆不預填，且說明進度與邀請碼會保留", () => {
    // FR-ET-US11-09「強制重新設定」——預填舊值會讓教師直接按確認、把課程再開成一段
    // 已經過去的期間，後端擋下但那是一次不必要且難以理解的往返。
    renderDialog()
    expect(screen.getByText(/再開課須重新設定一組新的開放起訖時間/)).toBeInTheDocument()
    expect(screen.getByText(/原邀請碼沿用、恢復有效/)).toBeInTheDocument()
  })

  it("未填時間直接按確認 → 兩欄都標示必填，且不送出", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()

    await user.click(screen.getByRole("button", { name: "確認再開課" }))

    expect(await screen.findByText("請選擇新的開放起始時間")).toBeInTheDocument()
    expect(screen.getByText("請選擇新的開放訖止時間")).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("取消時清掉已填內容與錯誤訊息", async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog()
    await user.click(screen.getByRole("button", { name: "確認再開課" }))
    expect(await screen.findByText("請選擇新的開放起始時間")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "取消" }))

    expect(onClose).toHaveBeenCalled()
  })

  it("檢核未通過時列出缺漏並附「去哪裡修」的導引", () => {
    // 再開課會重跑發布六項檢核（SA Q2 裁示 A）：關閉期間教師端仍可編輯，課程可能已
    // 不符發布條件。缺漏文案與導引沿用 PublishDialog 的 BLOCKER_HINT，兩處同一份檢核。
    const blockers: PublishBlocker[] = [
      { code: "NO_MATERIAL", message: "課程至少須有 1 份教材", target_id: null },
      { code: "QUIZ_NO_QUESTION", message: "測驗至少須有 1 題", target_id: 7 },
    ]
    renderDialog({ blockers, quizNames: { 7: "第一次小考" } })

    expect(screen.getByText(/課程目前不符發布條件，無法再開課/)).toBeInTheDocument()
    expect(screen.getByText("課程至少須有 1 份教材")).toBeInTheDocument()
    expect(screen.getByText("請於章節內新增至少 1 份教材")).toBeInTheDocument()
    // 測驗名稱由前端自課程詳細對照補上——後端只回 target_id
    expect(screen.getByText('測驗至少須有 1 題（測驗「第一次小考」）')).toBeInTheDocument()
  })

  it("缺漏未補齊時送出鈕仍可按", async () => {
    // 教師可能在另一個分頁把內容補好了，再按一次就重跑檢核。disable 會讓他只能關掉
    // 視窗重開，而畫面上沒有任何提示說「補好之後要重開視窗」。
    renderDialog({ blockers: [{ code: "NO_TAG", message: "課程至少須掛 1 個標籤", target_id: null }] })
    expect(screen.getByRole("button", { name: "確認再開課" })).toBeEnabled()
  })

  it("送出中時停用送出鈕（防連點造出兩次再開課）", () => {
    renderDialog({ submitting: true })
    expect(screen.getByRole("button", { name: "確認再開課" })).toBeDisabled()
  })
})
