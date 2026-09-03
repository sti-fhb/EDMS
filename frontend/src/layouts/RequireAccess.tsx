import type { ReactNode } from "react"
import { Outlet } from "react-router-dom"

import { AccessDenied } from "../components/AccessDenied"
import { useDmReviewerAccess } from "../dm/access/useDmReviewerAccess"
import { useModuleSummary } from "./useModuleSummary"

/**
 * 路由層權限守衛（#250）。
 *
 * 與側欄可見性同源（同一批 query，因此共用快取、不會多打 request），用途不同：側欄決定
 * 「看不看得到入口」，本守衛決定「直接輸入網址時看到什麼」。沒有它，非管理者開
 * `/dp/users` 會停在載入中（後端 403 但頁面無錯誤處理），開 `/dm/review` 甚至會渲染出
 * 簽核畫面的空殼——兩者都像壞掉，而非「你沒有權限」。
 *
 * fail-closed：query 未載入前不渲染子頁（回 null），避免先閃出內容再被收回。
 * 權限邊界仍在後端，本層只是把已被擋下的結果講清楚。
 */

/** 需具 ET 或 DM 任一模組管理者（DP 後台六項功能之操作者定義）。 */
export function RequireModuleAdmin({ children }: { children?: ReactNode }) {
  const { data: summary, isPending } = useModuleSummary()
  if (isPending || !summary) return null
  if (!summary.et.is_admin && !summary.dm.is_admin) {
    return <AccessDenied reason="系統管理者後台僅限教育訓練或文件管理的模組管理者使用。" />
  }
  return children ? <>{children}</> : <Outlet />
}

/** 需具 DM_REVIEWER（簽核中心入口；僅具 DM_ADMIN 者亦不放行，SA #250 Q3=A）。 */
export function RequireDmReviewer({ children }: { children?: ReactNode }) {
  const { data: summary } = useModuleSummary()
  const hasDmRole = summary?.dm.has_role ?? false
  // 僅在具任一 DM 角色時查詢（避免非 DM 使用者觸發 403 噪音），比照側欄
  const { data: access, isPending } = useDmReviewerAccess(hasDmRole)
  if (!summary) return null
  if (!hasDmRole) {
    return <AccessDenied reason="簽核中心僅限文件管理模組的審核者使用。" />
  }
  if (isPending || !access) return null
  if (!access.can_access) {
    return <AccessDenied reason="簽核中心僅限具「審核者」角色者使用；文件管理者如需簽核，請另行指派審核者角色。" />
  }
  return children ? <>{children}</> : <Outlet />
}
