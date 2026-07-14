import { createBrowserRouter, Navigate } from "react-router-dom"

import { DpLayout } from "./layouts/DpLayout"
import { RootLayout } from "./layouts/RootLayout"
import { AuditPage } from "./dp/audit/AuditPage"
import { TemplatesPage } from "./dp/notify/TemplatesPage"
import { ParamsPage } from "./dp/params/ParamsPage"
import { RolesPage } from "./dp/roles/RolesPage"
import { SchedulePage } from "./dp/schedules/SchedulePage"
import { UsersPage } from "./dp/users/UsersPage"
import { PortalPage } from "./portal/PortalPage"

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <Navigate to="/portal" replace /> },
      { path: "portal", element: <PortalPage /> },
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
