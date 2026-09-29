/** 統一 shell 側欄的導覽群組（#89 P1）。P1「系統管理者後台」；DM「文件管理」群組於 P4（#127）加入。 */
import type { SvgIconComponent } from "@mui/icons-material"
import AccountBoxIcon from "@mui/icons-material/AccountBox"
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings"
import AssignmentTurnedInIcon from "@mui/icons-material/AssignmentTurnedIn"
import AutoStoriesIcon from "@mui/icons-material/AutoStories"
import BarChartIcon from "@mui/icons-material/BarChart"
import EditNoteIcon from "@mui/icons-material/EditNote"
import EmailIcon from "@mui/icons-material/Email"
import FactCheckIcon from "@mui/icons-material/FactCheck"
import FolderOffIcon from "@mui/icons-material/FolderOff"
import HistoryIcon from "@mui/icons-material/History"
import LibraryBooksIcon from "@mui/icons-material/LibraryBooks"
import ManageAccountsIcon from "@mui/icons-material/ManageAccounts"
import ManageSearchIcon from "@mui/icons-material/ManageSearch"
import MenuBookIcon from "@mui/icons-material/MenuBook"
import ScheduleIcon from "@mui/icons-material/Schedule"
import SchoolIcon from "@mui/icons-material/School"
import TuneIcon from "@mui/icons-material/Tune"

/** 畫面：代號 + 名稱 + icon。側欄項目與頁面左上標題（`ScreenHeader`）共用同一份，兩處必然一致。 */
export interface Screen {
  code: string
  label: string
  /** 各畫面 icon 不得重複（Sidebar.test 守門），否則側欄上分不出功能。 */
  icon: SvgIconComponent
}

