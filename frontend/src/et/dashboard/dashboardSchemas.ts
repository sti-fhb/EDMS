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

/**
 * 教師卡「我的課程提醒」。
 *
 * 📌 #818 移除了 `draft_count`（自己建立但尚未發布的課程數）。區塊更名為「提醒」
 * 後那一行與名稱對不上，畫面已不顯示；草稿本來就在 ET01 課程列表看得到。
 */
export interface TeacherCard {
  ending_soon: TeacherCourseLine[]
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
  completion_rate: string
  /**
   * **截斷前**的母體大小——開放中且已有學員的課程門數（#818）。
   *
   * 用來寫出「完成率最低的 N 門，開放中共 M 門」。⚠️ `by_course` 已由後端截為最多
   * 5 筆，所以 `M > by_course.length` 是常態；相等時代表沒有被截斷，此時寫「最低的
   * N 門」沒有意義，註記要退回原本的「（各課程完成率）」。
   */
  open_course_count: number
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

/**
 * 教師卡：沒有即將截止的課，就沒有要提醒他的事。
 *
 * ## 🔴 判定只看 `ending_soon`——**因為畫面只畫 `ending_soon` 的列**
 *
 * #818 之前還看 `draft_count`，而草稿數那一行當時仍畫在卡上，兩者是一致的。該行已於
 * #818 移除（區塊更名為「提醒」後與名稱對不上），判定若留著 `draft_count`，「只有草稿、
 * 沒有即將截止的課」的教師會拿到一張**空卡**——標題與「前往課程列表 →」都在、底下一列
 * 都沒有。這與 `hasAdminData` 踩過的是同一個洞（見其說明）。
 *
 * ⛔ **渲染條件必須只看實際會被畫出來的欄位。** 判定與畫面各自演進是空卡的來源，而空卡
 * 不會報錯，只是看起來像壞了。
 */
export function hasTeacherData(card: TeacherCard | null): card is TeacherCard {
  return card !== null && card.ending_soon.length > 0
}

/**
 * 管理者卡：全站連一門有人的課程都沒有時不渲染。
 *
 * ## 🔴 判定只看 `by_course`——**因為畫面只畫 `by_course` 的列**
 *
 * 歷史：2026-10-02 起「逾期未完成」不再顯示（手測裁示），而該欄當時仍在判定裡，
 * 於是「有逾期但一門課都沒有」會渲染出一張**空表格**——標題與表頭都在、底下一列
 * 都沒有。該欄已於 #818 整個移除。
 *
 * ⛔ **渲染條件必須只看實際會被畫出來的欄位。** 判定與畫面各自演進是空卡的來源，
 * 而空卡不會報錯，只是看起來像壞了。⚠️ `open_course_count` 同樣**不可**進入判定：
 * 它只是標題裡的一個數字，`by_course` 為空時那張表仍然是空的。
 */
export function hasAdminData(card: AdminCard | null): card is AdminCard {
  return card !== null && card.by_course.length > 0
}
