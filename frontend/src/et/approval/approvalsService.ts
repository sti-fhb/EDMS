import { http } from "../../services/http"
import type { ApprovalCourseOption, ApprovalQueryParams, ApprovalQueryRow, MyApprovalRow } from "./schemas"
import type { PagedResult } from "../../hooks/usePagedQuery"

/**
 * ET10 核可查詢 API（US17 / #385）——**唯讀**，不含任何核可 / 撤銷動作（那些在 US16）。
 *
 * 兩支端點**刻意分開**而非同一支加參數：授權模型、回應欄位與資料範圍三者都不同。
 * `mine` 不帶任何識別參數——對象由後端從 token 取得，前端沒有可傳錯的東西。
 */
export const approvalsApi = {
  /**
   * 教師 / 管理者依學員姓名查詢。可見範圍由後端依 SA Q1 裁示 C 分流。
   *
   * 🔴 **`POST` 且條件走 body，不是 query string**（#391）。`keyword` 必定是姓名或 Email（皆為個資），是一個人的
   * 姓名，而網址會被 nginx `error_log` 與 Cloudflare 的請求日誌記下來（前者格式不可
   * 自訂、後者不在本系統掌控範圍）；body 不會。
   *
   * ⛔ 不要改回 `http.get(url, { params })`——那等於把姓名放回網址，而且**畫面行為
   * 完全正常**，不會有任何東西看起來壞掉。後端的 `test_姓名走query_string不被接受`
   * 是那道紅線。
   *
   * 語意仍是讀取：用 POST 的唯一理由是上述的日誌問題，後端不寫入也不留稽核。
   */
  search: async (params: ApprovalQueryParams): Promise<PagedResult<ApprovalQueryRow>> => {
    const { data } = await http.post<PagedResult<ApprovalQueryRow>>("/et/approvals/search", params)
    return data
  },

  /**
   * ET10 課程篩選下拉的選項——**有核可紀錄的**課程（#439）。教師只取得自己開設的課。
   *
   * ⛔ 不要改用 `coursesApi.list()`：那支的 `scope=all` 只給「已發布且期間未過」，
   * 而核可紀錄絕大多數落在**已結束**的課程上——管理者會發現最相關的課全部不在下拉裡，
   * 且畫面不會說明任何事；`scope=mine` 則對管理者是空的。
   */
  listFilterCourses: async (): Promise<ApprovalCourseOption[]> => {
    const { data } = await http.get<ApprovalCourseOption[]>("/et/approvals/filter-courses")
    return data
  },

  /** 學員自查：自己已通過（有效未撤銷）的課程。 */
  mine: async (params: { page?: number; limit?: number }): Promise<PagedResult<MyApprovalRow>> => {
    const { data } = await http.get<PagedResult<MyApprovalRow>>("/et/approvals/mine", { params })
    return data
  },
}
