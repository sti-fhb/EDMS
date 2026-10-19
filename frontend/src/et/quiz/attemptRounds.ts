/**
 * 作答紀錄依輪次分段（#709）——ET07 歷次作答紀錄與 ET02 作答明細共用。
 *
 * 「要求重測」（#361，測驗內容已改）與「重置重考次數」（ET02，同一份測驗多給機會）都會
 * 開啟新的一輪。兩個畫面原本把各輪作答平鋪在同一張表，看不出從哪一次開始是新一輪。
 */

/** 後端 `RoundBoundary`：一次重置。 */
export interface RoundBoundary {
  /** 重置當下的作答總數——分隔列插在 `attempt_no` 大於它的第一筆之前。 */
  after_attempt_no: number
  /** `RETEST`（要求重測）／`RETRY`（重置重考次數）／`null`（#709 之前的舊資料，原因未知）。 */
  kind: "RETEST" | "RETRY" | null
  executed_at: string
}

export type RoundRow<T> =
  | { type: "divider"; reset: RoundBoundary }
  /**
   * `previous`：在**最近一次「要求重測」**起點之前（灰色、標「前一輪」）。
   *
   * ⚠️ 只看 `RETEST`：灰色代表「不計入成績」，而「重置重考次數」（`RETRY`）與舊資料
   * 不影響最高分（後端 `attempt/rules.retest_base`）——灰掉會讓學員以為那幾次不算，
   * 與最高分對不起來（#709 Q1）。它們只插分隔列。
   */
  | { type: "attempt"; attempt: T; previous: boolean }

/** 分隔列的原因文字。舊資料分不出種類，給中性說法而非猜一個。 */
export function resetLabel(kind: RoundBoundary["kind"]): string {
  if (kind === "RETEST") return "教師要求重測（測驗內容已更新）"
  if (kind === "RETRY") return "重考次數已重置"
  return "重新計算起點"
}

/**
 * 依 `attempt_no` 遞增的作答清單插入輪次分隔列。
 *
 * ⚠️ 起點之後尚無作答時，分隔列**仍放在最後**——學員與教師要看得出「已要求重測、尚未重考」；
 * 少了它，畫面與重測前一模一樣。
 */
export function withRoundDividers<T extends { attempt_no: number }>(
  attempts: readonly T[],
  resets: readonly RoundBoundary[],
): RoundRow<T>[] {
  const ordered = [...resets].sort((a, b) => a.after_attempt_no - b.after_attempt_no)
  const latestRetest = Math.max(0, ...ordered.filter((r) => r.kind === "RETEST").map((r) => r.after_attempt_no))
  const rows: RoundRow<T>[] = []
  let next = 0
  for (const attempt of attempts) {
    while (next < ordered.length && attempt.attempt_no > ordered[next].after_attempt_no) {
      rows.push({ type: "divider", reset: ordered[next] })
      next += 1
    }
    rows.push({ type: "attempt", attempt, previous: attempt.attempt_no <= latestRetest })
  }
  for (; next < ordered.length; next += 1) rows.push({ type: "divider", reset: ordered[next] })
  return rows
}
