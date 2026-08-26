import { describe, expect, it } from "vitest"

import { moveId } from "./chapterOrder"

describe("章節順序計算（moveId）", () => {
  it("往後移：把第一個移到第三個位置", () => {
    expect(moveId([11, 12, 13], 11, 13)).toEqual([12, 13, 11])
  })

  it("往前移：把最後一個移到第一個位置", () => {
    expect(moveId([11, 12, 13], 13, 11)).toEqual([13, 11, 12])
  })

  it("相鄰交換", () => {
    expect(moveId([11, 12], 11, 12)).toEqual([12, 11])
  })

  it("回傳完整陣列（後端契約要求完整順序而非相對移動）", () => {
    const ids = [11, 12, 13, 14]
    const next = moveId(ids, 12, 14)
    expect(next).toHaveLength(ids.length)
    expect([...(next ?? [])].sort()).toEqual([...ids].sort())
  })

  it("id 不在清單中時回 null，不產生錯誤順序", () => {
    expect(moveId([11, 12], 99, 12)).toBeNull()
    expect(moveId([11, 12], 11, 99)).toBeNull()
  })

  it("不變動原陣列（immutability）", () => {
    const ids = [11, 12, 13]
    moveId(ids, 11, 13)
    expect(ids).toEqual([11, 12, 13])
  })
})
