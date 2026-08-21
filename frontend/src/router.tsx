import { createBrowserRouter, Navigate } from "react-router-dom"

import { ActivateAccountPage } from "./auth/ActivateAccountPage"
import { ResetPasswordPage } from "./auth/ResetPasswordPage"
import { VerifyEmailChangePage } from "./auth/VerifyEmailChangePage"
import { VerifyEmailPage } from "./auth/VerifyEmailPage"
import { AppShell } from "./layouts/AppShell"
import { RootLayout } from "./layouts/RootLayout"
import { DmChangeLogPage } from "./dm/changelog/DmChangeLogPage"
import { DmDetailPage } from "./dm/detail/DmDetailPage"
import { DmEditorPage } from "./dm/editor/DmEditorPage"
import { DmKpiPage } from "./dm/kpi/DmKpiPage"
import { DmLibraryPage } from "./dm/library/DmLibraryPage"
import { DmObsoletePage } from "./dm/obsolete/DmObsoletePage"
import { DmPersonalPage } from "./dm/personal/DmPersonalPage"
import { DmReviewPage } from "./dm/review/DmReviewPage"
import { AuditPage } from "./dp/audit/AuditPage"
import { TemplatesPage } from "./dp/notify/TemplatesPage"
import { ParamsPage } from "./dp/params/ParamsPage"
import { RolesPage } from "./dp/roles/RolesPage"
import { SchedulePage } from "./dp/schedules/SchedulePage"
import { ProfilePage } from "./dp/user/ProfilePage"
import { UsersPage } from "./dp/users/UsersPage"
import { WelcomePage } from "./home/WelcomePage"

export const router = createBrowserRouter([
  // 密碼重設頁：信中連結落點，免登入（置於 RootLayout 外，不被登入 overlay 覆蓋）
  { path: "reset-password", element: <ResetPasswordPage /> },
  // 註冊驗證落點頁（US2 #56）：信中連結落點，免登入，同置 RootLayout 外
  { path: "verify-email", element: <VerifyEmailPage /> },
  // 帳號啟用落點頁（US4 #67）：管理者邀請信連結落點，免登入，同置 RootLayout 外
  { path: "activate", element: <ActivateAccountPage /> },
  // Email 變更驗證落點頁（US8）：信中連結落點，免登入，同置 RootLayout 外
  { path: "verify-email-change", element: <VerifyEmailChangePage /> },
  {
    element: <RootLayout />,
    children: [
      {
        // 統一 shell（#89 導覽重構）：登入後所有頁共用頂列 + 常駐側欄
        element: <AppShell />,
        children: [
          // 主頁＝中性歡迎頁（取代原 portal 卡片頁）
          { index: true, element: <WelcomePage /> },
          // 個人資料維護（US8）：所有登入者可用，改入統一 shell（側欄常駐）
          { path: "profile", element: <ProfilePage /> },
          {
            path: "dp",
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
          {
            // 文件管理模組殼（#127 Foundation）：路由骨架，各頁為 StubPage，功能於對應 US issue 填實
            path: "dm",
            children: [
              // DM 儀表板（US7 / DM00）改為中性歡迎頁之依權限 widget（#89），不設獨立 /dm 落地頁；
              // 裸 /dm 導向文件庫（既有行為）
              { index: true, element: <Navigate to="/dm/library" replace /> },
              { path: "library", element: <DmLibraryPage /> },
              // US5 新增 / 編輯（靜態 new 置於動態 :docId 前，避免被誤捕）
              { path: "documents/new", element: <DmEditorPage /> },
              { path: "documents/:docId/edit", element: <DmEditorPage /> },
              { path: "documents/:docId", element: <DmDetailPage /> },
              { path: "review", element: <DmReviewPage /> },
              { path: "me", element: <DmPersonalPage /> },
              { path: "obsolete", element: <DmObsoletePage /> },
              { path: "change-log", element: <DmChangeLogPage /> },
              { path: "kpi", element: <DmKpiPage /> },
            ],
          },
        ],
      },
    ],
  },
])
