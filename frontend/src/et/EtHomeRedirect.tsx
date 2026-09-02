import { useQuery } from "@tanstack/react-query"
import { Navigate } from "react-router-dom"

import { coursesApi } from "./courses/coursesService"
import { QUERY_KEYS } from "../constants/queryKeys"

/**
 * 裸 `/et` 的角色導向（AC 1：**學員**登入後預設首頁為 ET04 我的課程）。
 *
 * 在 #247 之前這裡是無條件 `Navigate to="/et/courses"`——那是教師的課程列表，
 * 純學員進去只會看到一句「你不能建立課程」。ET04 補上之後才有正確的目的地。
 *
 * ## 為何以「能力」而非角色判斷
 *
 * 前端無從自行推導 ET 角色（JWT 刻意不含角色、`module-summary` 只回布林），故沿用
 * #202 已建立的作法：後端回**能力**（`can_create_course`），前端據此分流。這樣授權
 * 判斷只有一個來源。
 *
 * 具教師 / 管理者能力者仍導向課程列表——他們同時也是學員（學員角色人人有），
 * 若一律送到 ET04，教師每次進 ET 都要多點一次才能到自己的課程。
 *
 * 查詢未完成前 `render` 為 `null`：這是一個轉址節點，閃一下 spinner 再跳走比留白
 * 更晃眼。查詢失敗（能力取不到）時保守導向 ET04——那是每個 ET 使用者都進得去的
 * 頁面，而課程列表對純學員是死路。
 */
export function EtHomeRedirect() {
  const { data, isPending } = useQuery({
    queryKey: QUERY_KEYS.etCourses.capabilities(),
    queryFn: coursesApi.getCapabilities,
  })

  if (isPending) return null
  return <Navigate to={data?.can_create_course ? "/et/courses" : "/et/my-courses"} replace />
}
