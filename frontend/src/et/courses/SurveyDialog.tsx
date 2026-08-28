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
import CloseIcon from "@mui/icons-material/Close"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import DragIndicatorIcon from "@mui/icons-material/DragIndicator"
import EditOutlinedIcon from "@mui/icons-material/EditOutlined"
import LockIcon from "@mui/icons-material/Lock"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { moveId } from "./chapterOrder"
import { SurveyQuestionEditor } from "./SurveyQuestionEditor"
import {
  EMPTY_SURVEY_QUESTION,
  SURVEY_NAME_MAX_LEN,
  SURVEY_QUESTION_TYPE_LABEL,
  SurveyNameSchema,
  toSurveyDraft,
} from "./surveySchemas"
import type {
  SurveyDetail,
  SurveyQuestionFormValues,
  SurveyQuestionRow,
  SurveyQuestionType,
  SurveyTemplateRow,
} from "./surveySchemas"

interface QuestionRowViewProps {
  question: SurveyQuestionRow
  index: number
  locked: boolean
  onEdit: (question: SurveyQuestionRow) => void
  onDelete: (question: SurveyQuestionRow) => void
}

/** 收合態的題目列：拖拉手把 + 序號 + 題型 + 題幹 + 選項摘要 + 編輯 / 刪除。 */
function QuestionRowView({ question, index, locked, onEdit, onDelete }: QuestionRowViewProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: question.sq_id,
    disabled: locked,
  })
  const isText = question.question_type === "TEXT"

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
        <Chip
          size="small"
          variant="outlined"
          color={isText ? "secondary" : "primary"}
          label={SURVEY_QUESTION_TYPE_LABEL[question.question_type as SurveyQuestionType] ?? question.question_type}
        />
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap>
            {question.stem}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
            {/* 問答題沒有選項可摘要——留白會讓那一列看起來像壞掉的資料，改寫作答形式 */}
            {isText ? "學員以文字作答" : question.options.map((o) => o.option_text).join(" / ")}
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

interface SurveyDialogProps {
  open: boolean
  loading?: boolean
  readOnly: boolean
  survey: SurveyDetail | null
  templates: SurveyTemplateRow[]
  saving?: boolean
  error?: string | null
  onClose: () => void
  onRename: (surveyName: string) => void
  onApplyTemplate: (templateCode: string) => void
  onSaveQuestion: (sqId: number | null, values: SurveyQuestionFormValues) => void
  onDeleteQuestion: (question: SurveyQuestionRow) => void
  onReorder: (orderedIds: number[]) => void
}

/**
 * 課後問卷編輯視窗（ET02 / #238）。
 *
 * 由 #204 的 inline 展開改為 Dialog，與教材 / 測驗的操作形狀一致（2026-08-28 實測回饋）。
 * ⚠️ 這**刻意偏離 wireframe**——wireframe 的問卷區塊是 inline `wf-card`。
 *
 * ## 模板只在空問卷時出現
 *
 * 已有題目時套用模板會讓兩批題目混在一起、順序難以預期，後端亦以 `ET_SURVEY_010`
 * 擋下。此處不顯示入口是為了讓教師不必先試一次才知道不行。
 *
 * ## 凍結（沿用 #204）
 *
 * 有學員填答後題目與選項凍結，編輯入口全部收起。**問卷名稱不受此限**——
 * 名稱不影響已填答資料的意義。停用問卷的入口在卡片上（`SurveySection`），不在此視窗。
 */
export function SurveyDialog({
  open,
  loading = false,
  readOnly,
  survey,
  templates,
  saving = false,
  error = null,
  onClose,
  onRename,
  onApplyTemplate,
  onSaveQuestion,
  onDeleteQuestion,
  onReorder,
}: SurveyDialogProps) {
  /** 目前展開編輯的題目——`null` 表示新增中，`undefined` 表示未展開。 */
  const [editing, setEditing] = useState<SurveyQuestionRow | null | undefined>(undefined)
  const [nameDraft, setNameDraft] = useState<string | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const frozen = survey?.frozen ?? false
  const locked = readOnly || frozen
  const questions = survey?.questions ?? []
  const showTemplates = !locked && questions.length === 0 && editing === undefined && templates.length > 0

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const next = moveId(
      questions.map((q) => q.sq_id),
      Number(active.id),
      Number(over.id),
    )
    if (next) onReorder(next)
  }

  const commitName = () => {
    if (nameDraft === null || !survey || nameDraft === survey.survey_name) {
      setNameDraft(null)
      return
    }
    const parsed = SurveyNameSchema.safeParse(nameDraft)
    // 失敗時還原為原值而非留著壞掉的輸入——名稱是失焦即存的，
    // 留著會讓教師以為存進去了
    setNameDraft(null)
    if (parsed.success) onRename(parsed.data)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      // 固定整個對話框高度，比照 `QuizDialog`——內容多寡不同時視窗不會忽大忽小
      slotProps={{ paper: { sx: { height: "min(680px, 90vh)" } } }}
    >
      <DialogTitle sx={{ pr: 6 }}>
        {readOnly ? "檢視課後問卷" : "編輯課後問卷"}
        <IconButton
          // 名稱與底部的「關閉」刻意不同——同名會讓輔助技術與測試都分不出是哪一顆
          aria-label="關閉視窗"
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {loading || !survey ? (
          <Stack alignItems="center" sx={{ py: 6 }}>
            <CircularProgress />
          </Stack>
        ) : (
          <>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            {frozen && (
              <Alert severity="warning" icon={<LockIcon fontSize="inherit" />} sx={{ mb: 2 }}>
                已有學員填答，題目與選項已凍結。無人填答前可自由編修。
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
              onBlur={commitName}
            />

            {showTemplates && (
              <Paper variant="outlined" sx={{ p: 1.5, mb: 2, bgcolor: "background.default" }}>
                <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ display: "block", mb: 1 }}>
                  從模板開始（套用後可自由編修）
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {templates.map((template) => (
                    <Button
                      key={template.code}
                      size="small"
                      variant="outlined"
                      disabled={saving}
                      onClick={() => onApplyTemplate(template.code)}
                    >
                      {template.name}（{template.question_count} 題）
                    </Button>
                  ))}
                </Stack>
              </Paper>
            )}

            {questions.length === 0 && editing === undefined && (
              <Typography variant="caption" color="text.disabled" sx={{ display: "block", py: 1 }}>
                尚無題目——套用模板或點「新增題目」加入第一題
              </Typography>
            )}

            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={questions.map((q) => q.sq_id)} strategy={verticalListSortingStrategy}>
                {questions.map((question, index) =>
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
                      locked={locked}
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

            {!locked && editing === undefined && (
              <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => setEditing(null)}>
                新增題目
              </Button>
            )}
          </>
        )}
      </DialogContent>

      <DialogActions>
        <Typography variant="caption" color="text.secondary" sx={{ mr: "auto", pl: 1 }}>
          {survey ? `填答狀況：已填 ${survey.responded_count} / 未填 ${survey.pending_count}` : ""}
        </Typography>
        <Button onClick={onClose}>關閉</Button>
      </DialogActions>
    </Dialog>
  )
}
