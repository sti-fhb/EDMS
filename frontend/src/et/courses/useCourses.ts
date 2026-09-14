import { useQuery } from "@tanstack/react-query"

import { coursesApi } from "./coursesService"
import { QUERY_KEYS } from "../../constants/queryKeys"

/**
 * 當前使用者於 ET 課程之操作能力（#306 供編輯器路由守衛；CourseListPage 亦用同一 queryKey）。
 *
 * 回「能力」而非「角色」——JWT 刻意不含角色、`module-summary` 只回布林，前端無從自行推導
 * （見 `app/et/course/schemas.py` 之 `Capabilities`）。
 *
 * `enabled` 供守衛在「無任一 ET 角色」時關閉，避免非 ET 使用者觸發 403。
 */
export function useEtCourseCapabilities(enabled = true) {
  return useQuery({
    queryKey: QUERY_KEYS.etCourses.capabilities(),
    queryFn: coursesApi.getCapabilities,
    enabled,
  })
}
