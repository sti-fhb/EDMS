/**
 * 播放區段追蹤（US5 / #274）——**前端這半的三條覆蓋率規則**。
 *
 * ## 三條規則其實是同一個決定
 *
 * | 規則 | spec | 由誰滿足 |
 * |---|---|---|
 * | 2 倍速看完全片 = 100% | FR-07 | **本模組**：記的是 `currentTime`（影片時間軸）|
 * | 直接拉到結尾不算看過 | FR-06 | **本模組**：跳躍不產生區段 |
 * | 重複觀看不加成 | FR-06 | 後端聯集去重 |
 *
 * 合起來就是：**只記錄「播放頭實際走過的影片時間軸範圍」**。
 *
 * ## 為何不用 `timeupdate` 累加
 *
 * `timeupdate` 每秒觸發約 4 次。用它累加等於在前端做聯集，而前端手上沒有既有區段可
 * 比對——學員第二次看同一段時，前端無從得知那段已經看過。聯集必須在後端做。
 *
 * 本模組用 `timeupdate` 記下「最後觀察到的播放位置」。
 *
 * ## 🔴 跳躍必須在 `timeupdate` 偵測，不能等 `seeked`（#609）
 *
 * 本模組原本假設「`seeked` 時 `state.last` 還是跳躍前的位置」。**那個前提是錯的**：
 * 依 HTML 規格，瀏覽器完成 seek 時**先**發 `timeupdate`（`currentTime` 已是新位置、
 * `seeking` 已為 false）**再**發 `seeked`。於是 `observeTime` 早就把 `last` 覆寫成新
 * 位置，`seekTo` 拿它當終點等於把跳過的整段算成看過——0 秒播到 10 秒再拖到 600 秒，
 * 上報 `[0,600]`、覆蓋率約 97%，項目直接完成。
 *
 * 故改為在 `checkpoint`（即 `timeupdate` 的進入點）比對位置是否連續：**不連續就以
 * 跳躍前的位置收掉前一段、從新位置重新起算**。`seekTo` 保留，負責暫停中跳躍等
 * `timeupdate` 不會發生的情形。
 *
 * ⭐ `maxStepSec` 的誤判方向是刻意選的：**誤判為跳躍只是把一段切成兩段**，相接的兩段
 * 經後端聯集後完全相同；**漏判才是缺陷**（跳過的範圍被算成看過）。故門檻寧可抓緊。
 *
 * ## 為何是純函式而非 class
 *
 * 這裡是本 issue 前端唯一有邏輯的地方，其餘都是接線。純函式讓「拉到結尾不算看過」
 * 這條可以在完全不碰 `<video>` 的情況下驗完——用 jsdom 模擬 media 事件既慢又不可靠
 * （jsdom 不實作播放）。
 */

/** 一段實際播放過的影片時間軸範圍（秒，整數）。 */
export interface Segment {
  start_sec: number
  end_sec: number
}

/**
 * 追蹤狀態。
 *
 * @property anchor 目前這段播放的起點；`null` = 沒有正在播放的段落。
 * @property last 最後觀察到的播放位置——`seeked` 時用它當作**跳躍前**的終點。
 */
export interface TrackerState {
  readonly anchor: number | null
  readonly last: number
}

export const IDLE_TRACKER: TrackerState = { anchor: null, last: 0 }

/**
 * 取整一律 `floor`。
 *
 * `START_SEC` / `END_SEC` 為 `INT`，而 `currentTime` 是浮點數。起訖點同方向取整，
 * 誤差每段至多 1 秒且**不會系統性膨脹**——若起點 floor、終點 ceil，每段都會多算一秒，
 * 一支影片播十段就白送十秒。
 */
function floorSec(seconds: number): number {
  return Math.max(0, Math.floor(seconds))
}

/** `play` / `playing`：記下起點。 */
export function beginSegment(currentTime: number): TrackerState {
  return { anchor: floorSec(currentTime), last: currentTime }
}

/** `timeupdate`：更新最後觀察位置。**沒有在播放時不記**——那會讓 seek 後的位置污染下一段。 */
export function observeTime(state: TrackerState, currentTime: number): TrackerState {
  if (state.anchor === null) return state
  return { ...state, last: currentTime }
}

