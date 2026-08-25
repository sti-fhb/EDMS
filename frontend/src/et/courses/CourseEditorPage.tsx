import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
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
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs"
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker"
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import dayjs from "dayjs"
import type { Dayjs } from "dayjs"
import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { ChapterSection } from "./ChapterSection"
import { coursesApi } from "./coursesService"
import {
  COURSE_STATUS_LABEL,
  ChapterNameSchema,
  CourseFormSchema,
  DESCRIPTION_MAX_LEN,
  type ChapterItem,
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
  const [stagedChapters, setStagedChapters] = useState<string[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [conflictOpen, setConflictOpen] = useState(false)
  const [chapterDialogOpen, setChapterDialogOpen] = useState(false)
  const [chapterDraft, setChapterDraft] = useState("")
  const [chapterError, setChapterError] = useState("")

  const { data: course } = useQuery({
    queryKey: QUERY_KEYS.etCourses.detail(courseId ?? 0),
    queryFn: () => coursesApi.getDetail(courseId as number),
    enabled: courseId !== undefined,
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
    ? stagedChapters.map((name, i) => ({
        chapter_id: -(i + 1),
        chapter_name: name,
        sort_order: i + 1,
        version: 0,
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

  /** 起始時間是否被使用者改動——決定要不要套「不得早於當下」的下限。 */
  const startChanged = (startAt?.toISOString() ?? null) !== originalStart

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
      if (isNew) return coursesApi.create({ ...toPayload(), chapters: stagedChapters })
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
    onError: handleError,
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
    if (startChanged && startAt && startAt.isBefore(dayjs())) {
      timeErrors.open_start_at = "課程起始時間不可早於目前時間"
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
      setStagedChapters((prev) => [...prev, parsed.data])
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

  const stagedIndexOf = (chapter: ChapterItem) => -chapter.chapter_id - 1

  const handleDeleteChapter = (chapter: ChapterItem) => {
    if (isNew) {
      // 暫存章節尚未寫入 DB，也就沒有學員紀錄可連帶處理——直接移除，不必 confirm
      setStagedChapters((prev) => prev.filter((_, i) => i !== stagedIndexOf(chapter)))
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

  const selectedTags = tagOptions.filter((t) => form.tag_ids.includes(t.tag_id))
  // 已發布課程僅可新增標籤、不可移除（FR-ET-US3-02）；停用標籤不可再新掛（FR-ET-US3-03）
  const tagsLocked = status !== "DRAFT"
  const selectableTags = tagOptions.filter((t) => t.is_active)

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
              // 只在使用者「改動」時要求不得早於當下——沿用原值不設下限，
              // 否則已開課課程（起始必然在過去）之後永遠存不了檔（AC 28 允許繼續編輯）。
              minDateTime={startChanged ? dayjs() : undefined}
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
            setStagedChapters((prev) => prev.map((n, i) => (i === stagedIndexOf(chapter) ? name : n)))
            return
          }
          chapterMut.mutate(() => coursesApi.renameChapter(chapter.chapter_id, name, chapter.version))
        }}
        onDelete={handleDeleteChapter}
        onReorder={(ids) => {
          if (isNew) {
            setStagedChapters((prev) => ids.map((id) => prev[-id - 1]))
            return
          }
          chapterMut.mutate(() => coursesApi.reorderChapters(courseId, ids, course?.version ?? 0))
        }}
      />

      {!readOnly && (
        <Paper
          variant="outlined"
          sx={{ position: "sticky", bottom: 0, mt: 2, p: 1.5, zIndex: 1 }}
        >
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="caption" color="text.secondary">
              儲存草稿可隨時繼續編輯；教材 / 測驗與發布於後續 issue 提供。
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={() => navigate("/et/courses")}>
                取消
              </Button>
              <Button size="small" variant="contained" disabled={saveMut.isPending} onClick={handleSave}>
                儲存草稿
              </Button>
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
