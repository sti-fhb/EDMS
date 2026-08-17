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
