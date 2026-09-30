import { describe, expect, it } from "vitest"

import { courseOptionsEmptyReason } from "./courseOptionsState"

/**
 * ET10 課程下拉的空狀態判定（#439）。
 *
 * ## 為何這組是純函式測試而不是頁面測試
 *
 * 其中一種情形是「**先成功、之後背景刷新失敗**」。在頁面測試裡要驗到它，得真的觸發一次
 * 背景刷新（window focus / invalidate），而那在 jsdom 裡既脆弱又容易寫成「看起來有跑」。
 * 把判定抽成純函式之後，那個情境變成一組參數。
 *
 * ⭐ 這正是 code review 揪出來的缺陷所在：原本餵的是 `isError`，而它在背景刷新失敗時
 * 也是 true。**「一開始就失敗」的測試驗不出這件事**——那時 `isError` 與 `isLoadingError`
 * 同時為真，兩種寫法都會通過。
 */
describe("courseOptionsEmptyReason", () => {
  it("還在載入時不說任何成因——那時還不知道", () => {
    expect(courseOptionsEmptyReason({ isLoadingError: false, isPending: true }, 0)).toBeNull()
  })

  it("從未成功載入過就失敗 → failed", () => {
    expect(courseOptionsEmptyReason({ isLoadingError: true, isPending: false }, 0)).toBe("failed")
  })

  it("載完且真的沒有選項 → none", () => {
    expect(courseOptionsEmptyReason({ isLoadingError: false, isPending: false }, 0)).toBe("none")
  })

  it("有選項時不是空狀態", () => {
    expect(courseOptionsEmptyReason({ isLoadingError: false, isPending: false }, 2)).toBeNull()
  })

  it("🔴 先成功、之後背景刷新失敗時，下拉仍可用（不得宣稱載入失敗）", () => {
    // TanStack Query v5 在這個情形下 `isError` **是 true**、而 `data` 仍保有上次的內容
    //（`query-core` 的 `isRefetchError: isError && hasData`）。若判定吃的是 `isError`，
    // 教師選好課程之後只要撞一次限流（本端點與 `/approvals/search` 共用 60/分分桶），
    // 下拉就會被停用並顯示「載入失敗」——**而他手上那份選項完全可用**。
    //
    // 參數形狀即是那個情境：`isLoadingError=false`（曾經成功過）、有選項在手。
    expect(courseOptionsEmptyReason({ isLoadingError: false, isPending: false }, 2)).toBeNull()
  })

  it("⚠️ 曾成功載到空清單、之後刷新失敗時，維持最後已知的事實（none）而非改口說失敗", () => {
    // 上一次成功的結果就是「沒有課程」，那是**已知的事實**；這次刷新失敗不推翻它。
    expect(courseOptionsEmptyReason({ isLoadingError: false, isPending: false }, 0)).toBe("none")
  })
})
