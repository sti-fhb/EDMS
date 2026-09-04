import { createBrowserRouter, Navigate } from "react-router-dom"

import { ActivateAccountPage } from "./auth/ActivateAccountPage"
import { ResetPasswordPage } from "./auth/ResetPasswordPage"
import { VerifyEmailChangePage } from "./auth/VerifyEmailChangePage"
import { VerifyEmailPage } from "./auth/VerifyEmailPage"
import { AppShell } from "./layouts/AppShell"
import {
  RequireDmAdmin,
  RequireDmPersonal,
  RequireDmReviewer,
  RequireModule,
  RequireModuleAdmin,
} from "./layouts/RequireAccess"
import { RootLayout } from "./layouts/RootLayout"
import { DmChangeLogPage } from "./dm/changelog/DmChangeLogPage"
import { DmDetailPage } from "./dm/detail/DmDetailPage"
import { DmEditorPage } from "./dm/editor/DmEditorPage"
import { DmKpiPage } from "./dm/kpi/DmKpiPage"
import { DmLibraryPage } from "./dm/library/DmLibraryPage"
import { DmObsoletePage } from "./dm/obsolete/DmObsoletePage"
import { DmPersonalPage } from "./dm/personal/DmPersonalPage"
import { DmReviewPage } from "./dm/review/DmReviewPage"
import { EtApprovalQueryPage } from "./et/approval/ApprovalQueryPage"
import { EtCourseEditorPage } from "./et/courses/CourseEditorPage"
import { EtCourseListPage } from "./et/courses/CourseListPage"
import { EtHomeRedirect } from "./et/EtHomeRedirect"
import { EtInviteLandingPage } from "./et/invite/InviteLandingPage"
import { EtLearnPage } from "./et/learn/LearnPage"
import { EtMyCoursesPage } from "./et/my/MyCoursesPage"
import { EtStudentsPage } from "./et/students/StudentsPage"
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
            // #250：整段 /dp 掛模組管理者守衛——直接輸入網址者顯示無權限畫面，
            // 而非停在載入中（後端已回 403，但各頁無錯誤畫面）
            path: "dp",
            element: <RequireModuleAdmin />,
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
            // #250：整段 /dm 需任一 DM 角色；細項再各自掛閘（下方）。
            // 直接輸入網址而無權限者一律顯示「無權限存取此功能」，不再各頁自行處理 403。
            path: "dm",
            element: <RequireModule module="DM" />,
            children: [
              // DM 儀表板（US7 / DM00）改為中性歡迎頁之依權限 widget（#89），不設獨立 /dm 落地頁；
              // 裸 /dm 導向文件庫（既有行為）
              { index: true, element: <Navigate to="/dm/library" replace /> },
              { path: "library", element: <DmLibraryPage /> },
              // US5 新增 / 編輯（靜態 new 置於動態 :docId 前，避免被誤捕）
              { path: "documents/new", element: <DmEditorPage /> },
              { path: "documents/:docId/edit", element: <DmEditorPage /> },
              { path: "documents/:docId", element: <DmDetailPage /> },
              // #250：限 DM_REVIEWER——原本直接輸入網址會渲染出簽核畫面空殼
              {
                path: "review",
                element: (
                  <RequireDmReviewer>
                    <DmReviewPage />
                  </RequireDmReviewer>
                ),
              },
              // 個人專區：需編輯者或審核者（US9 FR-004）
              {
                path: "me",
                element: (
                  <RequireDmPersonal>
                    <DmPersonalPage />
                  </RequireDmPersonal>
                ),
              },
              // 需 DM_ADMIN（service 層 DM_AUTH_003）
              {
                path: "obsolete",
                element: (
                  <RequireDmAdmin>
                    <DmObsoletePage />
                  </RequireDmAdmin>
                ),
              },
              // 需 DM_ADMIN（service 層 DM_AUTH_003）
              {
                path: "change-log",
                element: (
                  <RequireDmAdmin>
                    <DmChangeLogPage />
                  </RequireDmAdmin>
                ),
              },
              // 需 DM_ADMIN（service 層 DM_AUTH_003）
              {
                path: "kpi",
                element: (
                  <RequireDmAdmin>
                    <DmKpiPage />
                  </RequireDmAdmin>
                ),
              },
            ],
          },
          {
            // 教育訓練模組殼（#202）：側欄 4 項對齊 wireframe ET 側欄；
            // 課程列表以外目前為 StubPage，功能於對應 US issue 填實。
            // #250：整段 /et 需任一 ET 角色（對齊側欄 requiresModule=ET）。
            // 課程編輯等頁另需 TEACHER / ADMIN，但目前無對應的 access 端點可供前端判定，
            // 故僅做群組層守衛，細粒度仍由後端 require_et_roles 把關（見 PR 說明之後續項）。
            path: "et",
            element: <RequireModule module="ET" />,
            children: [
              // 依能力分流（#247 AC 1）：純學員 → ET04 我的課程；具建課能力者 → 課程列表
              { index: true, element: <EtHomeRedirect /> },
              { path: "courses", element: <EtCourseListPage /> },
              // ET02 為課程列表之子頁、非側欄項目；靜態 new 置於動態 :courseId 前避免被誤捕
              { path: "courses/new", element: <EtCourseEditorPage /> },
              { path: "courses/:courseId", element: <EtCourseEditorPage /> },
              { path: "students", element: <EtStudentsPage /> },
              { path: "approvals", element: <EtApprovalQueryPage /> },
              { path: "my-courses", element: <EtMyCoursesPage /> },
              // ET05 章節學習（#255）：學員自我的課程卡片進入，非側欄項目
              { path: "courses/:courseId/learn", element: <EtLearnPage /> },
              // Email 邀請連結落點（#273）：置於登入殼**之內**——加入課程需要登入者身分，
              // 未登入時由 LoginOverlay 擋在前面，登入後 token 仍在網址上、流程自然接續。
              { path: "invite", element: <EtInviteLandingPage /> },
            ],
          },
        ],
      },
    ],
  },
])
