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
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import DragIndicatorIcon from "@mui/icons-material/DragIndicator"
import EditOutlinedIcon from "@mui/icons-material/EditOutlined"
import LockIcon from "@mui/icons-material/Lock"
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { moveId } from "./chapterOrder"
import { SurveyQuestionEditor } from "./SurveyQuestionEditor"
import { EMPTY_SURVEY_QUESTION, SURVEY_NAME_MAX_LEN, SurveyNameSchema, toSurveyDraft } from "./surveySchemas"
import type { SurveyDetail, SurveyQuestionFormValues, SurveyQuestionRow } from "./surveySchemas"

interface QuestionRowViewProps {
  question: SurveyQuestionRow
  index: number
  frozen: boolean
  readOnly: boolean
  onEdit: (question: SurveyQuestionRow) => void
  onDelete: (question: SurveyQuestionRow) => void
}

/** 收合態的題目列：拖拉手把 + 序號 + 題幹 + 選項摘要 + 編輯 / 刪除。 */
function QuestionRowView({ question, index, frozen, readOnly, onEdit, onDelete }: QuestionRowViewProps) {
  const locked = frozen || readOnly
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: question.sq_id,
    disabled: locked,
  })

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
        {!locked && (
          <Box
            {...attributes}
            {...listeners}
            sx={{ display: "flex", cursor: "grab", color: "text.disabled" }}
            aria-label={`拖曳調整第 ${index + 1} 題順序`}
          >
            <DragIndicatorIcon fontSize="small" />
          </Box>
        )}
        <Typography variant="body2" fontWeight={600} sx={{ minWidth: 32 }}>
          Q{index + 1}
        </Typography>
        <Chip size="small" variant="outlined" color="primary" label="單選" />
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap>
            {question.stem}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
            {question.options.map((o) => o.option_text).join(" / ")}
          </Typography>
        </Box>
        {!locked && (
          <>
            <IconButton size="small" aria-label={`編輯第 ${index + 1} 題`} onClick={() => onEdit(question)}>
              <EditOutlinedIcon fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              color="error"
              aria-label={`刪除第 ${index + 1} 題`}
              onClick={() => onDelete(question)}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </>
        )}
      </Stack>
    </Paper>
  )
}

interface SurveySectionProps {
  /** `null` = 尚未建立問卷（正常狀態，非錯誤）；`undefined` = 尚在載入。 */
  survey: SurveyDetail | null | undefined
  readOnly: boolean
  /** 新增模式（課程尚未建立於後端）時停用——問卷須掛在已存在的課程下。 */
  disabled?: boolean
  saving?: boolean
  error?: string | null
  onCreate: (surveyName: string) => void
  onRename: (surveyName: string) => void
  onDeactivate: () => void
  onSaveQuestion: (sqId: number | null, values: SurveyQuestionFormValues) => void
  onDeleteQuestion: (question: SurveyQuestionRow) => void
  onReorder: (orderedIds: number[]) => void
}

/**
 * ET02 課後問卷區塊（US3 / #204）。
 *
 * ## 凍結（AC 21）
 *
 * 一旦有學員填答，題目與選項即凍結——拖拉手把、編輯 / 刪除鈕、「新增題目」全部收起。
 * **但問卷名稱與「停用問卷」仍可用**：AC 21 明訂此時教師「僅可停用問卷」，把停用也
 * 鎖掉等於整張卡片變成死的。後端另以 `ET_SURVEY_003` 把關，前端隱藏僅為 UX。
 *
 * ## 沒有「刪除問卷」
 *
 * SA 裁示（#204 Q1 → B）：問卷只能停用。後端亦無對應端點。
 */
