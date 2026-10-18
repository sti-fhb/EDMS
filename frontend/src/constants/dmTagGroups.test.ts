import { describe, expect, it } from "vitest"

import { DM_TAG_GROUP_LABELS, dmTagGroupLabel } from "./dmTagGroups"

describe("dmTagGroupLabel", () => {
  it("四個檢索標籤組都對應到各自的中文名", () => {
    expect(dmTagGroupLabel("MODULE")).toBe("適用模組")
    expect(dmTagGroupLabel("NATURE")).toBe("文件性質")
    expect(dmTagGroupLabel("LEGAL")).toBe("法規關聯")
    // #711 新增的第四組。漏加的症狀是畫面顯示通稱「標籤」——不會壞、只是看不出是哪一組。
    expect(dmTagGroupLabel("OTHER")).toBe("其他")
  })

  it("未知組代碼退回通稱「標籤」", () => {
    expect(dmTagGroupLabel("ZZZ")).toBe("標籤")
  })

  it("null / undefined 退回通稱「標籤」", () => {
    // ControlledOption.group_code 的型別是 string | null，editor 側還可能是 undefined。
    expect(dmTagGroupLabel(null)).toBe("標籤")
    expect(dmTagGroupLabel(undefined)).toBe("標籤")
  })

  it("對照表本身不含空字串組名", () => {
    // 空字串會讓 ?? 的 fallback 失效（空字串不是 nullish），畫面出現沒有標題的分組。
    const blank = Object.entries(DM_TAG_GROUP_LABELS).filter(([, label]) => !label)
    expect(blank).toEqual([])
  })
})
