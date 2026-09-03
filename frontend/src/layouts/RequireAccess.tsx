import type { ReactNode } from "react"
import { Outlet } from "react-router-dom"

import { AccessDenied } from "../components/AccessDenied"
import { useDmAdminAccess } from "../dm/access/useDmAdminAccess"
import { useDmReviewerAccess } from "../dm/access/useDmReviewerAccess"
import { usePersonalAccess } from "../dm/personal/usePersonal"
import type { ModuleKey } from "./navItems"
import { useModuleSummary } from "./useModuleSummary"

/**
 * 路由層權限守衛（#250）。
 *
 * 與側欄可見性同源——用同一批 query，因此共用 TanStack Query 快取、不會多打 request。
 * 兩者職責不同：側欄決定「看不看得到入口」，本守衛決定「直接輸入網址時看到什麼」。
 * 沒有守衛時各頁表現不一致：`/dp/users` 停在載入中、`/dm/review` 渲染簽核畫面空殼、
 * `/dm/change-log` 彈一則 Snackbar——全都像壞掉而非「你沒有權限」。
 *
 * 一律 **fail-closed**：query 未載入前不渲染子頁（回 null），避免先閃出內容再被收回；
 * 判定失敗即視為無權限。權限邊界仍在後端，本層只是把已被擋下的結果講清楚。
 *
 * 每個守衛都同時支援兩種用法：包住單頁（`children`）或作為 route 的 `element`（`Outlet`）。
 */

function Gate({ allowed, pending, children }: { allowed: boolean; pending: boolean; children?: ReactNode }) {
  if (pending) return null
  if (!allowed) return <AccessDenied />
  return children ? <>{children}</> : <Outlet />
}

/** 需具 ET 或 DM 任一模組管理者（DP 後台六項功能之操作者定義）。 */
export function RequireModuleAdmin({ children }: { children?: ReactNode }) {
  const { data: summary, isPending } = useModuleSummary()
  return (
    <Gate allowed={Boolean(summary && (summary.et.is_admin || summary.dm.is_admin))} pending={isPending || !summary}>
      {children}
    </Gate>
  )
}

/** 需具該模組任一角色（模組群組門檻，對齊側欄 `requiresModule`）。 */
export function RequireModule({ module, children }: { module: ModuleKey; children?: ReactNode }) {
  const { data: summary, isPending } = useModuleSummary()
  const hasRole = module === "DM" ? summary?.dm.has_role : summary?.et.has_role
  return <Gate allowed={Boolean(hasRole)} pending={isPending || !summary}>{children}</Gate>
}

/** 需具 DM_REVIEWER（簽核中心；僅具 DM_ADMIN 者亦不放行，SA #250 Q3=A）。 */
export function RequireDmReviewer({ children }: { children?: ReactNode }) {
  const { data: summary } = useModuleSummary()
  const hasDmRole = summary?.dm.has_role ?? false
  // 僅在具任一 DM 角色時查詢（避免非 DM 使用者觸發 403 噪音），比照側欄
  const { data: access, isPending } = useDmReviewerAccess(hasDmRole)
  if (!summary) return null
  if (!hasDmRole) return <AccessDenied />
  return <Gate allowed={access?.can_access ?? false} pending={isPending || !access}>{children}</Gate>
}

/** 需具 DM_ADMIN（已廢止文件查詢 / 變更歷程查詢 / 閱讀統計 KPI；service 層 `DM_AUTH_003`）。 */
export function RequireDmAdmin({ children }: { children?: ReactNode }) {
  const { data: summary } = useModuleSummary()
  const hasDmRole = summary?.dm.has_role ?? false
  const { data: access, isPending } = useDmAdminAccess(hasDmRole)
  if (!summary) return null
  if (!hasDmRole) return <AccessDenied />
  return <Gate allowed={access?.can_access ?? false} pending={isPending || !access}>{children}</Gate>
}

/** 需具編輯者或審核者（個人專區，US9 FR-004）。 */
export function RequireDmPersonal({ children }: { children?: ReactNode }) {
  const { data: summary } = useModuleSummary()
  const hasDmRole = summary?.dm.has_role ?? false
  const { data: access, isPending } = usePersonalAccess(hasDmRole)
  if (!summary) return null
  if (!hasDmRole) return <AccessDenied />
  return <Gate allowed={access?.can_access ?? false} pending={isPending || !access}>{children}</Gate>
}