import ArrowRightCircleIcon from "@mui/icons-material/ArrowCircleRight"
import CheckCircleIcon from "@mui/icons-material/CheckCircle"
import DescriptionIcon from "@mui/icons-material/Description"
import LockIcon from "@mui/icons-material/Lock"
import QuizIcon from "@mui/icons-material/Quiz"
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked"
import List from "@mui/material/List"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"
import ListSubheader from "@mui/material/ListSubheader"
import Paper from "@mui/material/Paper"
import Typography from "@mui/material/Typography"

import { itemDisplayState } from "./learnSchemas"
import type { ChapterNode, ItemNode } from "./learnSchemas"

interface Props {
  chapters: ChapterNode[]
  activeItemId: number | null
  onSelect: (item: ItemNode) => void
}

/**
 * ET05 左側章節導覽（AC 1 / AC 6）。
 *
 * 狀態 icon 三態（已完成 ✓ / 進行中 → / 鎖定 🔒）；`locked` / `completed` 自 #274 起
 * 為真值。
 *
 * ## 鎖定項目**可點但不放行**，不是 `disabled`
 *
 * `disabled` 的 `ListItemButton` 不會觸發 `onClick`，於是點下去毫無反應——而 AC 6 要的
 * 是「阻擋**並提示**」（ET-MSG-ET05-001「請先完成本章節之影片學習」）。學員需要知道
 * 為什麼點不動，否則只會以為系統壞了。
 *
 * 故一律可點、由 `onSelect` 那端判斷 `locked` 決定提示或切換；視覺上仍以 `aria-disabled`
 * 與淡化表達不可用。
 *
 * ⚠️ wireframe 的側欄底部另有「填寫課後問卷」入口——**本 issue 不做**（`ET-15` 未實作，
 * 且顯示條件需完課判定）。照抄會做出一顆永遠不會動作的按鈕。
 */
export function ChapterNav({ chapters, activeItemId, onSelect }: Props) {
  if (chapters.length === 0) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary">
          本課程尚無章節內容。
        </Typography>
      </Paper>
    )
  }

  return (
    <Paper variant="outlined" sx={{ overflow: "hidden" }}>
      <List dense disablePadding>
        {chapters.map((chapter) => (
          <li key={chapter.chapter_id}>
            <ul style={{ padding: 0, margin: 0 }}>
              <ListSubheader sx={{ bgcolor: "action.hover", lineHeight: "2.2rem" }}>
                {chapter.chapter_name}
              </ListSubheader>
              {chapter.items.map((item) => {
                const state = itemDisplayState(item, activeItemId)
                return (
                  <ListItemButton
                    key={item.item_id}
                    selected={state === "active"}
                    aria-disabled={state === "locked"}
                    onClick={() => onSelect(item)}
                    sx={state === "locked" ? { color: "text.disabled" } : undefined}
                  >
                    <ListItemIcon sx={{ minWidth: 32 }}>{stateIcon(state)}</ListItemIcon>
                    <ListItemIcon sx={{ minWidth: 28 }}>
                      {item.item_type === "QUIZ" ? (
                        <QuizIcon fontSize="small" />
                      ) : (
                        <DescriptionIcon fontSize="small" />
                      )}
                    </ListItemIcon>
                    <ListItemText primary={item.title} slotProps={{ primary: { variant: "body2" } }} />
                  </ListItemButton>
                )
              })}
            </ul>
          </li>
        ))}
      </List>
    </Paper>
  )
}

function stateIcon(state: ReturnType<typeof itemDisplayState>) {
  switch (state) {
    case "completed":
      return <CheckCircleIcon fontSize="small" color="success" />
    case "active":
      return <ArrowRightCircleIcon fontSize="small" color="primary" />
    case "locked":
      return <LockIcon fontSize="small" />
    default:
      return <RadioButtonUncheckedIcon fontSize="small" color="disabled" />
  }
}
