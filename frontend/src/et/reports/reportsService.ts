import { http } from "../../services/http"

/**
 * 週報逐學員明細之下載（T164 / US14 / #325）。
 *
 * 以 blob 取回而非讓瀏覽器直接導向後端 URL：後端端點需要 `Authorization` header，
 * 而瀏覽器導覽帶不了它——直接開連結只會拿到 401。http 攔截器會補上 token
 * （同 `dp/audit/auditService.exportCsv` 與 `dm/kpi/kpiService.exportCsvBlob`）。
 */
export const reportsApi = {
  /** `courseId` 省略時為呼叫者權限範圍內的全部開放中課程（週報信中的連結即為此形式）。 */
  weeklyCsvBlob: async (courseId?: number): Promise<Blob> => {
    const { data } = await http.get<Blob>("/et/reports/weekly/students.csv", {
      params: courseId === undefined ? undefined : { course_id: courseId },
      responseType: "blob",
    })
    return data
  },
}

/** 取回 CSV 並觸發瀏覽器下載。 */
export async function downloadWeeklyCsv(courseId?: number): Promise<void> {
  const blob = await reportsApi.weeklyCsvBlob(courseId)
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "et-weekly-students.csv"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