export function SurveySection({
  survey,
  readOnly,
  disabled = false,
  saving = false,
  error = null,
  onCreate,
  onRename,
  onDeactivate,
  onSaveQuestion,
  onDeleteQuestion,
  onReorder,
}: SurveySectionProps) {
  /** 目前展開編輯的題目——`null` 表示新增中，`undefined` 表示未展開。 */
  const [editing, setEditing] = useState<SurveyQuestionRow | null | undefined>(undefined)
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [nameError, setNameError] = useState("")

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const frozen = survey?.frozen ?? false
  const editable = !readOnly && !frozen

  const header = (
    <Typography variant="subtitle2" fontWeight={700}>
      課後問卷{" "}
      <Typography component="span" variant="caption" color="text.secondary" fontWeight={400}>
        （選配；一門課程 0～1 份）
      </Typography>
    </Typography>
  )

  // ── 尚未建立 ────────────────────────────────────────────────────────────
  if (survey === null || survey === undefined) {
    const creating = nameDraft !== null
    return (
      <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          {header}
          {!readOnly && !creating && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              disabled={disabled || survey === undefined}
              onClick={() => {
                setNameError("")
                // 空字串而非預設名稱——#203 實測回饋：不要幫使用者填預設值
                setNameDraft("")
              }}
            >
              新增問卷
            </Button>
          )}
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          學員完課後開放填寫（具名、一人一次）。填寫問卷不是完課條件、不計入學習進度。
        </Typography>

        {creating ? (
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField
              autoFocus
              size="small"
              label="問卷名稱"
              required
              fullWidth
              value={nameDraft}
              error={Boolean(nameError)}
              helperText={nameError}
              slotProps={{ htmlInput: { maxLength: SURVEY_NAME_MAX_LEN } }}
              onChange={(e) => setNameDraft(e.target.value)}
            />
            <Button size="small" onClick={() => setNameDraft(null)}>
              取消
            </Button>
            <Button
              size="small"
              variant="contained"
              disabled={saving}
              onClick={() => {
                const parsed = SurveyNameSchema.safeParse(nameDraft ?? "")
                if (!parsed.success) {
                  setNameError(parsed.error.issues[0]?.message ?? "問卷名稱不正確")
                  return
                }
                setNameError("")
                setNameDraft(null)
                onCreate(parsed.data)
              }}
            >
              建立
            </Button>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.disabled" sx={{ display: "block", py: 1 }}>
            {disabled ? "請先儲存草稿後再新增問卷" : "尚未建立課後問卷"}
          </Typography>
        )}
      </Paper>
    )
  }

  // ── 已建立 ──────────────────────────────────────────────────────────────
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const next = moveId(
      survey.questions.map((q) => q.sq_id),
      Number(active.id),
      Number(over.id),
    )
    if (next) onReorder(next)
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        {header}
        <Stack direction="row" spacing={1} alignItems="center">
          {!survey.is_active && <Chip size="small" color="default" label="已停用" />}
          {/* 停用**不受凍結限制**——AC 21 明訂凍結後教師僅可停用問卷 */}
          {!readOnly && survey.is_active && (
            <Button
              size="small"
              color="warning"
              variant="outlined"
              startIcon={<PauseCircleOutlineIcon />}
              disabled={saving}
              onClick={onDeactivate}
            >
              停用問卷
            </Button>
          )}
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      {frozen && (
        <Alert severity="warning" icon={<LockIcon fontSize="inherit" />} sx={{ mb: 1 }}>
          已有學員填答，題目與選項已凍結（僅可停用問卷）。無人填答前可自由編修。
        </Alert>
      )}

      <TextField
        size="small"
        label="問卷名稱"
        fullWidth
        sx={{ mb: 2, maxWidth: 380 }}
        disabled={readOnly}
        value={nameDraft ?? survey.survey_name}
        slotProps={{ htmlInput: { maxLength: SURVEY_NAME_MAX_LEN } }}
        onChange={(e) => setNameDraft(e.target.value)}
        onBlur={() => {
          if (nameDraft === null || nameDraft === survey.survey_name) {
            setNameDraft(null)
            return
          }
          const parsed = SurveyNameSchema.safeParse(nameDraft)
          if (!parsed.success) {
            // 還原為原值而非留著壞掉的輸入——名稱是失焦即存的，留著會讓使用者以為存了
            setNameDraft(null)
            return
          }
          setNameDraft(null)
          onRename(parsed.data)
        }}
      />

      {survey.questions.length === 0 && editing === undefined && (
        <Typography variant="caption" color="text.disabled" sx={{ display: "block", py: 1 }}>
          尚無題目——點「新增題目」加入第一題
        </Typography>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={survey.questions.map((q) => q.sq_id)} strategy={verticalListSortingStrategy}>
          {survey.questions.map((question, index) =>
            editing?.sq_id === question.sq_id ? (
              <Box key={question.sq_id} sx={{ mb: 0.75 }}>
                <SurveyQuestionEditor
                  initial={toSurveyDraft(question)}
                  saving={saving}
                  onSave={(values) => {
                    setEditing(undefined)
                    onSaveQuestion(question.sq_id, values)
                  }}
                  onCancel={() => setEditing(undefined)}
                />
              </Box>
            ) : (
              <QuestionRowView
                key={question.sq_id}
                question={question}
                index={index}
                frozen={frozen}
                readOnly={readOnly}
                onEdit={setEditing}
                onDelete={onDeleteQuestion}
              />
            ),
          )}
        </SortableContext>
      </DndContext>

      {editing === null && (
        <Box sx={{ mb: 0.75 }}>
          <SurveyQuestionEditor
            initial={EMPTY_SURVEY_QUESTION}
            saving={saving}
            onSave={(values) => {
              setEditing(undefined)
              onSaveQuestion(null, values)
            }}
            onCancel={() => setEditing(undefined)}
          />
        </Box>
      )}

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1 }}>
        {editable && editing === undefined ? (
          <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => setEditing(null)}>
            新增題目
          </Button>
        ) : (
          <Box />
        )}
        <Typography variant="caption" color="text.secondary">
          填答狀況：已填 {survey.responded_count} / 未填 {survey.pending_count}
        </Typography>
      </Stack>
    </Paper>
  )
}
