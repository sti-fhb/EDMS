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

  it("下載失敗顯示後端訊息並可重試", async () => {
    // `responseType: "blob"` 的請求失敗時 `response.data` 是 **Blob**——用一般的錯誤解析
    // 只會拿到 axios 的英文狀態碼，把後端說得清楚的那句蓋掉。此處以真實形狀構造。
    downloadWeeklyCsv.mockRejectedValueOnce({
      response: {
        status: 403,
        data: new Blob([JSON.stringify({ error_code: "ET_COURSE_002", error_message: "僅課程擁有者可下載" })]),
      },
    })
    renderAt("/et/reports/weekly")

    expect(await screen.findByText("僅課程擁有者可下載")).toBeInTheDocument()

    downloadWeeklyCsv.mockResolvedValueOnce(undefined)
    await userEvent.click(screen.getByRole("button", { name: "重新下載" }))

    expect(await screen.findByText(/明細已開始下載/)).toBeInTheDocument()
    expect(downloadWeeklyCsv).toHaveBeenCalledTimes(2)
  })

  it("courseId 為空值時視為無效，不送出 course_id=0", async () => {
    // `Number("")` 是 0 且通過 `Number.isInteger`——寬鬆的驗證會讓這種壞連結送到後端吃 422
    renderAt("/et/reports/weekly?courseId=")

    expect(await screen.findByText(/課程代碼無效/)).toBeInTheDocument()
    expect(downloadWeeklyCsv).not.toHaveBeenCalled()
  })
})
