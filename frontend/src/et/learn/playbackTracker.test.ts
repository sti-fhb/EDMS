// @vitest-environment node
// 純邏輯測試：不碰 DOM，**也不經 app 的 axios 發請求**——跳過 jsdom 省下建置環境的
// 開銷（#376）。⚠️ 日後若在本檔加入會發送請求的測試，請把這兩行拿掉：`http` 的
// baseURL 是相對路徑 `/api`，node 環境沒有 document origin，axios 會改走 http
// adapter 並以 `TypeError: Invalid URL` 失敗。
import { describe, expect, it } from "vitest"

import { IDLE_TRACKER, beginSegment, checkpoint, endSegment, observeTime, seekTo } from "./playbackTracker"
import type { Segment, TrackerState } from "./playbackTracker"

/**
 * 播放區段追蹤（US5 / #274）。
 *
 * 「直接拉到結尾不算看過」（FR-06）與「2 倍速照算」（FR-07）**在前端這半就要成立**，
 * 後端只做聯集去重——它收到什麼就算什麼。故這兩條在這裡驗。
 */
describe("playbackTracker", () => {
  it("正常播放一段後暫停產生該區段", () => {
    let state = beginSegment(0)
    state = observeTime(state, 45.7)
    const { segment } = endSegment(state, 45.7)

    expect(segment).toEqual({ start_sec: 0, end_sec: 45 })
  })

  it("起訖皆 floor，誤差不系統性膨脹", () => {
    // 起點 floor、終點 ceil 的話每段都會多算一秒，播十段就白送十秒
    const { segment } = endSegment(beginSegment(10.9), 20.1)

    expect(segment).toEqual({ start_sec: 10, end_sec: 20 })
  })

  it("未滿一秒不產生區段", () => {
    const { segment } = endSegment(beginSegment(30.1), 30.9)

    expect(segment).toBeNull()
  })

  it("沒有在播放時結束不產生區段", () => {
    const { segment } = endSegment(IDLE_TRACKER, 100)

    expect(segment).toBeNull()
  })

  describe("依真實瀏覽器事件順序的跳躍（#609）", () => {
    /**
     * 🔴 瀏覽器完成 seek 時**先**發 `timeupdate`（`currentTime` 已是新位置、`seeking`
     * 已為 false）**再**發 `seeked`。上面那組「跳躍」測試直接呼叫 `seekTo`，跳過了中間
     * 那個 `timeupdate`——於是它們在真實順序下**恆綠**，抓不到本 issue 的缺陷。
     *
     * 這一組照真實順序走：`checkpoint`（timeupdate）→ `seekTo`（seeked）。
     *
     * ⭐ `maxStepSec` 的誤判方向是刻意選的：**誤判為跳躍只是把一段切成兩段**，
     * 相接的兩段在後端聯集後完全相同；**漏判才是本 issue 的缺陷**（跳過的範圍被算成
     * 看過）。故門檻寧可抓緊。
     */
    const OPTS = { minSeconds: 15, maxStepSec: 1.5 }

    /**
     * 逐步播放到 `to`，模擬瀏覽器每 0.25 秒一次的 `timeupdate`。
     *
     * ⚠️ 不可寫成一次 `checkpoint(state, to)`——那個前進量會超過 `maxStepSec` 而被
     * 正確地判成跳躍。真瀏覽器播放 10 秒會發約 40 次 timeupdate。
     */
    function play(initial: TrackerState, from: number, to: number) {
      const segments: Segment[] = []
      let state = initial
      for (let t = from + 0.25; t <= to + 1e-9; t += 0.25) {
        const r = checkpoint(state, t, OPTS)
        state = r.state
        if (r.segment !== null) segments.push(r.segment)
      }
      return { state, segments }
    }

    it("播放中由 10 秒拖到 600 秒，上報的區段不涵蓋 10～600", () => {
      const played = play(beginSegment(0), 0, 10) // 正常播放 0～10 秒
      let state = played.state

      // 真實順序第 1 步：timeupdate 於新位置 600
      const jump = checkpoint(state, 600, OPTS)
      state = jump.state
      // 真實順序第 2 步：seeked
      const seeked = seekTo(state, 600, { paused: false })

      const reported = [...played.segments, jump.segment, seeked.segment].filter((x) => x !== null)
      for (const seg of reported) {
        expect(seg!.end_sec - seg!.start_sec).toBeLessThan(600)
      }
      expect(reported.some((seg) => seg!.start_sec <= 10 && seg!.end_sec >= 600)).toBe(false)
      expect(jump.segment).toEqual({ start_sec: 0, end_sec: 10 })
    })

    it("小跳距也不算看過——跳 5 秒同樣要切斷", () => {
      // 原缺陷有兩條路徑：跳距 >= 15 秒時 checkpoint 直接切出橫跨的一段；
      // 跳距 < 15 秒時 observeTime 把 last 改成新位置，之後由 seekTo 把跳過的算進去。
      let state = play(beginSegment(0), 0, 10).state

      const jump = checkpoint(state, 15, OPTS) // 拖 5 秒
      state = jump.state
      const seeked = seekTo(state, 15, { paused: false })

      expect(jump.segment).toEqual({ start_sec: 0, end_sec: 10 })
      expect(seeked.segment).toBeNull()
      expect(state.anchor).toBe(15)
    })

    it("播放中往回拖：已看的區段仍上報", () => {
      let state = play(beginSegment(100), 100, 110).state

      const jump = checkpoint(state, 20, OPTS) // 往回拖
      state = jump.state

      expect(jump.segment).toEqual({ start_sec: 100, end_sec: 110 })
      expect(state.anchor).toBe(20)
    })

    it("正常連續播放不受影響——門檻內的前進照舊累積", () => {
      // 正向錨點：少了這條，把 maxStepSec 設成 0（每次 timeupdate 都當跳躍）也會通過上面幾條
      let state = beginSegment(0)
      const emitted = []
      for (let t = 0.25; t <= 16; t += 0.25) {
        const r = checkpoint(state, t, OPTS)
        state = r.state
        if (r.segment !== null) emitted.push(r.segment)
      }
      expect(emitted).toEqual([{ start_sec: 0, end_sec: 15 }])
    })

    it("倍速放寬門檻——2 倍速下 2 秒的前進不算跳躍", () => {
      const fast = { minSeconds: 15, maxStepSec: 3 }
      const r = checkpoint(beginSegment(0), 2, fast)
      expect(r.segment).toBeNull()
      expect(r.state.anchor).toBe(0)
    })
  })

  describe("跳躍", () => {
    it("直接拉到結尾不算看過中間", () => {
      // **FR-06 的落實點**：看了 0~10，拉到 590，跳過的 10~590 兩邊都不含
      let state = beginSegment(0)
      state = observeTime(state, 10.4)
      const { segment, state: next } = seekTo(state, 590, { paused: false })

      expect(segment).toEqual({ start_sec: 0, end_sec: 10 })
      expect(next.anchor).toBe(590)
    })

    it("終點取跳躍前的位置而非跳躍後", () => {
      // `seeked` 觸發時 `currentTime` 已是新位置。拿它當終點 = 把跳過的整段算成看過。
      let state = beginSegment(0)
      state = observeTime(state, 10)
      const { segment } = seekTo(state, 500, { paused: false })

      expect(segment?.end_sec).toBe(10)
    })

    it("暫停狀態下跳躍不開始新段", () => {
      // 學員暫停後拖動進度條找位置——那期間沒有播放，不該產生任何觀看紀錄
      let state = beginSegment(0)
      state = observeTime(state, 30)
      const { state: next } = seekTo(state, 200, { paused: true })

      expect(next).toEqual(IDLE_TRACKER)
    })

    it("多次跳躍只留下實際播放過的片段", () => {
      const collected = []
      let state = beginSegment(0)
      state = observeTime(state, 20)
      let step = seekTo(state, 100, { paused: false })
      collected.push(step.segment)

      state = observeTime(step.state, 130)
      step = seekTo(state, 400, { paused: false })
      collected.push(step.segment)

      expect(collected).toEqual([
        { start_sec: 0, end_sec: 20 },
        { start_sec: 100, end_sec: 130 },
      ])
    })
  })

  describe("播放中定期打點", () => {
    /**
     * 本組一律傳 `maxStepSec: Infinity`——它們驗的是**15 秒打點門檻**，不是跳躍偵測。
     *
     * 這些測試刻意用大步長（一次 `checkpoint` 就跨 10～16 秒）來逼近門檻，而那種步長在
     * 真實瀏覽器中只會出現在拖動進度條。關掉跳躍偵測才能讓本組繼續只驗它原本要驗的事；
     * 跳躍本身由「依真實瀏覽器事件順序的跳躍（#609）」那一組負責。
     */
    it("未達門檻不切段，只更新最後觀察位置", () => {
      const { segment, state } = checkpoint(beginSegment(0), 10, { minSeconds: 15, maxStepSec: Infinity })

      expect(segment).toBeNull()
      expect(state.anchor).toBe(0)
      expect(state.last).toBe(10)
    })

    it("達門檻切出一段並從同一點續記", () => {
      const { segment, state } = checkpoint(beginSegment(0), 15.8, { minSeconds: 15, maxStepSec: Infinity })

      expect(segment).toEqual({ start_sec: 0, end_sec: 15 })
      expect(state.anchor).toBe(15)
    })

    it("連續打點的聯集與一次送完全相同", () => {
      // 這是打點正確性的核心：切出來的段**相接**（gap = 0），後端聯集回同一個範圍。
      // 若切點之間有空隙，學員實際看過的秒數會被吃掉。
      const collected: { start_sec: number; end_sec: number }[] = []
      let state = beginSegment(0)
      for (const t of [15, 30, 45, 60]) {
        const step = checkpoint(state, t, { minSeconds: 15, maxStepSec: Infinity })
        state = step.state
        if (step.segment) collected.push(step.segment)
      }

      expect(collected).toEqual([
        { start_sec: 0, end_sec: 15 },
        { start_sec: 15, end_sec: 30 },
        { start_sec: 30, end_sec: 45 },
        { start_sec: 45, end_sec: 60 },
      ])
      // 相接 → 聯集為 [0,60]，與「一路播完才送一次」等價
      expect(collected[0].start_sec).toBe(0)
      expect(collected.at(-1)?.end_sec).toBe(60)
      collected.forEach((seg, i) => {
        if (i > 0) expect(seg.start_sec).toBe(collected[i - 1].end_sec)
      })
    })

    it("沒有在播放時不打點", () => {
      const { segment } = checkpoint(IDLE_TRACKER, 999, { minSeconds: 15, maxStepSec: Infinity })

      expect(segment).toBeNull()
    })
  })

  it("倍速依影片時間軸而非牆鐘時間", () => {
    // FR-07：2 倍速播 300 秒牆鐘 = 600 秒影片時間。`currentTime` 走的就是影片時間軸，
    // 故倍速自然照算——前端與後端都不需要知道倍速是多少。
    let state = beginSegment(0)
    state = observeTime(state, 600)
    const { segment } = endSegment(state, 600)

    expect(segment).toEqual({ start_sec: 0, end_sec: 600 })
  })

  it("暫停期間的 timeupdate 不污染下一段", () => {
    // 沒有在播放時就記位置的話，seek 後的位置會被當成上一段的終點
    const idle = observeTime(IDLE_TRACKER, 999)

    expect(idle).toEqual(IDLE_TRACKER)
  })
})
