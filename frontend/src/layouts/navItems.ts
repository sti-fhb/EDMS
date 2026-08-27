/** 統一 shell 側欄的導覽群組（#89 P1）。P1「系統管理者後台」；DM「文件管理」群組於 P4（#127）加入。 */
export interface NavItem {
  label: string
  path: string
  /** 個人專區入口可見性（US9 FR-004）：需具編輯者或審核者角色（DM-local access 判定，SA 裁示 Q1=C）。 */
  requiresDmPersonalAccess?: boolean
}

/** 模組門檻：需具該模組任一角色才顯示此群組（經 module-summary 判定）。未設＝恆顯示。 */
export type ModuleKey = "DM" | "ET"

export interface NavGroup {
  title: string
  items: readonly NavItem[]
  requiresModule?: ModuleKey
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    title: "系統管理者後台",
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
      { label: "簽核中心", path: "/dm/review" },
      { label: "個人專區", path: "/dm/me", requiresDmPersonalAccess: true },
      { label: "已廢止文件查詢", path: "/dm/obsolete" },
      { label: "文件變更歷程查詢", path: "/dm/change-log" },
      { label: "閱讀統計 KPI", path: "/dm/kpi" },
    ],
  },
]
