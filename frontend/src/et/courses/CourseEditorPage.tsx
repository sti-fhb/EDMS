import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"
import FormControlLabel from "@mui/material/FormControlLabel"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Switch from "@mui/material/Switch"
import Tooltip from "@mui/material/Tooltip"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs"
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker"
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import dayjs from "dayjs"
import type { Dayjs } from "dayjs"
import { useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { ChapterSection } from "./ChapterSection"
import { MaterialDialog } from "./MaterialDialog"
import { QuizDialog } from "./QuizDialog"
import { coursesApi } from "./coursesService"
import type { MaterialSavePayload } from "./MaterialDialog"
import { ItemTitleSchema } from "./itemSchemas"
import type { ItemRow, ItemType, QuestionFormValues, QuestionRow } from "./itemSchemas"
import { itemsApi, materialsApi, quizzesApi } from "./itemsService"
import {
  COURSE_STATUS_LABEL,
  ChapterNameSchema,
  CourseFormSchema,
  DESCRIPTION_MAX_LEN,
  type ChapterItem,
  type CourseDetail,
  type CoursePayload,
} from "./schemas"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/** 樂觀鎖衝突之 error code——後端 `ensure_version_matched` 於版本不符時回此碼。 */
const LOCK_CONFLICT = "ET_LOCK_001"

const EMPTY_FORM = {
  course_name: "",
  description: "",
  require_approval: false,
  tag_ids: [] as number[],
}

/**
 * ET02 課程建立與編輯——**課程骨架與章節編排**（US3 / #202）。
 *
 * 教材 / 測驗屬 #203、課後問卷與發布屬 #204，故本頁動作列只有「取消 / 儲存草稿」，
 * 尚無「儲存並發布」。
 *
 * **非擁有者為唯讀**（`spec.md` §擁有權判定）：顯示檢視模式提示，所有輸入停用、
 * 操作按鈕不顯示。後端另以 `ET_COURSE_002` 把關，前端隱藏僅為 UX。
 */
export function EtCourseEditorPage() {
  const { courseId: courseIdParam } = useParams<{ courseId: string }>()
  const courseId = courseIdParam ? Number(courseIdParam) : undefined
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { message, confirm } = useNotification()

  const [form, setForm] = useState(EMPTY_FORM)
  const [startAt, setStartAt] = useState<Dayjs | null>(null)
  const [endAt, setEndAt] = useState<Dayjs | null>(null)
  // 載入時的原值——「起始須 ≥ 當下」只對**使用者這次改動的值**成立（SA 裁示）。
  // 已發布課程的起始必然落在過去，無條件檢核會讓它之後永遠存不了檔。
  const [originalStart, setOriginalStart] = useState<string | null>(null)
  // 新增模式之章節暫存：章節有 COURSE_ID 外鍵、課程不存在時掛不上去，
  // 故先存在畫面上，儲存時連同課程一次送出（後端於同一交易內建立）。
  //
  // ⚠️ **id 必須穩定、不可由索引推導**：`ChapterRow` 以 `chapter_id` 當 React key 且
  // 內部以 state 保存章節名草稿。若 id 為 `-(index + 1)`，拖拉後陣列順序變了但 key 仍
  // 照位置排列，React 會重用同一批元件實例、其內部草稿不更新——畫面看起來「拖了沒動」。
  const [stagedChapters, setStagedChapters] = useState<{ id: number; name: string }[]>([])
  const nextStagedId = useRef(-1)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [conflictOpen, setConflictOpen] = useState(false)
  const [chapterDialogOpen, setChapterDialogOpen] = useState(false)
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterError, setChapterError] = useState("")
  /** 目前開啟的項目視窗——`null` 表示未開啟。 */
  const [openItem, setOpenItem] = useState<ItemRow | null>(null)
  const [itemError, setItemError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const {
    data: course,
    error: courseError,
    isLoading: courseLoading,
  } = useQuery({
    queryKey: QUERY_KEYS.etCourses.detail(courseId ?? 0),
    queryFn: () => coursesApi.getDetail(courseId as number),
    enabled: courseId !== undefined,
    // 403 / 404 重試沒有意義，只會延後畫面上的錯誤呈現
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })
  const { data: tagOptions = [] } = useQuery({
    queryKey: QUERY_KEYS.etCourses.tags(courseId),
    queryFn: () => coursesApi.listTags(courseId),
  })

  // 由查詢結果衍生表單初值——**於 render 期間同步，不放 useEffect**。
  // 除了 effect 內 setState 會造成串聯 render 之外，更實際的問題是：每次 refetch
  // （新增章節後 invalidate 即會觸發）都重設表單，會把使用者正在輸入的內容蓋掉。
  // 只在「載入到另一門課程」時同步，重新整理既有課程不動使用者已改的欄位。
  const [loadedCourseId, setLoadedCourseId] = useState<number | null>(null)
  if (course && loadedCourseId !== course.course_id) {
    setLoadedCourseId(course.course_id)
    setForm({
      course_name: course.course_name,
      description: course.description ?? "",
      require_approval: course.require_approval,
      tag_ids: course.tag_ids,
    })
    setStartAt(course.open_start_at ? dayjs(course.open_start_at) : null)
    setEndAt(course.open_end_at ? dayjs(course.open_end_at) : null)
    setOriginalStart(course.open_start_at)
  }

  const isNew = courseId === undefined
  const readOnly = course !== undefined && !course.is_owner
  // 新增模式以負數 id 表示暫存章節（尚未寫入 DB）；index = -id - 1
  const chapters: ChapterItem[] = isNew
    ? stagedChapters.map((c, i) => ({
        chapter_id: c.id,
        chapter_name: c.name,
        sort_order: i + 1,
        version: 0,
        // 暫存章節尚未寫入 DB，掛不了項目——ItemList 於新增模式停用
        items: [],
      }))
    : (course?.chapters ?? [])
  const status = course?.status ?? "DRAFT"

  /** 版本衝突以 Dialog 呈現而非 snackbar——使用者必須確實知道自己的編輯沒存進去。 */
  const handleError = (err: unknown) => {
    const { errorCode, errorMessage } = toApiError(err)
    if (errorCode === LOCK_CONFLICT) {
      setConflictOpen(true)
      return
    }
    message.error(errorMessage)
  }

  const invalidate = () => {
    if (courseId !== undefined) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.detail(courseId) })
    }
  }

  /** 起始時間是否被使用者改動——決定送出前要不要驗「不得早於當下」。 */
  const startChanged = (startAt?.toISOString() ?? null) !== originalStart

  /**
   * 起始時間可選範圍的下限——**一開始就套用**，過去的時間即為灰底不可選。
   *
   * 例外：課程已開課（原起始落在過去）時，下限放寬到**原值**而非當下。否則已開課課程
   * 一進編輯頁，既有的起始時間就落在不可選範圍內，教師無從沿用（AC 28 允許已發布課程
   * 繼續編輯）。放寬到原值仍擋住「把開課時間再往前挪」。
   */
  const startedInPast = originalStart !== null && dayjs(originalStart).isBefore(dayjs())
  const startFloor = startedInPast ? dayjs(originalStart) : dayjs()

  const toPayload = (): CoursePayload => ({
    course_name: form.course_name.trim(),
    description: form.description.trim() || null,
    // Dayjs → ISO 8601（含時區）；後端欄位為 TIMESTAMPTZ，送 naive 值會被以連線時區
    // 解讀而靜默位移，使「起始時間前學員不可見」等時間判定算錯。
    open_start_at: startAt?.toISOString() ?? null,
    open_end_at: endAt?.toISOString() ?? null,
    require_approval: form.require_approval,
    tag_ids: form.tag_ids,
  })

  const saveMut = useMutation({
    mutationFn: async () => {
      if (isNew) return coursesApi.create({ ...toPayload(), chapters: stagedChapters.map((c) => c.name) })
      await coursesApi.update(courseId, { ...toPayload(), version: course?.version ?? 0 })
      return undefined
    },
    onSuccess: () => {
      message.success("草稿已儲存")
      // 對齊 wireframe「儲存後：回到課程列表卡片網格」；新增 / 編輯皆同。
      // 章節是各自即時儲存的，不會因離開編輯頁而遺失。
      navigate("/et/courses")
    },
    onError: handleError,
  })

  const chapterMut = useMutation({
    mutationFn: async (action: () => Promise<unknown>) => action(),
    onSuccess: invalidate,
    onError: (err) => {
      handleError(err)
      invalidate() // 還原樂觀更新（如重排失敗）
    },
  })

  const handleSave = () => {
    const parsed = CourseFormSchema.safeParse(form)
    if (!parsed.success) {
      const next: Record<string, string> = {}
      for (const issue of parsed.error.issues) {
        const key = String(issue.path[0])
        if (!next[key]) next[key] = issue.message
      }
      setErrors(next)
      return
    }
    // 時間規則（SA 裁示 2026-08-24）：起始須 ≥ 當下——但**只對改動過的值**成立；
    // 迄止須晚於起始（後端亦強制，此處為即時回饋）。
    const timeErrors: Record<string, string> = {}
    if (startChanged && startAt && startAt.isBefore(startFloor)) {
      timeErrors.open_start_at = startedInPast
        ? "課程已開課，起始時間不可再往前調整"
        : "課程起始時間不可早於目前時間"
    }
    if (startAt && endAt && !endAt.isAfter(startAt)) {
      timeErrors.open_end_at = "課程訖止時間須晚於起始時間"
    }
    if (Object.keys(timeErrors).length > 0) {
      setErrors(timeErrors)
      return
    }
    setErrors({})
    saveMut.mutate()
  }

  /**
   * 新增章節（對齊 wireframe 之 modal）。
   *
   * `keepOpen` 對應 wireframe 的「儲存並繼續新增」——留在對話框並重設欄位，
   * 讓教師一次建完多個章節而不必反覆開關。
   */
  const submitChapter = async (keepOpen: boolean) => {
    const parsed = ChapterNameSchema.safeParse(chapterDraft)
    if (!parsed.success) {
      setChapterError(parsed.error.issues[0].message)
      return
    }
    setChapterError("")
    if (isNew) {
      setStagedChapters((prev) => [...prev, { id: nextStagedId.current--, name: parsed.data }])
      setChapterDraft("")
      if (!keepOpen) setChapterDialogOpen(false)
      return
    }
    try {
      await coursesApi.addChapter(courseId, parsed.data)
      invalidate()
      setChapterDraft("")
      if (!keepOpen) setChapterDialogOpen(false)
    } catch (err) {
      handleError(err)
    }
  }


  const handleDeleteChapter = (chapter: ChapterItem) => {
    if (isNew) {
      // 暫存章節尚未寫入 DB，也就沒有學員紀錄可連帶處理——直接移除，不必 confirm
      setStagedChapters((prev) => prev.filter((c) => c.id !== chapter.chapter_id))
      return
    }
    confirm({
      title: "刪除章節",
      content: "確定刪除此章節？學員於本章節之學習與成績將一併移除，且不再計入完課率。",
      okText: "刪除",
      onOk: async () => {
        try {
          await coursesApi.deleteChapter(chapter.chapter_id)
          invalidate()
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  // ── 章節項目（教材 / 測驗，#203）────────────────────────────────────────

  const openMaterialId = openItem?.item_type === "MATERIAL" ? openItem.material_id : null
  const openQuizId = openItem?.item_type === "QUIZ" ? openItem.quiz_id : null

  // 用 `isLoading`（首次載入）而非 `isFetching`——後者在存檔後的 refetch 也會是 true，
  // 視窗內容會被換成轉圈再換回來，看起來就是「儲存完視窗跳一下」。
  const { data: material, isLoading: materialLoading } = useQuery({
    queryKey: QUERY_KEYS.etCourses.material(openMaterialId ?? 0),
    queryFn: () => materialsApi.getDetail(openMaterialId as number),
    enabled: openMaterialId !== null,
  })

  const { data: quiz, isLoading: quizLoading } = useQuery({
    queryKey: QUERY_KEYS.etCourses.quiz(openQuizId ?? 0),
    queryFn: () => quizzesApi.getDetail(openQuizId as number),
    enabled: openQuizId !== null,
  })

  // DM 文件下拉只在教材視窗開著時才查——課程編輯頁本身不需要這份清單
  const { data: dmOptions = [] } = useQuery({
    queryKey: QUERY_KEYS.etCourses.dmDocuments(),
    queryFn: () => materialsApi.listDmDocuments(),
    enabled: openMaterialId !== null,
  })

  const invalidateMaterial = () => {
    if (openMaterialId !== null) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.material(openMaterialId) })
    }
  }
  const invalidateQuiz = () => {
    if (openQuizId !== null) {
      void qc.invalidateQueries({ queryKey: QUERY_KEYS.etCourses.quiz(openQuizId) })
    }
  }

  /**
   * 項目視窗內的操作統一經此執行。
   *
   * 錯誤呈現在**視窗內的 Alert** 而非 snackbar：使用者的注意力在視窗裡，
   * 而「教材須至少提供⋯」這類訊息需要指出是哪一個教材出問題，飄一則 toast 說不清楚。
   */
  const runItemAction = async (action: () => Promise<unknown>, after?: () => void) => {
    setItemError(null)
    try {
      await action()
      after?.()
    } catch (err) {
      const { errorCode, errorMessage } = toApiError(err)
      if (errorCode === LOCK_CONFLICT) {
        setConflictOpen(true)
        return
      }
      setItemError(errorMessage)
    }
  }

  const closeItemDialog = () => {
    setOpenItem(null)
    setItemError(null)
  }

  /** 關閉項目視窗；有未儲存的變更時先確認——沒改過就直接關，多問一次是干擾。 */
  const requestCloseItem = (dirty: boolean) => {
    if (!dirty) {
      closeItemDialog()
      return
    }
    confirm({
      title: "放棄變更",
      content: "尚未儲存的變更將不會保留，確定關閉？",
      okText: "關閉",
      onOk: closeItemDialog,
    })
  }

  const handleAddItem = async (chapter: ChapterItem, itemType: ItemType) => {
    const parsed = ItemTitleSchema.safeParse(itemType === "MATERIAL" ? "新教材" : "新測驗")
    if (!parsed.success) return
    try {
      const created = await itemsApi.add(chapter.chapter_id, itemType, parsed.data)
      invalidate()
      // 建完直接開視窗——空殼本身沒有內容，不開等於要使用者再點一次
      setOpenItem(created)
    } catch (err) {
      handleError(err)
    }
  }

  const handleDeleteItem = (item: ItemRow) => {
    confirm({
      title: `刪除${item.item_type === "MATERIAL" ? "教材" : "測驗"}`,
      content:
        "確定刪除此項目？其內容與學員於此項目之學習紀錄、成績將一併移除，且不再計入完課率。",
      okText: "刪除",
      onOk: async () => {
        try {
          await itemsApi.remove(item.item_id)
          invalidate()
          if (openItem?.item_id === item.item_id) closeItemDialog()
        } catch (err) {
          handleError(err)
        }
      },
    })
  }

  const handleUploadVideo = async (file: File) => {
    if (openMaterialId === null) return
    setUploading(true)
    await runItemAction(
      () => materialsApi.uploadVideo(openMaterialId, file),
      () => {
        invalidateMaterial()
        invalidate()
      },
    )
    setUploading(false)
  }

  const handleDeleteQuestion = (question: QuestionRow) => {
    confirm({
      title: "刪除題目",
      content: "確定刪除此題目？學員於此題之作答紀錄與得分將一併移除。",
      okText: "刪除",
      onOk: () => runItemAction(() => quizzesApi.removeQuestion(question.question_id), invalidateQuiz),
    })
  }

  const selectedTags = tagOptions.filter((t) => form.tag_ids.includes(t.tag_id))
  // 已發布課程僅可新增標籤、不可移除（FR-ET-US3-02）；停用標籤不可再新掛（FR-ET-US3-03）
  const tagsLocked = status !== "DRAFT"
  const selectableTags = tagOptions.filter((t) => t.is_active)

  // ⚠️ 查詢失敗時**必須早退**。原本忽略 error，403 之後 `course` 為 undefined，
  // 而 `readOnly` 是由 `course` 推導的（undefined → false），結果學員直接看到一個
  // 可編輯的課程編輯頁——雖然每個寫入都會被後端擋下，但畫面本身就不該出現。
  if (courseLoading) {
    // 載入中先顯示轉圈——否則會先閃出一張空表單，看起來像資料掉了
    return (
      <Stack alignItems="center" sx={{ py: 8 }}>
        <CircularProgress />
      </Stack>
    )
  }

  if (courseError) {
    const { status, errorMessage } = toApiError(courseError)
    const forbidden = status === 403
    return (
      <Box sx={{ p: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
          <IconButton size="small" aria-label="返回課程列表" onClick={() => navigate("/et/courses")}>
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h5">課程編輯</Typography>
        </Stack>
        <Alert severity={forbidden ? "warning" : "error"}>
          {forbidden ? "您沒有檢視此課程的權限。課程編輯僅開放教師與管理者。" : errorMessage}
        </Alert>
      </Box>
    )
  }

  return (
    <LocalizationProvider dateAdapter={AdapterDayjs}>
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <IconButton size="small" aria-label="返回課程列表" onClick={() => navigate("/et/courses")}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5">{courseId === undefined ? "新增課程" : "課程編輯"}</Typography>
        <Chip size="small" label={COURSE_STATUS_LABEL[status] ?? status} />
      </Stack>

      {readOnly && (
        <Alert severity="warning" icon={<VisibilityIcon />} sx={{ mb: 2 }}>
          <strong>檢視模式</strong> — 此課程由 <strong>{course?.owner_name ?? "他人"}</strong> 建立，您僅可閱覽，無法編輯。
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>
          基本資料
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "repeat(12, 1fr)" },
            gap: 2,
          }}
        >
          <Box sx={{ gridColumn: { md: "span 9" } }}>
            <TextField
              label="課程名稱"
              required
              size="small"
              fullWidth
              value={form.course_name}
              disabled={readOnly}
              error={Boolean(errors.course_name)}
              helperText={errors.course_name}
              onChange={(e) => setForm({ ...form, course_name: e.target.value })}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 3" } }}>
            <TextField
              label="狀態"
              size="small"
              fullWidth
              disabled
              value={COURSE_STATUS_LABEL[status] ?? status}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 12" } }}>
            <Autocomplete
              multiple
              size="small"
              disabled={readOnly}
              options={selectableTags}
              value={selectedTags}
              getOptionLabel={(o) => o.tag_name}
              isOptionEqualToValue={(a, b) => a.tag_id === b.tag_id}
              onChange={(_, next) => setForm({ ...form, tag_ids: next.map((t) => t.tag_id) })}
              renderValue={(value, getItemProps) =>
                value.map((option, index) => {
                  const { key, ...chipProps } = getItemProps({ index })
                  return (
                    <Chip
                      key={key}
                      {...chipProps}
                      size="small"
                      label={option.tag_name}
                      // 已發布不可移除既有標籤 → 不給 onDelete（後端另以 ET_COURSE_003 把關）
                      onDelete={tagsLocked || readOnly ? undefined : chipProps.onDelete}
                    />
                  )
                })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="受訓單位標籤"
                  helperText={
                    tagsLocked
                      ? "已發布課程可新增標籤、不可移除既有標籤"
                      : "多選；草稿可自由增刪，發布時至少 1 個（發布屬後續 issue）"
                  }
                />
              )}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            <DateTimePicker
              label="課程起始時間"
              value={startAt}
              disabled={readOnly}
              minDateTime={startFloor}
              onChange={(v) => setStartAt(v)}
              slotProps={{
                textField: { size: "small", fullWidth: true, error: Boolean(errors.open_start_at), helperText: errors.open_start_at },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            <DateTimePicker
              label="課程訖止時間"
              value={endAt}
              disabled={readOnly}
              minDateTime={startAt ?? undefined}
              onChange={(v) => setEndAt(v)}
              slotProps={{
                textField: { size: "small", fullWidth: true, error: Boolean(errors.open_end_at), helperText: errors.open_end_at },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
          </Box>
          <Box sx={{ gridColumn: { md: "span 4" } }}>
            <FormControlLabel
              control={
                <Switch
                  checked={form.require_approval}
                  disabled={readOnly}
                  onChange={(e) => setForm({ ...form, require_approval: e.target.checked })}
                />
              }
              label="本課程需線下核可"
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              開啟後學員線上完課仍須教師 / 管理者核可；不併入完課定義、不影響完課率。
            </Typography>
          </Box>
          <Box sx={{ gridColumn: { md: "span 12" } }}>
            <TextField
              label="課程描述"
              size="small"
              fullWidth
              multiline
              rows={2}
              value={form.description}
              disabled={readOnly}
              error={Boolean(errors.description)}
              helperText={errors.description ?? `${form.description.length} / ${DESCRIPTION_MAX_LEN}`}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Box>
        </Box>
      </Paper>

      <ChapterSection
        chapters={chapters}
        readOnly={readOnly}
        disabled={false}
        onAdd={() => {
          setChapterDraft("")
          setChapterError("")
          setChapterDialogOpen(true)
        }}
        onRename={(chapter, name) => {
          if (isNew) {
            setStagedChapters((prev) => prev.map((c) => (c.id === chapter.chapter_id ? { ...c, name } : c)))
            return
          }
          chapterMut.mutate(() => coursesApi.renameChapter(chapter.chapter_id, name, chapter.version))
        }}
        onDelete={handleDeleteChapter}
        onReorder={(ids) => {
          if (isNew) {
            setStagedChapters((prev) => ids.map((id) => prev.find((c) => c.id === id)).filter((c) => c !== undefined))
            return
          }
          // 樂觀更新：先把快取裡的章節順序換掉，拖放後立即定位。
          // 少了這步，畫面要等 API + refetch 才變，中間會閃回舊順序、看起來像「拖了沒動」。
          // 失敗時 onError 會 invalidate 還原（見 chapterMut）。
          qc.setQueryData(QUERY_KEYS.etCourses.detail(courseId), (old?: CourseDetail) =>
            old
              ? {
                  ...old,
                  chapters: ids
                    .map((id) => old.chapters.find((c) => c.chapter_id === id))
                    .filter((c) => c !== undefined),
                }
              : old,
          )
          chapterMut.mutate(() => coursesApi.reorderChapters(courseId, ids, course?.version ?? 0))
        }}
        itemsDisabled={isNew}
        onAddItem={handleAddItem}
        onOpenItem={(item) => {
          setItemError(null)
          setOpenItem(item)
        }}
        onDeleteItem={handleDeleteItem}
        onReorderItems={(chapter, ids) => {
          // 樂觀更新：同章節重排之理由——少了這步會閃回舊順序、看起來像「拖了沒動」
          qc.setQueryData(QUERY_KEYS.etCourses.detail(courseId as number), (old?: CourseDetail) =>
            old
              ? {
                  ...old,
                  chapters: old.chapters.map((c) =>
                    c.chapter_id === chapter.chapter_id
                      ? {
                          ...c,
                          items: ids.map((id) => c.items.find((i) => i.item_id === id)).filter((i) => i !== undefined),
                        }
                      : c,
                  ),
                }
              : old,
          )
          chapterMut.mutate(() => itemsApi.reorder(chapter.chapter_id, ids, chapter.version))
        }}
      />

      <MaterialDialog
        open={openMaterialId !== null}
        loading={materialLoading}
        readOnly={readOnly}
        material={material ?? null}
        dmOptions={dmOptions}
        error={itemError}
        uploading={uploading}
        onClose={requestCloseItem}
        onSave={(values: MaterialSavePayload) =>
          void runItemAction(
            () => materialsApi.update(openMaterialId as number, { ...values, version: material?.version ?? 0 }),
            () => {
              message.success("教材已儲存")
              invalidateMaterial()
              // 課程詳細也要刷——項目列顯示的名稱取自教材名稱
              invalidate()
              closeItemDialog()
            },
          )
        }
        onUploadVideo={(file) => void handleUploadVideo(file)}
      />

      <QuizDialog
        open={openQuizId !== null}
        loading={quizLoading}
        readOnly={readOnly}
        quiz={quiz ?? null}
        error={itemError}
        onClose={requestCloseItem}
        onSaveSettings={(values) =>
          void runItemAction(
            () => quizzesApi.update(openQuizId as number, { ...values, version: quiz?.version ?? 0 }),
            () => {
              message.success("測驗已儲存")
              invalidateQuiz()
              // 課程詳細也要刷——項目列顯示的名稱取自測驗名稱
              invalidate()
              closeItemDialog()
            },
          )
        }
        onSaveQuestion={(questionId: number | null, values: QuestionFormValues) =>
          void runItemAction(() => {
            if (questionId === null) return quizzesApi.addQuestion(openQuizId as number, values)
            const version = quiz?.questions.find((q) => q.question_id === questionId)?.version ?? 0
            return quizzesApi.updateQuestion(questionId, { ...values, version })
          }, invalidateQuiz)
        }
        onDeleteQuestion={handleDeleteQuestion}
      />

      {!readOnly && (
        <Paper
          variant="outlined"
          sx={{ position: "sticky", bottom: 0, mt: 2, p: 1.5, zIndex: 1 }}
        >
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="caption" color="text.secondary">
              儲存草稿可隨時繼續編輯。發布須先有教材與測驗，待 #203 / #204 完成後開放。
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={() => navigate("/et/courses")}>
                取消
              </Button>
              <Button size="small" variant="outlined" disabled={saveMut.isPending} onClick={handleSave}>
                儲存草稿
              </Button>
              {/*
                發布屬 #204。此處先放停用的按鈕呈現完整版面——#204 接上時補 handler 即可，
                按鈕本身不需重寫。

                **不可先讓它能按**：發布檢核五項中「至少 1 教材」與「各測驗配分 = 100」
                要到 #203 才驗得了。跳過那兩項會發布出一門沒有內容的課程，而發布會觸發
                標籤自動邀請＋寄信給所有符合標籤的學員（FR-ET-US3-12）——等於對全體學員
                寄信通知一門空課程。
              */}
              <Tooltip title="發布功能待教材 / 測驗完成後開放（ET Issue #203 / #204）">
                <span>
                  <Button size="small" variant="contained" disabled>
                    儲存並發布
                  </Button>
                </span>
              </Tooltip>
            </Stack>
          </Stack>
        </Paper>
      )}

      <Dialog open={chapterDialogOpen} onClose={() => setChapterDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>新增章節</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            size="small"
            fullWidth
            label="章節名稱"
            value={chapterDraft}
            error={Boolean(chapterError)}
            helperText={chapterError}
            onChange={(e) => setChapterDraft(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChapterDialogOpen(false)}>取消</Button>
          <Button onClick={() => void submitChapter(true)}>儲存並繼續新增</Button>
          <Button variant="contained" onClick={() => void submitChapter(false)}>
            儲存
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={conflictOpen} onClose={() => setConflictOpen(false)}>
        <DialogTitle>儲存失敗</DialogTitle>
        <DialogContent>
          <DialogContentText>內容已被其他裝置變更，請重新整理後再儲存。</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setConflictOpen(false)
              invalidate()
            }}
          >
            重新載入
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
    </LocalizationProvider>
  )
}
