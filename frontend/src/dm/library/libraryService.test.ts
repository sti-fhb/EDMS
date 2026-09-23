// ⛔ 本檔**不可**改用 node 測試環境（#376 實測，2026-09-23）。
//
// ⚠️ 本段刻意**不寫出**那個檔首指示的字面 token：vitest 以正規式掃描檔首註解，
// 寫出來就會真的生效——連「不要用它」的警告也一樣。初版就這樣把自己變成了它
// 所警告的東西，本檔因而紅在 `TypeError: Invalid URL`。
//
// #376 的「11 支純邏輯測試改 node 環境」清單把本檔列進去了，判準是「不碰 DOM」
// ——本檔確實不碰，但那個判準**不完整**。真正的條件還要加一項：
// **不經 app 的 axios 發請求**。
//
// 本檔正是經 `libraryApi.search()` 發真實請求（由 MSW 攔截）驗參數序列化。node 環境
// 沒有 document origin，而 `http` 的 baseURL 是相對路徑 `/api`，axios 會改走 http
// adapter 並以 `TypeError: Invalid URL` 失敗——實測如此，不是推論。
//
// 留下這段是為了讓下一個照那份清單做的人不必重跑一次同樣的失敗。
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { libraryApi } from "./libraryService"
import { EMPTY_LIBRARY_FILTERS } from "./schemas"
import { server } from "../../test/server"

describe("libraryApi.search 參數序列化", () => {
  it("tag_ids 以重複格式送出（tag_ids=6&tag_ids=7），對齊 FastAPI list[int]=Query()", async () => {
    let captured: string[] = []
    server.use(
      http.get("/api/dm/library/documents", ({ request }) => {
        captured = new URL(request.url).searchParams.getAll("tag_ids")
        return HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } })
      }),
    )
    await libraryApi.search({ ...EMPTY_LIBRARY_FILTERS, tagIds: [6, 7], page: 1, limit: 20 })
    // 非 tag_ids[]=6（帶括號會使 getAll("tag_ids") 為空）、非單一 "6,7"
    expect(captured).toEqual(["6", "7"])
  })
})
