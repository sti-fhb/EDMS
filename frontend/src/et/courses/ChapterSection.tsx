import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core"
import type { DragEndEvent } from "@dnd-kit/core"
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import DragIndicatorIcon from "@mui/icons-material/DragIndicator"
import FolderOpenIcon from "@mui/icons-material/FolderOpen"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { ItemList } from "./ItemList"
import { moveId } from "./chapterOrder"
import type { ItemRow, ItemType } from "./itemSchemas"
import type { ChapterItem } from "./schemas"

interface ItemHandlers {
  /** 新增模式（章節尚未寫入 DB）時停用項目操作——項目須掛在已存在的章節下。 */
  itemsDisabled: boolean
  onAddItem: (chapter: ChapterItem, itemType: ItemType) => void
  onOpenItem: (item: ItemRow) => void
  onDeleteItem: (item: ItemRow) => void
  onReorderItems: (chapter: ChapterItem, orderedIds: number[]) => void
}

interface ChapterRowProps extends ItemHandlers {
  chapter: ChapterItem
  index: number
  readOnly: boolean
  onRename: (chapter: ChapterItem, name: string) => void
  onDelete: (chapter: ChapterItem) => void
}

/** 單一章節列：拖拉手把 + 章節序 + inline 更名 + 刪除。 */
function ChapterRow({
  chapter,
  index,
  readOnly,
  onRename,
  onDelete,
  itemsDisabled,
  onAddItem,
  onOpenItem,
  onDeleteItem,
  onReorderItems,
}: ChapterRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: chapter.chapter_id,
    disabled: readOnly,
  })
  const [draft, setDraft] = useState(chapter.chapter_name)

  return (
    <Paper
      ref={setNodeRef}
      variant="outlined"
      sx={{
        p: 1.5,
        mb: 1,
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        {!readOnly && (
          <Box
            {...attributes}
            {...listeners}
            sx={{ display: "flex", cursor: "grab", color: "text.disabled" }}
            aria-label={`拖曳調整「${chapter.chapter_name}」順序`}
          >
            <DragIndicatorIcon fontSize="small" />
          </Box>
        )}
        <Typography variant="body2" color="text.secondary" sx={{ minWidth: 56 }}>
          第 {index + 1} 章
        </Typography>
        <TextField
          variant="standard"
          size="small"
          fullWidth
          value={draft}
          disabled={readOnly}
          slotProps={{ htmlInput: { "aria-label": `章節名稱 ${index + 1}` } }}
          onChange={(e) => setDraft(e.target.value)}
          // 失焦才送出，避免逐字打字都打 API；名稱未變則不送
          onBlur={() => draft !== chapter.chapter_name && onRename(chapter, draft)}
        />
        {!readOnly && (
          <IconButton
            size="small"
            color="error"
            aria-label={`刪除章節 ${chapter.chapter_name}`}
            onClick={() => onDelete(chapter)}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Stack>
      <ItemList
        items={chapter.items}
        readOnly={readOnly}
        disabled={itemsDisabled}
        onAdd={(itemType) => onAddItem(chapter, itemType)}
        onOpen={onOpenItem}
        onDelete={onDeleteItem}
        onReorder={(ids) => onReorderItems(chapter, ids)}
      />
    </Paper>
  )
}

interface ChapterSectionProps extends ItemHandlers {
  chapters: ChapterItem[]
  readOnly: boolean
  /** 新增模式（課程尚未建立）時停用整區——章節須掛在已存在的課程下。 */
  disabled?: boolean
  onAdd: () => void
  onRename: (chapter: ChapterItem, name: string) => void
  onDelete: (chapter: ChapterItem) => void
  onReorder: (orderedIds: number[]) => void
}

/**
 * 章節編排區（ET02）。
 *
 * 拖拉採 `@dnd-kit`（內建鍵盤操作與 a11y）；重排一律送**完整順序陣列**而非相對移動，
 * 避免並行編輯下的順序漂移——與後端 `ensure_reorder_complete` 的契約一致。
 */
export function ChapterSection({
  chapters,
  readOnly,
  disabled = false,
  onAdd,
  onRename,
  onDelete,
  onReorder,
  ...itemHandlers
}: ChapterSectionProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const next = moveId(
      chapters.map((c) => c.chapter_id),
      Number(active.id),
      Number(over.id),
    )
    if (next) onReorder(next)
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={700}>
          章節編排
          {!readOnly && chapters.length > 0 && (
            <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              （拖拉手把可調整順序）
            </Typography>
          )}
        </Typography>
        {!readOnly && (
          <Button
            size="small"
            variant="contained"
            startIcon={<AddCircleOutlineIcon />}
            disabled={disabled}
            onClick={onAdd}
          >
            新增章節
          </Button>
        )}
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
        系統規則：學員須依序完成每個章節後才能進入下一章（強制完成邏輯系統內建，無需逐章設定）。
      </Typography>

      {chapters.length === 0 ? (
        <Stack alignItems="center" spacing={1} sx={{ py: 5, color: "text.disabled" }}>
          <FolderOpenIcon sx={{ fontSize: 40 }} />
          <Typography variant="body2" color="text.secondary" fontWeight={600}>
            尚未新增章節
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {disabled ? "請先儲存草稿後再新增章節" : "點上方「新增章節」開始建立課程內容"}
          </Typography>
        </Stack>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={chapters.map((c) => c.chapter_id)} strategy={verticalListSortingStrategy}>
            {chapters.map((chapter, index) => (
              <ChapterRow
                key={chapter.chapter_id}
                chapter={chapter}
                index={index}
                readOnly={readOnly}
                onRename={onRename}
                onDelete={onDelete}
                {...itemHandlers}
              />
            ))}
          </SortableContext>
        </DndContext>
      )}
    </Paper>
  )
}
