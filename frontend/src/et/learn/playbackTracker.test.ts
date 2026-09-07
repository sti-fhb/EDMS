import { describe, expect, it } from "vitest"

import { IDLE_TRACKER, beginSegment, checkpoint, endSegment, observeTime, seekTo } from "./playbackTracker"

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
    it("未達門檻不切段，只更新最後觀察位置", () => {
      const { segment, state } = checkpoint(beginSegment(0), 10, { minSeconds: 15 })

      expect(segment).toBeNull()
      expect(state.anchor).toBe(0)
      expect(state.last).toBe(10)
    })

    it("達門檻切出一段並從同一點續記", () => {
      const { segment, state } = checkpoint(beginSegment(0), 15.8, { minSeconds: 15 })

      expect(segment).toEqual({ start_sec: 0, end_sec: 15 })
      expect(state.anchor).toBe(15)
    })

    it("連續打點的聯集與一次送完全相同", () => {
      // 這是打點正確性的核心：切出來的段**相接**（gap = 0），後端聯集回同一個範圍。
      // 若切點之間有空隙，學員實際看過的秒數會被吃掉。
      const collected: { start_sec: number; end_sec: number }[] = []
      let state = beginSegment(0)
      for (const t of [15, 30, 45, 60]) {
        const step = checkpoint(state, t, { minSeconds: 15 })
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
      const { segment } = checkpoint(IDLE_TRACKER, 999, { minSeconds: 15 })

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
