/**
 * 側欄高亮哪一項（#89 統一 shell 的導覽狀態）。
 *
 * 原本直接交給 `NavLink` 的前綴相符，而**子頁的網址前綴不一定是它的入口**：
 * ET06 章節學習 `/et/courses/:id/learn` 的前綴是 `/et/courses`（ET01 課程列表），
 * 但學員是從 ET03 我的課程點課程卡片進來的——純學員連 ET01 都看不到
 * （`requiresEtManage`），於是整個側欄沒有任何一項亮著。DM07 文件詳細頁
 * `/dm/documents/:docId` 更是連前綴都對不上任何功能項，一律不亮。
 *
 * 本模組把「高亮哪一項」從 URL 前綴改為明確的對應：單一入口的子頁寫進
 * `SUBPAGE_ACTIVE_NAV`，多個入口的子頁由進入時帶的 `NAV_FROM` 決定。
 */
import { NAV_GROUPS } from "./navItems"

/**
 * `location.state` 上標記「本頁是從哪個側欄功能項進來的」。
 *
 * 只有**同一個子頁有多個側欄入口**時才需要——DM07 文件詳細頁可自 DM01 文件庫或
 * DM03 已廢止文件查詢進入，光看網址分不出來。單一入口的子頁一律用
 * `SUBPAGE_ACTIVE_NAV`：那條對應連直接貼網址、重新整理都成立，而 state 只有
 * 點擊進入時才有（瀏覽器會把它存進該筆歷程，故重新整理與上一頁 / 下一頁仍在，
 * 但換一筆歷程就沒了）。
 */
export const NAV_FROM = "__navFrom"

/** 導航到子頁時帶上來源功能項：`navigate(path, navFrom("/dm/obsolete"))`。 */
export function navFrom(navPath: string): { state: Record<string, string> } {
  return { state: { [NAV_FROM]: navPath } }
}

/** 所有側欄功能項的 path。高亮與可見性各自獨立——算出來的項目若被角色隱藏，就是沒有一項亮著。 */
const NAV_PATHS: readonly string[] = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.path))

/**
 * 無側欄入口的子頁 → 應高亮的功能項。只放**入口唯一**（或有唯一合理預設）的子頁；
 * 比前綴相符優先，否則 `/et/courses/:id/learn` 會被 `/et/courses` 搶走。
 */
const SUBPAGE_ACTIVE_NAV: readonly (readonly [RegExp, string])[] = [
  // ET06 章節學習 / 課後問卷：自 ET03 我的課程的課程卡片進入（教師自 ET01「全部課程」
  // 預覽時由 `NAV_FROM` 覆寫，見 CourseListPage）
  [/^\/et\/courses\/[^/]+\/(learn|survey)$/, "/et/my-courses"],
  // ET06 測驗作答與成績：自章節學習頁進入；來源不再往下傳，一律歸「我的課程」
  [/^\/et\/attempts\//, "/et/my-courses"],
  // DM07 文件詳細頁：預設 DM01 文件庫；自 DM03 已廢止文件查詢進入者由 `NAV_FROM` 覆寫。
  // `new`（DM08 文件新增）刻意排除：本次只處理詳細頁，DM08 維持既有的「不亮」，
  // 免得新增亮 DM01、編輯（`/:docId/edit`）不亮，兩個編輯模式表現不一致。
  [/^\/dm\/documents\/(?!new$)[^/]+$/, "/dm/library"],
]

/**
 * 目前位置應高亮哪一個側欄功能項，回傳其 path；無對應者回 `undefined`（側欄不亮任何一項）。
 *
 * @param pathname `location.pathname`
 * @param state `location.state`（可能帶 `NAV_FROM`）
 */
export function resolveActiveNavPath(pathname: string, state?: unknown): string | undefined {
  if (NAV_PATHS.includes(pathname)) return pathname

  const from = readNavFrom(state)
  if (from) return from

  for (const [pattern, navPath] of SUBPAGE_ACTIVE_NAV) {
    if (pattern.test(pathname)) return navPath
  }

  // 其餘子頁沿用前綴相符（ET05 課程建立 / 編輯 → ET01）。同時命中多項時取最長者。
  return NAV_PATHS.filter((navPath) => pathname.startsWith(`${navPath}/`)).sort((a, b) => b.length - a.length)[0]
}

/** 取 state 上的來源功能項；非字串或已不是側欄功能項（竄改 / 功能項改過路徑）一律忽略。 */
function readNavFrom(state: unknown): string | undefined {
  if (typeof state !== "object" || state === null) return undefined
  const value = (state as Record<string, unknown>)[NAV_FROM]
  return typeof value === "string" && NAV_PATHS.includes(value) ? value : undefined
}
