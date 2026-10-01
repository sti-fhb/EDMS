/** 首頁教育訓練儀表板的回應型別（對應後端 `GET /api/et/dashboard`，#453）。 */

/** 學員卡「我的學習概況」。 */
export interface StudentCard {
  joined: number
  in_progress: number
  not_started: number
  completed: number
  pending_open: number
}

/** 教師卡的一列：即將截止且仍有人未完課的課程。 */
export interface TeacherCourseLine {
  course_id: number
  course_name: string
  days_left: number
  not_completed: number
}

/** 教師卡「我的課程待辦」。 */
export interface TeacherCard {
  ending_soon: TeacherCourseLine[]
  draft_count: number
}

/** 管理者卡的一列：一個受訓單位的達成狀況。 */
export interface UnitRate {
  tag_name: string
  enrolled: number
  completed: number
  /** `DECIMAL(5,2)` 經 JSON 後為字串。 */
  completion_rate: string
}

/** 管理者卡「全體訓練概況」。 */
export interface AdminCard {
  overdue_incomplete: number
  completion_rate: string
  by_unit: UnitRate[]
}

/**
 * 三張卡；**`null` = 沒有該角色**。
 *
 * ⚠️ `null` 與「有角色但沒資料」是不同的兩件事，兩者都不渲染但語意不同——判斷要不要
 * 顯示一律用下方的 `hasXxxData`，不要只看 `!== null`。
 */
export interface EtDashboard {
  student: StudentCard | null
  teacher: TeacherCard | null
  admin: AdminCard | null
}

/**
 * #89 的**空卡規則**：卡片無資料就不渲染。
 *
 * > spec 定義「人人具 ET 學員預設角色」，若嚴格「有 ET 角色就顯示我的課程」→ 主管也會
 * > 看到空的「我的課程」。故規則為卡片無資料就不渲染。
 *
 * ⛔ 因此**不可**寫成 `modules.et.has_role && <Widget />`（DM 那側是這樣寫的，但它沒有
 * 「人人都有預設角色」這個前提）。
 */
export function hasStudentData(card: StudentCard | null): card is StudentCard {
  return card !== null && card.joined > 0
}

/** 教師卡：沒有即將截止的課、也沒有草稿，就沒有要他做的事。 */
export function hasTeacherData(card: TeacherCard | null): card is TeacherCard {
  return card !== null && (card.ending_soon.length > 0 || card.draft_count > 0)
}

/**
 * 管理者卡：全站連一筆在籍都沒有時不渲染。
 *
 * ⚠️ 判準用 `by_unit` 或 `overdue_incomplete` 都不對——前者在「有人但都沒貼單位標籤」
 * 時為空、後者在「一切正常」時為 0，而那兩種情況管理者都該看到完成率。故以「有沒有
 * 任何一個單位有人」加上「有沒有逾期」聯集，兩者皆空才是真的無事可看。
 */
export function hasAdminData(card: AdminCard | null): card is AdminCard {
  return card !== null && (card.by_unit.length > 0 || card.overdue_incomplete > 0)
}
