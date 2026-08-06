/** 統一 shell 側欄的導覽群組（#89 P1）。P1 僅「系統管理者後台」群組；ET / DM 群組於 P3 / P4 加入。 */
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
]
