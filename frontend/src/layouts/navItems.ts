/** 統一 shell 側欄的導覽群組（#89 P1）。P1「系統管理者後台」；DM「文件管理」群組於 P4（#127）加入。 */
export interface NavItem {
  label: string
  path: string
  /** 個人專區入口可見性（US9 FR-004）：需具編輯者或審核者角色（DM-local access 判定，SA 裁示 Q1=C）。 */
  requiresDmPersonalAccess?: boolean
  /** admin-only 項入口可見性（US10 已廢止 / US11 變更歷程 / US13 KPI）：需具 DM_ADMIN；共用 GET /dm/admin-access（US11 A' 收斂）。 */
  requiresDmAdminAccess?: boolean
  /** 簽核中心入口可見性（#250）：需具 DM_REVIEWER（僅具 DM_ADMIN 者亦不顯示）；GET /dm/reviewer-access。 */
  requiresDmReviewerAccess?: boolean
}

/** 模組門檻：需具該模組任一角色才顯示此群組（經 module-summary 判定）。未設＝恆顯示。 */
export type ModuleKey = "DM" | "ET"

export interface NavGroup {
  title: string
  items: readonly NavItem[]
  requiresModule?: ModuleKey
  /**
   * 群組門檻（#250）：需具 **ET 或 DM 任一模組管理者**角色才顯示。
   * 對齊 spec——DP 後台六項功能（spec_us4 / us5 / us7 / us9 / us10 / us11）之操作者
   * 皆定義為「ET 或 DM 管理者」；後端對應閘為 `require_any_module_admin`。
   */
  requiresAnyModuleAdmin?: boolean
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    // requiresAnyModuleAdmin（#250）：原為「過渡期對所有登入者顯示」，收斂為模組管理者專用。
    // 側欄與後端閘同源（module-summary 的 is_admin ↔ require_any_module_admin），
    // 避免側欄承諾閘不給的東西。
    title: "系統管理者後台",
    requiresAnyModuleAdmin: true,
    items: [
      { label: "使用者管理", path: "/dp/users" },
      { label: "系統參數", path: "/dp/params" },
      { label: "通知範本", path: "/dp/templates" },
      { label: "角色 / 權限", path: "/dp/roles" },
      { label: "稽核日誌", path: "/dp/audit" },
      { label: "排程總覽", path: "/dp/schedule" },
    ],
  },
  {
    // 教育訓練（#202）：對齊 wireframe ET 側欄 4 項；課程列表以外各頁目前為骨架佔位。
    // requiresModule=ET：無任一 ET 角色者整個群組不顯示（module-summary 判定；
    // 該端點之 ET 判定已於 #201 由寫死 true 改為實查 et_has_any_role）。
    // ⚠️ ET02 課程建立 / 編輯**不是**側欄項目——它是課程列表的子頁
    //（/et/courses/new、/et/courses/:courseId）。
    title: "教育訓練",
    requiresModule: "ET",
    items: [
      { label: "課程列表", path: "/et/courses" },
      { label: "學員", path: "/et/students" },
      { label: "核可查詢", path: "/et/approvals" },
      { label: "我的課程", path: "/et/my-courses" },
    ],
  },
  {
    // 文件管理（#127 Foundation）：對齊 wireframe DM 側欄 6 項；各頁目前為骨架佔位。
    // requiresModule=DM（US1）：無任一 DM 角色者，整個群組不顯示（module-summary 判定）。
    title: "文件管理",
    requiresModule: "DM",
    items: [
      { label: "文件庫", path: "/dm/library" },
      // 簽核中心（#250）：限 DM_REVIEWER——原本管理者 / 編輯者也看得到，但清單依
      // assigned_reviewer=登入者 過濾，點進去永遠空白（SA Q3=A 裁示嚴格只認審核者）
      { label: "簽核中心", path: "/dm/review", requiresDmReviewerAccess: true },
      { label: "個人專區", path: "/dm/me", requiresDmPersonalAccess: true },
      { label: "已廢止文件查詢", path: "/dm/obsolete", requiresDmAdminAccess: true },
      { label: "文件變更歷程查詢", path: "/dm/change-log", requiresDmAdminAccess: true },
      { label: "閱讀統計 KPI", path: "/dm/kpi" },
    ],
  },
]
