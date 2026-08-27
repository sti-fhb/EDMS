import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core"
import type { DragEndEvent } from "@dnd-kit/core"
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import AddIcon from "@mui/icons-material/Add"
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined"
import ChecklistIcon from "@mui/icons-material/Checklist"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import DragIndicatorIcon from "@mui/icons-material/DragIndicator"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { moveId } from "./chapterOrder"
import { ITEM_TYPE_LABEL, UNNAMED_ITEM_LABEL } from "./itemSchemas"
import type { ItemRow, ItemType } from "./itemSchemas"

interface ItemRowViewProps {
  item: ItemRow
  readOnly: boolean
  onOpen: (item: ItemRow) => void
  onDelete: (item: ItemRow) => void
}

/** 單一項目列：拖拉手把 + 類型標記 + 名稱（點擊開視窗）+ 刪除。 */
function ItemRowView({ item, readOnly, onOpen, onDelete }: ItemRowViewProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.item_id,
    disabled: readOnly,
  })
  const isMaterial = item.item_type === "MATERIAL"

  return (
    <Paper
      ref={setNodeRef}
      variant="outlined"
      sx={{
        p: 1,
        mb: 0.75,
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
        bgcolor: "background.default",
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        {!readOnly && (
          <Box
            {...attributes}
            {...listeners}
            sx={{ display: "flex", cursor: "grab", color: "text.disabled" }}
            aria-label={`拖曳調整「${item.title || UNNAMED_ITEM_LABEL}」順序`}
          >
            <DragIndicatorIcon fontSize="small" />
          </Box>
        )}
        <Chip
          size="small"
          variant="outlined"
          color={isMaterial ? "success" : "info"}
          icon={isMaterial ? <ArticleOutlinedIcon /> : <ChecklistIcon />}
          label={ITEM_TYPE_LABEL[item.item_type as ItemType] ?? item.item_type}
        />
        <Button
          size="small"
          variant="text"
          sx={{ flexGrow: 1, justifyContent: "flex-start", textAlign: "left", minWidth: 0 }}
          onClick={() => onOpen(item)}
        >
          {/* 名稱可為空（剛建立、還沒填）——顯示佔位文字而非留一片空白，
              否則那一列看起來像壞掉的資料 */}
          <Typography
            variant="body2"
            noWrap
            color={item.title ? "inherit" : "text.disabled"}
            fontStyle={item.title ? undefined : "italic"}
          >
            {item.title || UNNAMED_ITEM_LABEL}
          </Typography>
        </Button>
        {!readOnly && (
          <IconButton
            size="small"
            color="error"
            aria-label={`刪除項目 ${item.title || UNNAMED_ITEM_LABEL}`}
            onClick={() => onDelete(item)}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Stack>
    </Paper>
  )
}

interface ItemListProps {
  items?: ItemRow[]
  readOnly: boolean
  /** 新增模式（章節尚未建立於後端）時停用——項目須掛在已存在的章節下。 */
  disabled?: boolean
  onAdd: (itemType: ItemType) => void
  onOpen: (item: ItemRow) => void
  onDelete: (item: ItemRow) => void
  onReorder: (orderedIds: number[]) => void
}

/**
 * 章節內項目清單（教材 / 測驗）。
 *
 * 拖拉重排一律送**完整順序陣列**，與後端 `ensure_item_reorder_complete` 的契約一致
 * （相對移動在並行編輯時會疊加出非預期結果）。
 */
export function ItemList({
  // 預設空陣列：後端恆回此欄位，但少一個欄位不該讓整個課程編輯頁變成白畫面——
  // 降級成「這個章節沒有項目」比整頁崩潰好得多
  items = [],
  readOnly,
  disabled = false,
  onAdd,
  onOpen,
  onDelete,
  onReorder,
}: ItemListProps) {
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const next = moveId(
      items.map((i) => i.item_id),
      Number(active.id),
      Number(over.id),
    )
    if (next) onReorder(next)
  }

  const pick = (itemType: ItemType) => {
    setMenuAnchor(null)
    onAdd(itemType)
  }

  return (
    <Box sx={{ pl: { xs: 0, sm: 4 }, pt: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          章節項目{items.length > 0 && `（${items.length}）`}
        </Typography>
        {!readOnly && (
          <>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              disabled={disabled}
              aria-haspopup="menu"
              onClick={(e) => setMenuAnchor(e.currentTarget)}
            >
              新增項目
            </Button>
            <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)}>
              <MenuItem onClick={() => pick("MATERIAL")}>
                <ListItemIcon>
                  <ArticleOutlinedIcon fontSize="small" color="success" />
                </ListItemIcon>
                <ListItemText primary="教材" secondary="影片 / 文件 / 說明文字" />
              </MenuItem>
              <MenuItem onClick={() => pick("QUIZ")}>
                <ListItemIcon>
                  <ChecklistIcon fontSize="small" color="info" />
                </ListItemIcon>
                <ListItemText primary="測驗" secondary="題目與配分" />
              </MenuItem>
            </Menu>
          </>
        )}
      </Stack>

      {items.length === 0 ? (
        <Typography variant="caption" color="text.disabled" sx={{ display: "block", py: 1 }}>
          {disabled ? "請先儲存草稿後再新增項目" : "尚無項目——點「新增項目」加入教材或測驗"}
        </Typography>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((i) => i.item_id)} strategy={verticalListSortingStrategy}>
            {items.map((item) => (
              <ItemRowView
                key={item.item_id}
                item={item}
                readOnly={readOnly}
                onOpen={onOpen}
                onDelete={onDelete}
              />
            ))}
          </SortableContext>
        </DndContext>
      )}
    </Box>
  )
}
