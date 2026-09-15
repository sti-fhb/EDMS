import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { EtWeeklyReportDownloadPage } from "./WeeklyReportDownloadPage"

/**
 * 週報明細下載中繼頁（T164 / #325）。
 *
 * 這一頁的行為幾乎全在「進場即自動下載」與「參數怎麼傳給 service」，故直接 mock
 * service 驗呼叫；CSV 內容與授權由後端 integration 覆蓋（`test_et_weekly_csv.py`）。
 */
const downloadWeeklyCsv = vi.hoisted(() => vi.fn())
vi.mock("./reportsService", () => ({ downloadWeeklyCsv }))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/et/reports/weekly" element={<EtWeeklyReportDownloadPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe("EtWeeklyReportDownloadPage", () => {
  beforeEach(() => {
    downloadWeeklyCsv.mockReset()
    downloadWeeklyCsv.mockResolvedValue(undefined)
  })

  it("進場即自動下載，未帶課程時不傳參數", async () => {
    renderAt("/et/reports/weekly")

    await waitFor(() => expect(downloadWeeklyCsv).toHaveBeenCalledWith(undefined))
    expect(await screen.findByText(/明細已開始下載/)).toBeInTheDocument()
  })

  it("帶 courseId 時轉為數字傳入", async () => {
    renderAt("/et/reports/weekly?courseId=42")

    await waitFor(() => expect(downloadWeeklyCsv).toHaveBeenCalledWith(42))
  })

  it("自動下載只觸發一次", async () => {
    // StrictMode 於開發期會重跑 effect，不擋會連下兩次檔案
    renderAt("/et/reports/weekly")

    await waitFor(() => expect(downloadWeeklyCsv).toHaveBeenCalled())
    expect(downloadWeeklyCsv).toHaveBeenCalledTimes(1)
  })

  it("courseId 非整數時顯示錯誤且不呼叫後端", async () => {
    renderAt("/et/reports/weekly?courseId=abc")

    expect(await screen.findByText(/課程代碼無效/)).toBeInTheDocument()
    expect(downloadWeeklyCsv).not.toHaveBeenCalled()
  })

  it("下載失敗顯示錯誤訊息並可重試", async () => {
    downloadWeeklyCsv.mockRejectedValueOnce(new Error("伺服器忙碌"))
    renderAt("/et/reports/weekly")

    expect(await screen.findByText("伺服器忙碌")).toBeInTheDocument()

    downloadWeeklyCsv.mockResolvedValueOnce(undefined)
    await userEvent.click(screen.getByRole("button", { name: "重新下載" }))

    expect(await screen.findByText(/明細已開始下載/)).toBeInTheDocument()
    expect(downloadWeeklyCsv).toHaveBeenCalledTimes(2)
  })
})
