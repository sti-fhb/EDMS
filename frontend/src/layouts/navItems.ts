/** DP 後台 sidebar 的六個管理畫面（對齊 wireframe；入口頁 portal 為登入後落點、不在後台 sidebar）。 */
export interface NavItem {
  label: string
  path: string
}

export const DP_NAV_ITEMS: readonly NavItem[] = [
  { label: "使用者管理", path: "/dp/users" },
  { label: "系統參數", path: "/dp/params" },
  { label: "通知範本", path: "/dp/templates" },
  { label: "角色 / 權限", path: "/dp/roles" },
  { label: "稽核日誌", path: "/dp/audit" },
  { label: "排程總覽", path: "/dp/schedule" },
]
