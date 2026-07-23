import { createBrowserRouter, Navigate } from "react-router-dom"

import { ActivateAccountPage } from "./auth/ActivateAccountPage"
import { ResetPasswordPage } from "./auth/ResetPasswordPage"
import { VerifyEmailPage } from "./auth/VerifyEmailPage"
import { DpLayout } from "./layouts/DpLayout"
import { PortalLayout } from "./layouts/PortalLayout"
import { RootLayout } from "./layouts/RootLayout"
import { AuditPage } from "./dp/audit/AuditPage"
import { TemplatesPage } from "./dp/notify/TemplatesPage"
import { ParamsPage } from "./dp/params/ParamsPage"
import { RolesPage } from "./dp/roles/RolesPage"
import { SchedulePage } from "./dp/schedules/SchedulePage"
import { UsersPage } from "./dp/users/UsersPage"
import { PortalPage } from "./portal/PortalPage"

export const router = createBrowserRouter([
  // 密碼重設頁：信中連結落點，免登入（置於 RootLayout 外，不被登入 overlay 覆蓋）
  { path: "reset-password", element: <ResetPasswordPage /> },
  // 註冊驗證落點頁（US2 #56）：信中連結落點，免登入，同置 RootLayout 外
  { path: "verify-email", element: <VerifyEmailPage /> },
  // 帳號啟用落點頁（US4 #67）：管理者邀請信連結落點，免登入，同置 RootLayout 外
  { path: "activate", element: <ActivateAccountPage /> },
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <Navigate to="/portal" replace /> },
      {
        path: "portal",
        element: <PortalLayout />,
        children: [{ index: true, element: <PortalPage /> }],
      },
      {
        path: "dp",
        element: <DpLayout />,
        children: [
          { index: true, element: <Navigate to="/dp/users" replace /> },
          { path: "users", element: <UsersPage /> },
          { path: "params", element: <ParamsPage /> },
          { path: "templates", element: <TemplatesPage /> },
          { path: "roles", element: <RolesPage /> },
          { path: "audit", element: <AuditPage /> },
          { path: "schedule", element: <SchedulePage /> },
        ],
      },
    ],
  },
])