/**
 * 結束目前這段。
 *
 * @param endAt 終點；`seeked` 要傳**跳躍前**的位置（即 `state.last`），其餘事件傳當下的
 *   `currentTime`。
 * @returns 新狀態與產生的區段；長度不足 1 秒者回 `null`（不值得送、後端也會拒收
 *   `end_sec <= start_sec`）。
 */
export function endSegment(state: TrackerState, endAt: number): { state: TrackerState; segment: Segment | null } {
  if (state.anchor === null) return { state, segment: null }
  const start = state.anchor
  const end = floorSec(endAt)
  const segment = end > start ? { start_sec: start, end_sec: end } : null
  return { state: IDLE_TRACKER, segment }
}

/**
 * 播放中的定期打點：把「起點 → 現在」切出來送，並**從同一點繼續記**。
 *
 * ## 為什麼需要它
 *
 * `pause` / `seeked` / `ended` 都是「停下來」才觸發的事件。學員從頭播到尾都不暫停時，
 * 整段觀看在結束前**一次都不會上報**——畫面上的覆蓋率會一路停在進頁時的舊值（看起來
 * 像壞掉），而瀏覽器若在播放中被關掉，那整段就永久遺失。
 *
 * ## 這不是「用 `timeupdate` 累加」
 *
 * 模組 docstring 警告的是「在前端把秒數加總當成覆蓋率」——前端沒有既有區段可比對，
 * 做不出聯集。這裡送的仍是**播放頭實際走過的精確範圍**，只是切成好幾段：
 * `[0,15]`、`[15,30]`、`[30,45]`⋯ 相接（gap = 0），後端聯集回 `[0,45]`，
 * 結果與一次送完全相同。
 *
 * ## 它同時是跳躍的偵測點（#609）
 *
 * 見模組 docstring：`seeked` 來得太晚，`last` 那時已被覆寫。位置若與上次觀察不連續，
 * 就在這裡以**跳躍前**的位置收段、從新位置重記。
 *
 * @param minSeconds 距離目前起點至少要走過幾秒才切一段；未達則原樣返回。
 * @param maxStepSec 兩次 `timeupdate` 之間允許的最大前進量（影片秒）。超過、或位置
 *   倒退，即視為跳躍。應依 `playbackRate` 放寬——2 倍速下同樣的牆鐘間隔會走兩倍的
 *   影片時間。
 */
export function checkpoint(
  state: TrackerState,
  currentTime: number,
  { minSeconds, maxStepSec }: { minSeconds: number; maxStepSec: number },
): { state: TrackerState; segment: Segment | null } {
  if (state.anchor === null) return { state, segment: null }

  // 不連續 ⇒ 跳躍。終點取 `state.last`（跳躍前），新段自 `currentTime` 起算；
  // 跳過的範圍夾在兩者之間、兩邊都不含它，故完全不產生區段（FR-06）。
  const advance = currentTime - state.last
  if (advance < 0 || advance > maxStepSec) {
    const { segment } = endSegment(state, state.last)
    return { state: beginSegment(currentTime), segment }
  }

  if (floorSec(currentTime) - state.anchor < minSeconds) {
    return { state: observeTime(state, currentTime), segment: null }
  }
  const { segment } = endSegment(state, currentTime)
  // 從同一點重新起算——相接而不重疊，故聯集不變、也不會有沒看過的秒數被算進去
  return { state: beginSegment(currentTime), segment }
}

/**
 * `seeked`：先結束「跳之前那一段」，再視情況從新位置重記起點。
 *
 * **這是「直接拉到結尾不算看過」的落實點**（FR-06）：跳過的範圍夾在舊段的終點與新段的
 * 起點之間，兩邊都不含它，於是完全不產生區段。
 *
 * 終點取 `state.last`（最後一次 `timeupdate` 的位置）而**不是** `currentTime`——後者在
 * `seeked` 觸發時已經是跳躍後的新位置，拿它當終點等於把跳過的整段算成看過了。
 */
export function seekTo(
  state: TrackerState,
  newTime: number,
  { paused }: { paused: boolean },
): { state: TrackerState; segment: Segment | null } {
  const ended = endSegment(state, state.last)
  return { state: paused ? IDLE_TRACKER : beginSegment(newTime), segment: ended.segment }
}
