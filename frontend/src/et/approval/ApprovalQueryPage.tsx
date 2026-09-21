import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useModuleSummary } from "../../layouts/useModuleSummary"
import { coursesApi } from "../courses/coursesService"
import { StudentApprovalList } from "./StudentApprovalList"
import { TeacherApprovalQuery } from "./TeacherApprovalQuery"

/**
 * ET10 核可查詢（US17 / #385）——依角色分流的單一畫面。
 *
 * ## 為何側欄項目不掛角色旗標
 *
 * `navItems.ts` 的「核可查詢」對**任一 ET 角色**都顯示，路由也**沒有守衛**（對比隔壁
 * `/et/students` 包了 `RequireEtCourseManager`）。那是刻意的：兩種角色都要進得來，
 * 看到的東西不同。
 *
 * ⚠️ 代價是 `FR-ET-US17-04`「不以前端隱藏為唯一防線」在這裡不是提醒而是**唯一的實作
 * 路徑**——本元件的分流只決定「畫面長什麼樣」，資料邊界完全由後端的兩支端點負責。
 * 純學員即使直接打教師端 API 也會被 403 擋下。
 *
 * ## 兼具兩種角色時顯示教師視角
 *
 * 他自己的已通過課程在 ET04「我的課程」看得到；兩張表塞同一頁只會讓畫面變長，而他
 * 來這一頁的目的是查學員。
 *
 * ⛔ **本畫面不提供核可證明 / 結業證書的下載或列印**（`FR-ET-US17-05`，2026-07-17
 * 客戶確認不需要）。新增匯出入口前請先確認客戶改了需求。
 */
export function EtApprovalQueryPage() {
  const { data: capabilities, isPending } = useQuery({
    queryKey: QUERY_KEYS.etCourses.capabilities(),
    queryFn: coursesApi.getCapabilities,
  })
  // ⚠️ 管理者身分**不能從 `capabilities` 推**：`can_create_course` 是「具教師角色」，
  // 同時具教師與管理者身分的人它也是 true，`!can_create_course` 會把他誤判成非管理者
  // 而顯示一句不適用的範圍提示。`module-summary` 的 `et.is_admin` 與後端
  // `authz.is_admin()` 同源，是唯一正確的來源。
  const { data: summary } = useModuleSummary()

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        核可查詢
      </Typography>
      {isPending ? (
        <Typography variant="body2" color="text.secondary">
          載入中…
        </Typography>
      ) : capabilities?.can_manage_courses ? (
        <TeacherApprovalQuery isAdmin={summary?.et.is_admin ?? false} />
      ) : (
        <StudentApprovalList />
      )}
    </Box>
  )
}
