/** ET05 章節學習型別（對齊後端 `app/et/learning/schemas.py`）。 */

/** 章節項目類型（對齊後端 `ET_ITEM_TYPE`）。 */
export type ItemType = "MATERIAL" | "QUIZ"

export interface ItemNode {
  item_id: number
  item_type: ItemType
  sort_order: number
  title: string
  material_id: number | null
  quiz_id: number | null
  /** **本 issue 恆為 false**——解鎖判定依賴 `ET_PROGRESS`（`ET-5b`）。 */
  locked: boolean
  /** **本 issue 恆為 false**，同上。 */
  completed: boolean
}

export interface ChapterNode {
  chapter_id: number
  chapter_name: string
  sort_order: number
  items: ItemNode[]
}

export interface LearnStructure {
  course_id: number
  course_name: string
  status: string
  /** 課程擁有者（教師預覽模式，#255 裁示 Q1=A）。 */
  is_owner: boolean
  /** 課程已關閉 → 顯示唯讀提示。**不過濾內容**（#255 裁示 Q2=A）。 */
  is_closed: boolean
  /** 已依 `ET_VIDEO_PLAYBACK_MAX_RATE` 往下限縮之可選倍速。 */
  playback_rates: number[]
  chapters: ChapterNode[]
}

export interface MaterialVideoRow {
  video_id: number
  file_name: string
  duration_sec: number
  sort_order: number
}

export interface MaterialDocRow {
  doc_id: string
  doc_name: string | null
  file_name: string | null
  file_mime: string | null
  version_id: number | null
  /** 已廢止——顯示標籤但**仍可閱讀**廢止前最後版本（AC 17）。 */
  obsolete: boolean
  /** PDF → 頁內嵌入預覽；其餘走下載原檔（AC 15 / 16）。 */
  previewable: boolean
  /** DM 端取不到——顯示「文件無法取得」而非給一個點了會 404 的連結。 */
  available: boolean
  sort_order: number
}

export interface MaterialContent {
  material_id: number
  material_name: string
  description_html: string | null
  videos: MaterialVideoRow[]
  docs: MaterialDocRow[]
}

/** 側欄項目的呈現狀態。`ET-5b` 交付後 `locked` / `completed` 才會有真值。 */
export type ItemDisplayState = "completed" | "active" | "locked" | "available"

export function itemDisplayState(item: ItemNode, activeItemId: number | null): ItemDisplayState {
  if (item.item_id === activeItemId) return "active"
  if (item.completed) return "completed"
  if (item.locked) return "locked"
  return "available"
}
