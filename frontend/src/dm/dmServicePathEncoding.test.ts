// ⛔ 本檔**不可**改用 node 測試環境，理由同 `dm/library/libraryService.test.ts` 檔首那段：
// 本檔經 app 的 axios 發真實請求（由 MSW 攔截）以驗出站 URL，而 node 環境沒有 document
// origin，`http` 的相對 baseURL `/api` 會讓 axios 改走 http adapter 並以 Invalid URL 失敗。
//
// 本檔跨 `dm/editor` 與 `dm/detail` 兩個子模組，故放在 `src/dm/` 層而非任一子目錄下——
// 它驗的是**整個 DM 模組的一致性**，拆進各自目錄會讓「有沒有補齊」變得看不出來（#624）。
import type { JsonBodyType } from "msw"
import { HttpResponse, http } from "msw"
import { describe, expect, it } from "vitest"

import { detailApi } from "./detail/detailService"
import { editorApi } from "./editor/editorService"
import { server } from "../test/server"

/**
 * DM 模組路徑參數編碼（#624）。
 *
 * ## 為什麼要編碼
 *
 * React Router 對路徑參數做 `decodeURIComponent`，所以 `/dm/documents/..%2F..%2Fx/edit`
 * 會得到 `docId === "../../x"`。未編碼直接內插進樣板字串時，瀏覽器解析相對路徑後，請求會
 * 落到**別的同源 API**，帶的是受害者自己的憑證。
 *
 * 影響有限（需誘使受害者點特製連結），但本專案在 ET 已有相反慣例並附註解
 * （`et/students/studentsService.ts`：「值目前來自後端回應故安全，但這是零成本的防禦」），
 * DM 應對齊。
 *
 * ## 只編碼字串參數
 *
 * ET 的既有寫法是 `${courseId}/students/${encodeURIComponent(userId)}/quizzes/${quizId}`
 * ——**數字參數不編碼**。DM 比照：`docId` 是 `string` 故編碼；`reviewId` / `versionId`
 * 是 `number`，TypeScript 保證它們內插後不可能含 `/`，編碼是 no-op 只會製造雜訊。
 */
const TRAVERSAL_ID = "../../evil"

/** 攔下任一出站請求並回出其 URL（path 比對用）。 */
function captureUrl(pattern: string, body: JsonBodyType = {}) {
  const seen: { url: string } = { url: "" }
  server.use(
    http.all(pattern, ({ request }) => {
      seen.url = new URL(request.url).pathname
      return HttpResponse.json(body)
    }),
  )
  return seen
}

describe("DM service 路徑參數編碼（#624）", () => {
  it("editorApi.getDocTags：docId 含 ../ 時已編碼，請求不會跳出預期路徑", async () => {
    const seen = captureUrl("/api/dm/editor/documents/*", { audience_pairs: [], retrieval_ids: [], tag_names: {} })
    await editorApi.getDocTags(TRAVERSAL_ID)

    // 正向錨點：請求確實送出了（否則下方否定斷言恆真）
    expect(seen.url).not.toBe("")
    // `..%2F..%2Fevil` 而非 `../../evil`
    expect(seen.url).toContain(encodeURIComponent(TRAVERSAL_ID))
    expect(seen.url).toBe(`/api/dm/editor/documents/${encodeURIComponent(TRAVERSAL_ID)}/tags`)
  })

  it("detailApi.getDetail：同上（整個 DM 模組一致，不是只補被點名的那處）", async () => {
    const seen = captureUrl("/api/dm/documents/*")
    await detailApi.getDetail(TRAVERSAL_ID)

    expect(seen.url).not.toBe("")
    expect(seen.url).toBe(`/api/dm/documents/${encodeURIComponent(TRAVERSAL_ID)}`)
  })

  it("detailApi.getVersions：docId 在路徑中段時亦編碼", async () => {
    const seen = captureUrl("/api/dm/documents/*/versions", [])
    await detailApi.getVersions(TRAVERSAL_ID)

    expect(seen.url).not.toBe("")
    expect(seen.url).toBe(`/api/dm/documents/${encodeURIComponent(TRAVERSAL_ID)}/versions`)
  })
})
