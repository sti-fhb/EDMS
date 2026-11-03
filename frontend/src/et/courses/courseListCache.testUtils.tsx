// #901：「回到課程列表時，先畫出快取裡的舊列表」的共用測試輔助。
//
// ⚠️ 只在**重抓變慢**時才看得到這個缺陷——網路正常時舊資料不到半秒就被換掉，
// 用正常速度的 handler 測，修改前也會通過（實機重現見 #901 留言）。所以這裡把
// 「回到列表後的那次重抓」卡住，直到測試呼叫 `release()` 才回應。

import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor } from "@testing-library/react"
import { HttpResponse, http } from "msw"
import { expect } from "vitest"

import { EtCourseListPage } from "./CourseListPage"
import type { CourseCard } from "./schemas"
import { renderWithProviders } from "../../test/renderWithProviders"
import { server } from "../../test/server"

/** 課程卡片 fixture——只有名稱與 id 會影響斷言，其餘取最普通的草稿值。 */
export function courseCard(courseId: number, courseName: string): CourseCard {
  return {
    course_id: courseId,
    course_name: courseName,
    status: "DRAFT",
    open_start_at: null,
    open_end_at: null,
    owner_id: "U1",
    owner_name: "王教師",
    owner_is_disabled: false,
    audiences: [],
    chapter_count: 0,
    student_count: 0,
    is_owner: true,
    is_closed: false,
  }
}

function pageOf(cards: CourseCard[]) {
  return { data: cards, meta: { total: cards.length, page: 1, limit: 12, total_pages: 1 } }
}

/**
 * 課程列表第一次查詢立即回 `first`；之後的查詢卡住，`release()` 後才回 `later`。
 *
 * `listCalls()` 讓測試確認「回到列表後的重抓已經發出」再斷言——不等這一下就斷言，
 * 列表頁可能還沒掛載完成，「看不到舊課程」會因為畫面還沒畫而假綠。
 *
 * ⚠️ **必須在測試覆寫課程詳情（`/api/et/courses/:courseId`）之後呼叫。** 該覆寫會把列表頁
 * 的 `capabilities` / `filter-tags` / `filter-owners` 也吃掉（`:courseId` 匹配任何一段），
 * 拿到課程物件而非陣列、列表頁當場炸掉。這裡重新註冊這三支字面路徑，後註冊者優先。
 */
export function mockSlowListRefetch(first: CourseCard[], later: CourseCard[]) {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let calls = 0
  server.use(
    http.get("/api/et/courses/capabilities", () =>
      HttpResponse.json({
        can_create_course: true,
        can_manage_courses: true,
        can_track_students: true,
        can_learn: true,
      }),
    ),
    http.get("/api/et/courses/filter-tags", () => HttpResponse.json([])),
    http.get("/api/et/courses/filter-owners", () => HttpResponse.json([])),
    http.get("/api/et/courses", async () => {
      calls += 1
      if (calls === 1) return HttpResponse.json(pageOf(first))
      await gate
      return HttpResponse.json(pageOf(later))
    }),
  )
  return { release, listCalls: () => calls }
}

/** 列表頁與編輯頁共用的 QueryClient——兩次 render 之間要留住快取，才測得到「讀到舊快取」。 */
export function newSharedQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

/** 渲染課程列表並等第一次查詢的卡片出現（快取就此存進 `queryClient`）。 */
export async function renderListAndCache(queryClient: QueryClient, visibleName: string) {
  const view = renderWithProviders(<EtCourseListPage />, undefined, undefined, queryClient)
  await screen.findByText(visibleName)
  return view
}

/** 回到列表：重新渲染列表頁，並等「回到列表後的重抓」發出。 */
export async function returnToList(queryClient: QueryClient, listCalls: () => number) {
  const view = renderWithProviders(<EtCourseListPage />, undefined, undefined, queryClient)
  await waitFor(() => expect(listCalls()).toBe(2))
  return view
}
