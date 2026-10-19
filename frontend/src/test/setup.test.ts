/**
 * 釘住 `setup.ts` 的全域 testing-library 設定（#733）。
 *
 * ⚠️ 這不是「常數結構測試」。驗的不是某個常數等於某個值，而是
 * **`setup.ts` 的副作用有沒有真的套用到 testing-library 的 runtime 設定上** ——
 * 它會因為那行被刪掉、import 寫錯、或 setupFiles 沒載到而紅。
 *
 * 為什麼值得一條測試：#733 之前 `sti-testing.md` 已宣稱全域有 3000ms，
 * 但 `setup.ts` 裡**一個 `configure()` 都沒有**，實際生效的是預設 1000ms。
 * 那個假宣稱擋在追查的正前方整整數個月（「我們設過 3 秒了，所以問題不在這」）。
 * 沒有這條測試的話，同一件事可以再發生一次而且沒有任何東西會告訴你。
 */
import { getConfig } from "@testing-library/react"
import { describe, expect, it } from "vitest"

describe("全域測試設定", () => {
  it("asyncUtilTimeout 為 3000ms（findBy* 的等待預算，非 it() 的 testTimeout）", () => {
    expect(getConfig().asyncUtilTimeout).toBe(3000)
  })
})
