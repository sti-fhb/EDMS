
/** ET04 課程下拉的空狀態判定（#439）。 */

/**
 * 下拉為何是空的——`null` 代表「不是空的，或還不知道」。
 *
 * ⚠️ 三態是刻意的：**說錯比不說更糟**。把「載入失敗」講成「尚無核可紀錄」是一句假話，
 * 使用者會據此以為系統裡真的沒有資料，而不是「剛才沒載到，重整一下」。ET02 的課程下拉
 * 踩過同一個坑（#390 的回歸）。
 */
export type CourseOptionsEmptyReason = "failed" | "none" | null

/**
 * 由查詢狀態導出下拉的空狀態成因。
 *
 * ## 🔴 為什麼吃的是 `isLoadingError` 而不是 `isError`
 *
 * TanStack Query v5 的 `isError` 在**背景刷新失敗**時也是 `true`，而此時 `data` 仍保有
 * 上次成功的內容——函式庫自己把這兩種情形拆成兩個旗標（`query-core` 的 `queryObserver`：
 * `isLoadingError: isError && !hasData`、`isRefetchError: isError && hasData`）。
 *
 * 用 `isError` 的後果是：教師成功載入下拉、選好課程之後，只要任何一次背景刷新失敗
 * （最容易撞到的是與 `/approvals/search` **共用同一個 60/分分桶**的限流），下拉就會被
 * 停用、並顯示「載入失敗」——**即使手上那份選項完全可用**。他失去的是一個還能用的功能。
 *
 * ⭐ 這個區別在「一開始就失敗」的測試裡**看不出來**：那時 `isError` 與 `isLoadingError`
 * 同時為真。要讓它現形，測試必須涵蓋「先成功、之後失敗」——本函式抽出來就是為了讓那個
 * 情境不需要真的觸發一次背景刷新才驗得到。
 *
 * ## ⭐ 為何收的是**整個查詢結果**而不是幾個 boolean
 *
 * 先前的版本收 `{ isLoadingError, isPending, optionCount }`，於是「要餵哪一個旗標」變成
 * 呼叫端的選擇——而那正是本函式存在的理由所在的那個坑。**純函式測試驗不到那個選擇**：
 * 它只證明「給定 `isLoadingError` 時行為正確」，有人改成餵 `isError` 照樣全綠。
 *
 * 改收查詢結果之後，那個自由度**在型別上就不存在了**：呼叫端把 `useQuery(...)` 整包交出來，
 * 由本函式決定看哪一個旗標。⛔ 不要為了「彈性」把它改回收 boolean。
 *
 * @param query `useQuery()` 的回傳值（只讀其中兩個旗標）。
 * @param optionCount 目前手上的選項數。
 */
export function courseOptionsEmptyReason(
  query: { isLoadingError: boolean; isPending: boolean },
  optionCount: number,
): CourseOptionsEmptyReason {
  if (query.isLoadingError) return "failed"
  if (query.isPending) return null
  return optionCount === 0 ? "none" : null
}