export interface NavItem extends Screen {
  /**
   * 畫面代號（#421）：**取自各模組 spec 之〈畫面代號對照表〉，不得自訂**
   * （`docs/specs/{dp,et,dm}/spec.md`）。格式為模組碼 + 兩位數字。
   *
   * 編號在側欄中不連續是正常的——部分畫面沒有側欄入口：`DP00` 為登入後主頁（中性歡迎頁、
   * index route）、`DP01`~`DP04` 為登入 / 註冊 / 忘記密碼 / 個資頁、`ET02` 課程建立為課程列表
   * 之子頁、`DM02` 文件詳細頁由清單進入。
   * 交付甲方的文件以此編號標示作業，畫面上必須對得起來。
   */
  code: string
  path: string
  /** 個人專區入口可見性（US9 FR-004）：需具編輯者或審核者角色（DM-local access 判定，SA 裁示 Q1=C）。 */
  requiresDmPersonalAccess?: boolean
  /** admin-only 項入口可見性（US10 已廢止 / US11 變更歷程 / US13 KPI）：需具 DM_ADMIN；共用 GET /dm/admin-access（US11 A' 收斂）。 */
  requiresDmAdminAccess?: boolean
  /** 簽核中心入口可見性（#250）：需具 DM_REVIEWER（僅具 DM_ADMIN 者亦不顯示）；GET /dm/reviewer-access。 */
  requiresDmReviewerAccess?: boolean
  /** ET 教學管理項：需具教師或管理者角色（`Capabilities.can_manage_courses`）。 */
  requiresEtManage?: boolean
  /** ET 學習項（我的課程）：需具學員角色（`Capabilities.can_learn`）。 */
  requiresEtLearn?: boolean
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
    // 教育訓練（#202）：對齊 wireframe ET 側欄 4 項；課程列表以外各頁目前為骨架佔位。
    // requiresModule=ET：無任一 ET 角色者整個群組不顯示（module-summary 判定；
    // 該端點之 ET 判定已於 #201 由寫死 true 改為實查 et_has_any_role）。
    // ⚠️ ET02 課程建立 / 編輯**不是**側欄項目——它是課程列表的子頁
    //（/et/courses/new、/et/courses/:courseId）。
    title: "教育訓練",
    requiresModule: "ET",
    items: [
      // 群組門檻（requiresModule）只判「有無任一 ET 角色」；群組內再依角色分流
      // （#247）——ET 三種角色可任意組合，純學員看到「課程列表 / 學員」等於看到
      // 點進去只會 403 的項目，純教師看到「我的課程」則是一個空清單。
      { code: "ET01", icon: MenuBookIcon, label: "課程列表", path: "/et/courses", requiresEtManage: true },
      { code: "ET03", icon: SchoolIcon, label: "學員", path: "/et/students", requiresEtManage: true },
      { code: "ET04", icon: AutoStoriesIcon, label: "我的課程", path: "/et/my-courses", requiresEtLearn: true },
      // 核可查詢**兩種角色都要**，但看到的內容不同：學員查自己已通過核可的課程；
      // 教師依姓名查——**已通過**的涵蓋全部課程，**不通過 / 已撤銷 / 考核備註**僅限
      // 自己所開設的課程（US17 SA 裁示 C，見 `app/et/approval/query_rules.py`）。
      // 不掛任何角色旗標＝具任一 ET 角色即顯示；資料邊界完全由後端負責。
      { code: "ET10", icon: FactCheckIcon, label: "核可查詢", path: "/et/approvals" },
    ],
  },
  {
    // 文件管理（#127 Foundation）：對齊 wireframe DM 側欄 6 項；各頁目前為骨架佔位。
    // requiresModule=DM（US1）：無任一 DM 角色者，整個群組不顯示（module-summary 判定）。
    title: "文件管理",
    requiresModule: "DM",
    items: [
      { code: "DM01", icon: LibraryBooksIcon, label: "文件庫", path: "/dm/library" },
      // 簽核中心（#250）：限 DM_REVIEWER——原本管理者 / 編輯者也看得到，但清單依
      // assigned_reviewer=登入者 過濾，點進去永遠空白（SA Q3=A 裁示嚴格只認審核者）
      { code: "DM04", icon: AssignmentTurnedInIcon, label: "簽核中心", path: "/dm/review", requiresDmReviewerAccess: true },
      { code: "DM06", icon: FolderOffIcon, label: "已廢止文件查詢", path: "/dm/obsolete", requiresDmAdminAccess: true },
      { code: "DM07", icon: AccountBoxIcon, label: "個人專區", path: "/dm/me", requiresDmPersonalAccess: true },
      { code: "DM08", icon: HistoryIcon, label: "文件變更歷程查詢", path: "/dm/change-log", requiresDmAdminAccess: true },
      // US13 KPI 為管理者功能，與路由守衛 RequireDmAdmin 一致（#250 / main 同時補上此 flag）
      { code: "DM10", icon: BarChartIcon, label: "閱讀統計 KPI", path: "/dm/kpi", requiresDmAdminAccess: true },
    ],
  },
  {
    // requiresAnyModuleAdmin（#250）：原為「過渡期對所有登入者顯示」，收斂為模組管理者專用。
    // 側欄與後端閘同源（module-summary 的 is_admin ↔ require_any_module_admin），
    // 避免側欄承諾閘不給的東西。
    title: "系統管理者後台",
    requiresAnyModuleAdmin: true,
    items: [
      // 標籤一律採用 spec 對照表之畫面名稱（#421）：交付文件以畫面碼 + 名稱標示作業，
      // 側欄若用簡稱（如「稽核日誌」對 DP09「操作記錄查詢」），甲方對不起來。
      { code: "DP05", icon: ManageAccountsIcon, label: "使用者管理", path: "/dp/users" },
      { code: "DP06", icon: AdminPanelSettingsIcon, label: "權限管理", path: "/dp/roles" },
      { code: "DP07", icon: TuneIcon, label: "系統參數與清單維護", path: "/dp/params" },
      { code: "DP08", icon: EmailIcon, label: "通知範本維護", path: "/dp/templates" },
      { code: "DP09", icon: ManageSearchIcon, label: "操作記錄查詢", path: "/dp/audit" },
      { code: "DP10", icon: ScheduleIcon, label: "排程作業總覽", path: "/dp/schedule" },
    ],
  },
]

/** 無側欄入口、但有自己頁面標題的畫面（子頁）。 */
const SUBPAGE_SCREENS: readonly Screen[] = [{ code: "ET02", label: "課程建立", icon: EditNoteIcon }]

const SCREENS: ReadonlyMap<string, Screen> = new Map(
  [...NAV_GROUPS.flatMap((group) => group.items), ...SUBPAGE_SCREENS].map((screen) => [screen.code, screen]),
)

/** 依畫面代號取畫面定義；代號打錯直接拋錯（開發期即現形，不靜默顯示空標題）。 */
export function getScreen(code: string): Screen {
  const screen = SCREENS.get(code)
  if (!screen) throw new Error(`未定義的畫面代號：${code}`)
  return screen
}
