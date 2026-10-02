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

/** 管理者卡的一列：一門課程的完成狀況（#475，原為受訓單位）。 */
export interface CourseRate {
  /**
   * ⚠️ **必須有**：後端以 `(course_id, course_name)` 分組，同名課程刻意不合併（不同
   * 年度的年度訓練）。以 `course_name` 當 React key 會撞號——症狀是改動一列時另一列
   * 跟著變，且不會有任何錯誤訊息。
   */
  course_id: number
  course_name: string
  enrolled: number
  completed: number
  /** `DECIMAL(5,2)` 經 JSON 後為字串。 */
  completion_rate: string
}

/** 管理者卡「全體訓練概況」。 */
export interface AdminCard {
  overdue_incomplete: number
  completion_rate: string
  by_course: CourseRate[]
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
 * 管理者卡：全站連一門有人的課程都沒有時不渲染。
 *
 * ## 🔴 判定只看 `by_course`——**因為畫面只畫 `by_course`**
 *
 * 2026-10-02 起「逾期未完成」不再顯示（手測裁示）。若這裡仍保留
 * `|| card.overdue_incomplete > 0`，「有逾期但一門課都沒有」會渲染出一張**空表格**
 * ——標題與表頭都在、底下一列都沒有。
 *
 * ⛔ **渲染條件必須只看實際會被畫出來的欄位。** 判定與畫面各自演進是空卡的來源，
 * 而空卡不會報錯，只是看起來像壞了。`AdminCard.overdue_incomplete` 的 docstring
 * 有對應的提醒，改動任一側時兩邊要一起看。
 */
export function hasAdminData(card: AdminCard | null): card is AdminCard {
  return card !== null && card.by_course.length > 0
}
