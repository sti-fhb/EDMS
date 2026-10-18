import { describe, expect, it } from "vitest"

import { resetLabel, withRoundDividers, type RoundBoundary } from "./attemptRounds"

const attempts = [1, 2, 3, 4].map((no) => ({ attempt_no: no }))
const reset = (after: number, kind: RoundBoundary["kind"]): RoundBoundary => ({
  after_attempt_no: after,
  kind,
  executed_at: "2026-10-14T09:00:00Z",
})

describe("withRoundDividers（#709）", () => {
  it("沒有重置時原樣列出、皆非前一輪", () => {
    const rows = withRoundDividers(attempts, [])
    expect(rows.map((r) => r.type)).toEqual(["attempt", "attempt", "attempt", "attempt"])
    expect(rows.every((r) => r.type === "attempt" && !r.previous)).toBe(true)
  })

  it("分隔列插在起點之後的第一筆之前，起點之前為前一輪", () => {
    const rows = withRoundDividers(attempts, [reset(1, "RETEST")])
    expect(rows.map((r) => (r.type === "divider" ? "|" : String(r.attempt.attempt_no)))).toEqual([
      "1",
      "|",
      "2",
      "3",
      "4",
    ])
    const previous = rows.filter((r) => r.type === "attempt" && r.previous)
    expect(previous.map((r) => r.type === "attempt" && r.attempt.attempt_no)).toEqual([1])
  })

  it("只有「要求重測」之前才是前一輪——重置重考次數只插分隔列", () => {
    // 重置重考次數不影響最高分，灰掉會讓學員以為那幾次不算（#709 Q1）
    const rows = withRoundDividers(attempts, [reset(1, "RETEST"), reset(3, "RETRY")])
    expect(rows.filter((r) => r.type === "divider")).toHaveLength(2)
    const current = rows.filter((r) => r.type === "attempt" && !r.previous)
    expect(current.map((r) => r.type === "attempt" && r.attempt.attempt_no)).toEqual([2, 3, 4])
  })

  it("重置重考次數後未再考就要求重測（兩者同一起點）：起點之前全是前一輪", () => {
    // `ordered` 依 after_attempt_no 排序，同值時 RETEST 仍要生效
    const rows = withRoundDividers(attempts, [reset(2, "RETRY"), reset(2, "RETEST")])
    expect(rows.map((r) => (r.type === "divider" ? "|" : String(r.attempt.attempt_no)))).toEqual(["1", "2", "|", "|", "3", "4"])
    const previous = rows.filter((r) => r.type === "attempt" && r.previous)
    expect(previous.map((r) => r.type === "attempt" && r.attempt.attempt_no)).toEqual([1, 2])
  })

  it("只有重置重考次數或舊資料時，沒有任何一筆是前一輪", () => {
    const rows = withRoundDividers(attempts, [reset(1, null), reset(2, "RETRY")])
    expect(rows.filter((r) => r.type === "divider")).toHaveLength(2)
    expect(rows.filter((r) => r.type === "attempt" && r.previous)).toHaveLength(0)
  })

  it("重置之後尚無作答：分隔列仍出現在最後", () => {
    // 看得出「已要求重測、尚未重考」——少了它，畫面與重測前一模一樣
    const rows = withRoundDividers([{ attempt_no: 1 }], [reset(1, "RETEST")])
    expect(rows.map((r) => r.type)).toEqual(["attempt", "divider"])
  })
})

describe("resetLabel（#709）", () => {
  it("依原因給不同文字，舊資料為中性文字", () => {
    expect(resetLabel("RETEST")).toBe("教師要求重測（測驗內容已更新）")
    expect(resetLabel("RETRY")).toBe("重考次數已重置")
    expect(resetLabel(null)).toBe("重新計算起點")
  })
})
