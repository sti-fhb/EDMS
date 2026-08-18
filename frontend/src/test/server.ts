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
  http.get("/api/version", () => HttpResponse.json({ version: "1.0.0-test" })),
  // 入口頁 / 側欄模組摘要（預設具 DM 權限；個別測試以 server.use 覆蓋）
  http.get("/api/dp/user/module-summary", () =>
    HttpResponse.json({ et: { has_role: true }, dm: { has_role: true } }),
  ),
  // US3 文件庫與檢索（dm-library）：預設兩筆（含手冊）+ 選項 + 可新增；個別測試以 server.use 覆蓋
  http.get("/api/dm/library/documents", () =>
    HttpResponse.json({
      data: [
        {
          doc_id: "DM-SOP-000001",
          doc_name: "領血確認標準作業程序",
          category_code: "SOP",
          category_name: "SOP",
          published_date: "2026-04-15T00:00:00Z",
          author_id: "u1",
          author_name: "陳大華",
          func_code: null,
          func_name: null,
          tags: ["供應", "平時"],
        },
        {
          doc_id: "DM-MANUAL-000002",
          doc_name: "BS04 領血掃血袋線上系統操作手冊",
          category_code: "MANUAL",
          category_name: "系統操作手冊",
          published_date: "2026-05-02T00:00:00Z",
          author_id: "u2",
          author_name: "王曉明",
          func_code: "BS04",
          func_name: "領血確認",
          tags: ["供應"],
        },
      ],
      meta: { total: 2, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  http.get("/api/dm/library/func-options", () =>
    HttpResponse.json([{ code: "BS04", name: "領血確認", group_code: null }]),
  ),
  http.get("/api/dm/library/retrieval-tags", () =>
    HttpResponse.json([
      { code: "10", name: "供應", group_code: "MODULE" },
      { code: "20", name: "平時", group_code: "NATURE" },
    ]),
  ),
  http.get("/api/dm/library/capabilities", () => HttpResponse.json({ can_create: true })),
  // US4 文件詳細頁（dm-detail）：預設 PDF 已發布、可編輯；個別測試以 server.use 覆蓋
  http.get("/api/dm/documents/:docId", ({ params }) =>
    HttpResponse.json({
      doc_id: params.docId,
      doc_name: "領血確認標準作業程序",
      status: "PUBLISHED",
      current_version_no: "2.1",
      category_code: "SOP",
      category_name: "SOP",
      author_id: "u1",
      author_name: "陳大華",
      published_date: "2026-04-15T10:30:00Z",
      approver_id: "u2",
      approver_name: "李主任",
      approve_time: "2026-04-15T10:30:00Z",
      tags: ["平時"],
      func_code: null,
      func_name: null,
      file: {
        version_id: 21,
        file_name: "SOP-v2.1.pdf",
        file_mime: "application/pdf",
        file_size: 2200000,
        uploaded_at: "2026-04-15T10:30:00Z",
        previewable: true,
      },
      is_editor: true,
      can_edit: true,
      edit_lock_reason: null,
      is_obsolete: false,
      obsolete_info: null,
    }),
  ),
  http.get("/api/dm/documents/:docId/versions", () =>
    HttpResponse.json([
      {
        version_id: 21,
        version_no: "2.1",
        change_summary: "補充異常通報流程",
        file_name: "SOP-v2.1.pdf",
        author_id: "u1",
        author_name: "陳大華",
        approver_name: "李主任",
        published_date: "2026-04-15T10:30:00Z",
        is_current: true,
        previewable: true,
      },
      {
        version_id: 20,
        version_no: "2.0",
        change_summary: "改版重寫",
        file_name: "SOP-v2.0.pdf",
        author_id: "u1",
        author_name: "陳大華",
        approver_name: "李主任",
        published_date: "2026-02-10T14:20:00Z",
        is_current: false,
        previewable: true,
      },
    ]),
  ),
  // US7 權限管理（dp-roles）：預設 DM 可管理、一筆使用者；個別測試以 server.use 覆蓋
  // US5 文件新增與編輯（dm-editor）：受控下拉 / 審核者 / 新增 / 加版 / 送簽（happy path）
  http.get("/api/dm/editor/options", () =>
    HttpResponse.json({
      categories: [
        { code: "SOP", name: "標準作業程序" },
        { code: "MANUAL", name: "系統操作手冊" },
        { code: "TRAINING", name: "訓練教材" },
        { code: "OTHER", name: "其他" },
      ],
      funcs: [{ code: "BS04", name: "領血確認", group_code: null }],
      audiences: [
        { code: "1", name: "全體", group_code: null },
        { code: "2", name: "護理師", group_code: null },
      ],
      retrieval_tags: [
        { code: "10", name: "供應", group_code: "MODULE" },
        { code: "20", name: "平時", group_code: "NATURE" },
      ],
    }),
  ),
  http.get("/api/dm/reviewers", () =>
    HttpResponse.json([
      { user_id: "rev1", user_name: "王審核" },
      { user_id: "rev2", user_name: "李審核" },
    ]),
  ),
  http.post("/api/dm/documents", () =>
    HttpResponse.json({ doc_id: "DM-SOP-000009", version_id: 900, previewable: true }, { status: 201 }),
  ),
  http.post("/api/dm/documents/:docId/versions", () =>
    HttpResponse.json({ version_id: 901, previewable: true }, { status: 201 }),
  ),
  http.post("/api/dm/documents/:docId/submit", () => HttpResponse.json({ review_id: 500, notified: 1 })),
  http.get("/api/dp/roles/modules", () => HttpResponse.json(["DM"])),
  http.get("/api/dp/roles/:module/assignments", () =>
    HttpResponse.json({
      data: [
        {
          user_id: "u1",
          user_name: "王曉明",
          email: "ming@example.com",
          roles: ["DM_EDITOR"],
          groups: [],
          last_modified_by: "admin",
          last_modified_by_name: "系統管理員",
          last_modified_date: "2026-06-30T00:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  http.get("/api/dp/roles/:module/group-options", () =>
    HttpResponse.json([{ code: "5", name: "護理師" }]),
  ),
  http.put("/api/dp/roles/:module/assignments/:userId", () => new HttpResponse(null, { status: 204 })),
  // US8 個人資料維護（預設 happy path）
  http.get("/api/dp/user/me", () =>
    HttpResponse.json({ user_id: "u1", email: "me@example.com", user_name: "測試員", pending_email: null }),
  ),
  http.put("/api/dp/user/me", () => new HttpResponse(null, { status: 204 })),
  http.put("/api/dp/user/me/password", () => new HttpResponse(null, { status: 204 })),
  http.put("/api/dp/user/me/email", () =>
    HttpResponse.json(
      { message: "驗證信已寄至新 Email，請於效期內完成驗證；驗證前原 Email 仍可登入", retry_after: 600 },
      { status: 202 },
    ),
  ),
  http.post("/api/verify-email-change", () => HttpResponse.json({ message: "Email 已變更，請以新 Email 登入" })),
  http.get("/api/password-policy", () =>
    HttpResponse.json({ min_len: 8, admin_min_len: 12, char_types: 3, history_count: 3, expiry_days: 90 }),
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
          invite_id: "inv-valid",
          user_name: "周雅婷",
          email: "tina@edms.local",
          created_date: "2026-07-06T10:20:00Z",
          expires_date: "2099-01-01T00:00:00Z",
        },
        {
          invite_id: "inv-expired",
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
  // US5 系統參數維護（預設 happy path；含平台 VALUE / LIST 與 DM 鎖定清單供 UI 驗證）
  http.get("/api/dp/params", () =>
    HttpResponse.json([
      {
        param_id: "JWT",
        param_name: "JWT 設定",
        param_type: "VALUE",
        detail_lock: false,
        description: "JWT 存取與換發相關參數",
        scope: "platform",
        details: [
          {
            param_key: "ACCESS_TTL_MIN",
            param_name: "閒置自動登出（分鐘）",
            param_value: "15",
            description: null,
            sort_order: null,
            is_enabled: true,
          },
          {
            param_key: "RENEW_MAX_HOURS",
            param_name: "單次登入時效上限（小時）",
            param_value: "8",
            description: null,
            sort_order: null,
            is_enabled: true,
          },
        ],
      },
      {
        param_id: "ET_TRAINING_UNIT",
        param_name: "受訓單位標籤",
        param_type: "LIST",
        detail_lock: false,
        description: null,
        scope: "ET",
        details: [
          { param_key: "NURSE", param_name: "護理師", param_value: null, description: null, sort_order: 1, is_enabled: true },
        ],
      },
      {
        param_id: "DM_DOC_CATEGORY",
        param_name: "文件分類",
        param_type: "LIST",
        detail_lock: true,
        description: null,
        scope: "DM",
        details: [
          { param_key: "SOP", param_name: "標準作業程序", param_value: null, description: null, sort_order: 1, is_enabled: true },
        ],
      },
    ]),
  ),
  http.put("/api/dp/params/:id/details/:key", () =>
    HttpResponse.json({
      param_key: "ACCESS_TTL_MIN",
      param_name: "閒置自動登出（分鐘）",
      param_value: "10",
      description: null,
      sort_order: null,
      is_enabled: true,
    }),
  ),
  http.post("/api/dp/params/:id/details", () =>
    HttpResponse.json(
      { param_key: "DOCTOR", param_name: "醫師", param_value: null, description: null, sort_order: null, is_enabled: true },
      { status: 201 },
    ),
  ),
  // US9 通知範本維護（預設 happy path：一支 DP 系統信 + 一支 ET 範本）
  http.get("/api/dp/notify/templates", () =>
    HttpResponse.json([
      {
        module: "DP",
        template_code: "PWD_RESET",
        template_name: "密碼重設",
        subject: "【EDMS】密碼重設連結",
        body: "您好 {user_name}，請點連結重設密碼。",
        variables: "user_name, reset_link",
        channel: "EMAIL",
        is_enabled: true,
        is_system: true,
        version: 1,
      },
      {
        module: "ET",
        template_code: "COURSE_INVITE",
        template_name: "課程邀請通知",
        subject: "課程邀請",
        body: "您好 {user_name}，您有新課程。",
        variables: "user_name",
        channel: "EMAIL",
        is_enabled: true,
        is_system: false,
        version: 1,
      },
    ]),
  ),
  http.put("/api/dp/notify/templates/:module/:code", async ({ params, request }) => {
    const body = (await request.json()) as { subject: string; body: string; channel: string; version: number }
    return HttpResponse.json({
      module: params.module,
      template_code: params.code,
      template_name: "範本",
      subject: body.subject,
      body: body.body,
      variables: "user_name",
      channel: body.channel,
      is_enabled: true,
      is_system: params.module === "DP",
      version: body.version + 1,
    })
  }),
  // US10 操作記錄查詢（預設 happy path：一筆 SUCCESS + 一筆 FAIL 供 UI 驗證）
  http.get("/api/dp/audit/logs", () =>
    HttpResponse.json({
      data: [
        {
          log_id: 2,
          created_date: "2026-07-06T09:15:22Z",
          operator_id: "u001",
          operator_name: "陳大華",
          operator_email: "chen@edms.local",
          module: "DP",
          func_name: "DP-USERS",
          func_label: "DP-使用者管理",
          action_type: "UPDATE",
          result: "SUCCESS",
          target_id: "u1042",
          target_display: "林小美",
          source_ip: "10.1.2.33",
          description: "手動解鎖帳號",
          before_value: '{"status": "LOCKED"}',
          after_value: '{"status": "ACTIVE"}',
        },
        {
          log_id: 1,
          created_date: "2026-07-06T09:13:55Z",
          operator_id: "SYSTEM",
          operator_name: null,
          operator_email: null,
          module: "DP",
          func_name: "DP-AUTH",
          func_label: "DP-登入登出",
          action_type: "LOGIN",
          result: "FAIL",
          target_id: null,
          target_display: null,
          source_ip: "203.0.113.9",
          description: "密碼錯誤",
          before_value: null,
          after_value: null,
        },
      ],
      meta: { total: 2, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  http.get("/api/dp/audit/logs/export", () =>
    HttpResponse.text("﻿LOG_ID,時間\n2,2026-07-06 09:15:22\n", {
      headers: { "Content-Type": "text/csv; charset=utf-8" },
    }),
  ),
  // US11 排程總覽（預設 happy path：SCHDP001 啟用 + ET/DM 預留停用）
  http.get("/api/dp/schedules", () =>
    HttpResponse.json([
      {
        job_id: "SCHDP001",
        job_name: "平台每日作業（閒置帳號禁用 + 密碼到期提醒）",
        module: "DP",
        cron_expr: "0 8 * * *",
        is_enabled: true,
        last_run_date: "2026-07-06T08:00:41Z",
        last_run_status: "SUCCESS",
        next_run_date: "2026-08-01T08:00:00Z",
      },
      {
        job_id: "SCHET001",
        job_name: "ET 週報 / 提醒（預留）",
        module: "ET",
        cron_expr: "0 8 * * 1",
        is_enabled: false,
        last_run_date: null,
        last_run_status: null,
        next_run_date: null,
      },
    ]),
  ),
  http.put("/api/dp/schedules/:jobId", async ({ params, request }) => {
    const body = (await request.json()) as { job_name: string; cron_expr: string; is_enabled: boolean }
    return HttpResponse.json({
      job_id: params.jobId,
      job_name: body.job_name,
      module: "DP",
      cron_expr: body.cron_expr,
      is_enabled: body.is_enabled,
      last_run_date: null,
      last_run_status: null,
      next_run_date: body.is_enabled ? "2026-08-02T02:30:00Z" : null,
    })
  }),
  http.get("/api/dp/schedules/SCHDP001/logs", () =>
    HttpResponse.json({
      data: [
        {
          log_id: 2,
          job_id: "SCHDP001",
          start_date: "2026-07-06T08:00:00Z",
          end_date: "2026-07-06T08:00:41Z",
          status: "SUCCESS",
          error_msg: null,
        },
      ],
      meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
    }),
  ),
  http.get("/api/dp/schedules/SCHET001/logs", () =>
    HttpResponse.json({ data: [], meta: { total: 0, page: 1, limit: 20, total_pages: 0 } }),
  ),
]

export const server = setupServer(...handlers)
