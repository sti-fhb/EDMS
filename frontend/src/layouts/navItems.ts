/** 統一 shell 側欄的導覽群組（#89 P1）。P1「系統管理者後台」；DM「文件管理」群組於 P4（#127）加入。 */
export interface NavItem {
  label: string
  path: string
}

export interface NavGroup {
  title: string
  items: readonly NavItem[]
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
    // 文件管理（#127 Foundation）：對齊 wireframe DM 側欄 6 項；各頁目前為骨架佔位。
    // 權限可見性（如管理者專屬項）於後續 US 依 DM 角色決定顯示與否，此處先全列。
    title: "文件管理",
    items: [
      { label: "文件庫", path: "/dm/library" },
      { label: "簽核中心", path: "/dm/review" },
      { label: "個人專區", path: "/dm/me" },
      { label: "已廢止文件查詢", path: "/dm/obsolete" },
      { label: "文件變更歷程查詢", path: "/dm/change-log" },
      { label: "閱讀統計 KPI", path: "/dm/kpi" },
    ],
  },
]
