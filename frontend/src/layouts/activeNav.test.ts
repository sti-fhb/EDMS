import { describe, expect, it } from "vitest"

import { navFrom, resolveActiveNavPath } from "./activeNav"
import { NAV_GROUPS } from "./navItems"

const NAV_PATHS = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.path))

describe("resolveActiveNavPath", () => {
  it("功能項本身：回自己", () => {
    expect(resolveActiveNavPath("/dm/library")).toBe("/dm/library")
    expect(resolveActiveNavPath("/et/my-courses")).toBe("/et/my-courses")
    expect(resolveActiveNavPath("/dp/users")).toBe("/dp/users")
  })

  it("🔴 ET06 章節學習頁高亮 ET03 我的課程，不是 ET01 課程列表", () => {
    // 路徑前綴是 `/et/courses`，純前綴相符會停在 ET01——而學員是從 ET03 點卡片進來的，
    // 且純學員看不到 ET01（`requiresEtManage`），結果整個側欄沒有一項亮著。
    expect(resolveActiveNavPath("/et/courses/7/learn")).toBe("/et/my-courses")
    expect(resolveActiveNavPath("/et/courses/7/learn")).not.toBe("/et/courses")
  })

  it("ET06 課後問卷與測驗作答 / 成績同樣高亮 ET03 我的課程", () => {
    expect(resolveActiveNavPath("/et/courses/7/survey")).toBe("/et/my-courses")
    expect(resolveActiveNavPath("/et/attempts/31")).toBe("/et/my-courses")
    expect(resolveActiveNavPath("/et/attempts/31/result")).toBe("/et/my-courses")
  })

  it("ET05 課程建立 / 編輯仍高亮 ET01 課程列表（前綴相符的既有行為未被破壞）", () => {
    expect(resolveActiveNavPath("/et/courses/new")).toBe("/et/courses")
    expect(resolveActiveNavPath("/et/courses/7")).toBe("/et/courses")
  })

  it("DM07 文件詳細頁無來源時高亮 DM01 文件庫", () => {
    expect(resolveActiveNavPath("/dm/documents/DM-TRAINING-000015")).toBe("/dm/library")
  })

  it("🔴 DM07 文件詳細頁自 DM03 進入時高亮 DM03，不是預設的 DM01", () => {
    const { state } = navFrom("/dm/obsolete")
    expect(resolveActiveNavPath("/dm/documents/DM-TRAINING-000015", state)).toBe("/dm/obsolete")
  })

  it("來源為 DM01 時高亮 DM01（與預設同值，但走的是來源分支）", () => {
    const { state } = navFrom("/dm/library")
    expect(resolveActiveNavPath("/dm/documents/5", state)).toBe("/dm/library")
  })

  it("ET06 自 ET01「全部課程」預覽進入時高亮 ET01（教師預覽不該落在「我的課程」）", () => {
    const { state } = navFrom("/et/courses")
    expect(resolveActiveNavPath("/et/courses/7/learn", state)).toBe("/et/courses")
  })

  it("來源不是側欄功能項時忽略（竄改 / 功能項已改名），退回靜態對應", () => {
    expect(resolveActiveNavPath("/dm/documents/5", { __navFrom: "/dm/not-a-nav-item" })).toBe("/dm/library")
    expect(resolveActiveNavPath("/dm/documents/5", { __navFrom: 123 })).toBe("/dm/library")
    expect(resolveActiveNavPath("/dm/documents/5", "not-an-object")).toBe("/dm/library")
    expect(resolveActiveNavPath("/dm/documents/5", null)).toBe("/dm/library")
  })

  it("無對應功能項的頁面回 undefined（側欄不亮任何一項）", () => {
    expect(resolveActiveNavPath("/")).toBeUndefined()
    expect(resolveActiveNavPath("/profile")).toBeUndefined()
    // DM08 文件新增 / 編輯：本次未處理，維持既有的「不亮」
    expect(resolveActiveNavPath("/dm/documents/new")).toBeUndefined()
    expect(resolveActiveNavPath("/dm/documents/5/edit")).toBeUndefined()
  })

  it("子頁對應到的一定是真實存在的側欄功能項（擋住功能項改路徑後對應變成死路徑）", () => {
    const subpages = [
      "/et/courses/7/learn",
      "/et/courses/7/survey",
      "/et/attempts/31",
      "/dm/documents/5",
      "/et/courses/new",
    ]
    for (const pathname of subpages) {
      expect(NAV_PATHS).toContain(resolveActiveNavPath(pathname))
    }
  })
})
