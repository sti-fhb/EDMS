import { http, HttpResponse } from "msw"
import { setupServer } from "msw/node"

/**
 * MSW mock server：於網路層攔截 API（axios 真實發出 request）。
 * 各測試可用 server.use(...) 覆寫單一情境（如錯誤 / must_change）；預設為 happy path。
 */
export const handlers = [
  http.post("/api/login", () =>
    HttpResponse.json({ access_token: "test-access-token", must_change_pwd: false }),
  ),
  http.post("/api/register", () =>
    HttpResponse.json({ message: "驗證信已寄至您的信箱，請於 30 分鐘內點連結完成驗證" }, { status: 202 }),
  ),
  http.post("/api/verify-email", () => HttpResponse.json({ message: "帳號已啟用，請以新帳號登入" })),
  http.post("/api/resend-verification", () =>
    HttpResponse.json({ message: "若該 Email 有待驗證的註冊，驗證信將重新寄出，請於 30 分鐘內完成驗證" }),
  ),
  http.post("/api/forgot-password", () =>
    HttpResponse.json({ message: "若該 Email 已註冊，密碼重設信將寄至信箱，請於 30 分鐘內完成重設" }),
  ),
  http.post("/api/reset-password", () => HttpResponse.json({ message: "密碼已更新，請以新密碼登入" })),
  http.post("/api/dp/user/renew", () => HttpResponse.json({ access_token: "renewed-token" })),
  http.post("/api/dp/user/logout", () => new HttpResponse(null, { status: 204 })),
  http.get("/api/dp/user/module-summary", () =>
    HttpResponse.json({ et: { has_role: true }, dm: { has_role: false } }),
  ),
  // US4 使用者管理（預設 happy path；含啟用中 / 已鎖定 / 已停用三態供 UI 驗證）
  http.get("/api/dp/users", () =>
    HttpResponse.json({
      data: [
        {
          user_id: "u-active",
          user_name: "陳大華",
          email: "active@edms.local",
          status: "ACTIVE",
          locked_until: null,
          last_login_date: "2026-07-06T09:12:00Z",
          created_date: "2026-05-01T00:00:00Z",
        },
        {
          user_id: "u-locked",
          user_name: "林小美",
          email: "locked@edms.local",
          status: "ACTIVE",
          locked_until: "2099-01-01T00:00:00Z",
          last_login_date: null,
          created_date: "2026-06-02T00:00:00Z",
        },
        {
          user_id: "u-disabled",
          user_name: "張志豪",
          email: "disabled@edms.local",
          status: "DISABLED",
          locked_until: null,
          last_login_date: null,
          created_date: "2026-06-20T00:00:00Z",
        },
      ],
      meta: { total: 3, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  // 建立帳號＝寄邀請（#67）：後端 202 + message，不回 UserRow
  http.post("/api/dp/users", () =>
    HttpResponse.json({ message: "邀請信已寄出，使用者需經連結設定密碼後啟用" }, { status: 202 }),
  ),
  // 待啟用邀請清單（ADMIN_INVITE）：含有效中 / 已逾期兩態供 UI 驗證
  http.get("/api/dp/users/invites", () =>
    HttpResponse.json({
      data: [
        {
          res_id: "inv-valid",
          user_name: "周雅婷",
          email: "tina@edms.local",
          created_date: "2026-07-06T10:20:00Z",
          expires_date: "2099-01-01T00:00:00Z",
        },
        {
          res_id: "inv-expired",
          user_name: "李國豪",
          email: "kuo@edms.local",
          created_date: "2026-07-05T16:02:00Z",
          expires_date: "2020-01-01T00:00:00Z",
        },
      ],
      meta: { total: 2, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  http.post("/api/dp/users/invites/:id/resend", () =>
    HttpResponse.json({ message: "邀請信已重寄" }, { status: 202 }),
  ),
  http.delete("/api/dp/users/invites/:id", () => new HttpResponse(null, { status: 204 })),
  http.post("/api/activate-account", () => HttpResponse.json({ message: "帳號已啟用，請以新密碼登入" })),
  http.patch("/api/dp/users/:id/status", () =>
    HttpResponse.json({
      user_id: "u-active",
      user_name: "陳大華",
      email: "active@edms.local",
      status: "DISABLED",
      locked_until: null,
      last_login_date: null,
      created_date: "2026-05-01T00:00:00Z",
    }),
  ),
  http.patch("/api/dp/users/:id/unlock", () =>
    HttpResponse.json({
      user_id: "u-locked",
      user_name: "林小美",
      email: "locked@edms.local",
      status: "ACTIVE",
      locked_until: null,
      last_login_date: null,
      created_date: "2026-06-02T00:00:00Z",
    }),
  ),
  http.patch("/api/dp/users/:id", () =>
    HttpResponse.json({
      user_id: "u-active",
      user_name: "陳大華改",
      email: "active2@edms.local",
      status: "ACTIVE",
      locked_until: null,
      last_login_date: null,
      created_date: "2026-05-01T00:00:00Z",
    }),
  ),
]

export const server = setupServer(...handlers)
