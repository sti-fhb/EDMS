import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CourseCard } from "./CourseCard"
import type { CourseCard as CourseCardData } from "./schemas"
import { renderWithProviders } from "../../test/renderWithProviders"

function makeCourse(overrides: Partial<CourseCardData> = {}): CourseCardData {
  return {
    course_id: 11,
    course_name: "採血作業新進人員訓練",
    status: "PUBLISHED",
    // ⚠️ 刻意不帶 `Z`：不帶時區的 ISO 由 JS 視為**本地時間**，斷言才不會隨執行機器的
    // 時區飄動（專案未固定 TZ）。
    open_start_at: "2026-04-15T09:00:00",
    open_end_at: "2026-07-31T17:30:00",
    owner_id: "t01",
    owner_name: "陳大華",
    tags: [{ tag_id: 1, tag_name: "護理師", is_active: true }],
    chapter_count: 5,
    student_count: 28,
    is_owner: true,
    is_closed: false,
    ...overrides,
  }
}

describe("ET01 課程卡片", () => {
  it("整張卡是可聚焦的按鈕，鍵盤使用者到得了", async () => {
    // 用 CardActionArea 而非在 Card 掛 onClick 的理由就在這；若改回 div+onClick
    // 這條會紅（#296 的 <tr> 正是不可聚焦才要另補 IconButton）
    const user = userEvent.setup()
    const onOpen = vi.fn()
    renderWithProviders(<CourseCard course={makeCourse()} onOpen={onOpen} />)

    const card = screen.getByRole("button", { name: /採血作業新進人員訓練/ })
    await user.tab()

    expect(card).toHaveFocus()
    await user.keyboard("{Enter}")
    expect(onOpen).toHaveBeenCalledWith(11)
  })

  it("他人課程才有「檢視」標籤；自己的改標「（您）」", () => {
    const { unmount } = renderWithProviders(<CourseCard course={makeCourse()} onOpen={vi.fn()} />)
    expect(screen.queryByText("檢視")).not.toBeInTheDocument()
    expect(screen.getByText(/陳大華（您）/)).toBeInTheDocument()
    unmount()

    renderWithProviders(
      <CourseCard course={makeCourse({ is_owner: false, owner_name: "林助教" })} onOpen={vi.fn()} />,
    )
    expect(screen.getByText("檢視")).toBeInTheDocument()
    expect(screen.queryByText(/（您）/)).not.toBeInTheDocument()
  })

  it.each([
    ["DRAFT", "草稿"],
    ["PUBLISHED", "已發布"],
    ["CLOSED", "已關閉"],
  ] as const)("狀態 %s 顯示為「%s」", (status, label) => {
    renderWithProviders(<CourseCard course={makeCourse({ status })} onOpen={vi.fn()} />)

    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it("期間已過的課程標成「已關閉」，不因 status 仍是 PUBLISHED 就標「已發布」", () => {
    // 到期自動轉 CLOSED 屬未實作的 ET-16，所以期間已過時 status 仍是 PUBLISHED。
    // 照 status 標會寫成「已發布」，但學員早已進不去——卡片會騙人。
    renderWithProviders(
      <CourseCard course={makeCourse({ status: "PUBLISHED", is_closed: true })} onOpen={vi.fn()} />,
    )

    expect(screen.getByText("已關閉")).toBeInTheDocument()
    expect(screen.queryByText("已發布")).not.toBeInTheDocument()
  })

  it("草稿不因 is_closed 被改標成「已關閉」", () => {
    renderWithProviders(<CourseCard course={makeCourse({ status: "DRAFT", is_closed: true })} onOpen={vi.fn()} />)

    expect(screen.getByText("草稿")).toBeInTheDocument()
    expect(screen.queryByText("已關閉")).not.toBeInTheDocument()
  })

  it("開課期間起訖齊全時兩端都顯示", () => {
    renderWithProviders(<CourseCard course={makeCourse()} onOpen={vi.fn()} />)

    expect(screen.getByText("2026-04-15 09:00 ～ 2026-07-31 17:30")).toBeInTheDocument()
  })

  it("草稿常見的「起訖都沒填」顯示破折號，不是 Invalid Date", () => {
    // 起訖為選填，草稿階段兩端常是 null；直接丟給 new Date() 會印出 `Invalid Date`
    renderWithProviders(
      <CourseCard course={makeCourse({ open_start_at: null, open_end_at: null })} onOpen={vi.fn()} />,
    )

    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument()
  })

  it("只有結束日時前段以破折號補位，不讓使用者誤讀成開始日", () => {
    renderWithProviders(
      <CourseCard course={makeCourse({ open_start_at: null })} onOpen={vi.fn()} />,
    )

    expect(screen.getByText("— ～ 2026-07-31 17:30")).toBeInTheDocument()
  })

  it("兩個聚合值都標示單位，避免卡片上出現兩個裸數字", () => {
    renderWithProviders(<CourseCard course={makeCourse()} onOpen={vi.fn()} />)

    expect(screen.getByText("5 章節")).toBeInTheDocument()
    expect(screen.getByText("28 位學員")).toBeInTheDocument()
  })

  it("沒有標籤時不渲染空的標籤列", () => {
    renderWithProviders(<CourseCard course={makeCourse({ tags: [] })} onOpen={vi.fn()} />)

    expect(screen.queryByText("護理師")).not.toBeInTheDocument()
  })
})
