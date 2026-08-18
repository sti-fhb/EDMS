import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useMemo, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { EMPTY_EDITOR_FORM, isPreviewableMime, makeEditorSchema, MANUAL_CATEGORY } from "./schemas"
import type { EditorForm, OptionItem } from "./schemas"
import { editorApi } from "./editorService"
import { useEditorOptions, useReviewers } from "./useEditor"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"
import { useDetail } from "../detail/useDetail"

const TAG_GROUP_LABELS: Record<string, string> = { MODULE: "適用模組", NATURE: "文件性質", LEGAL: "法規關聯" }

/** 後端 error_code → 對應表單欄位（用於 inline 標紅）；未列者以 Snackbar 呈現。 */
const ERROR_FIELD: Record<string, keyof EditorForm> = {
  DM_DOC_005: "audience_ids", // 無可見對象（DM-MSG-DM03-008）
  DM_DOC_006: "version_no", // 版號空 / 重複（DM-MSG-DM03-009）
  DM_DOC_007: "func_code", // 手冊 func 重複（DM-MSG-DM03-003）
  DM_REVIEW_001: "reviewer_id", // 審核者為撰寫者本人
}

/**
 * 文件新增與編輯（US5 / DM03）雙模式表單。
 *
 * - **新增模式**（`/dm/documents/new`）：填 名稱 / 分類 /（MANUAL）func / 可見對象 / 檢索標籤 /
 *   首版版號 / 摘要 + 上傳單檔 → 存草稿 或 送簽（指定審核者）。
 * - **編輯模式**（`/dm/documents/:docId/edit`）：名稱 / 分類 / func 唯讀；改版號 / 摘要 / 檔案 →
 *   存草稿 或 送簽。標籤 / 可見性沿用文件既有、不於此變更（見後端 service 說明）。
 *
 * 送簽 = 先建草稿（新增 POST /documents 或加版 POST /versions）再 POST /submit；建草稿結果快取於
 * `persisted`，送簽失敗（如 func 重複）可原地重試而不重複建立、亦不觸發單一草稿擋（DM_DOC_009）。
 */
export function DmEditorPage() {
  const { docId } = useParams<{ docId?: string }>()
  const isNew = !docId
  const navigate = useNavigate()
  const { message, confirm } = useNotification()

  const { data: options } = useEditorOptions()
  const { data: reviewers } = useReviewers()
  const { data: detail, isPending: detailLoading } = useDetail(isNew ? "" : docId!)

  const [form, setForm] = useState<EditorForm>(EMPTY_EDITOR_FORM)
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  // 已建立之草稿識別（送簽失敗重試時沿用，避免重複建立 / 單一草稿擋）
  const persisted = useRef<{ doc_id: string; version_id: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isManual = isNew && form.category_code === MANUAL_CATEGORY
  const fileNotPreviewable = file !== null && !isPreviewableMime(file.type)

  const audienceOptions = options?.audiences ?? []
  const retrievalOptions = options?.retrieval_tags ?? []
  const selectedAudiences = useMemo(
    () => (options?.audiences ?? []).filter((o) => form.audience_ids.includes(o.code)),
    [options?.audiences, form.audience_ids],
  )
  const selectedRetrieval = useMemo(
    () => (options?.retrieval_tags ?? []).filter((o) => form.retrieval_ids.includes(o.code)),
    [options?.retrieval_tags, form.retrieval_ids],
  )

  // 草稿內容欄位（會寫入 DM_DOCUMENT / DM_DOC_VERSION / DM_DOC_TAG）：變更後清草稿快取，
  // 使下次送簽重新建立、避免沿用已過時之草稿。
  const setField = <K extends keyof EditorForm>(key: K, value: EditorForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setDirty(true)
    persisted.current = null
    setErrors((prev) => ({ ...prev, [key as string]: "" }))
  }

  // 審核者僅為 submit 參數、不屬草稿內容：變更**不可**清草稿快取，否則送簽失敗後改審核者重試
  // 會重複建立文件（新增模式）或誤觸單一草稿擋（編輯模式）。
  const setReviewer = (value: string) => {
    setForm((prev) => ({ ...prev, reviewer_id: value }))
    setDirty(true)
    setErrors((prev) => ({ ...prev, reviewer_id: "" }))
  }

  const onCategoryChange = (value: string) => {
    setForm((prev) => ({ ...prev, category_code: value, func_code: value === MANUAL_CATEGORY ? prev.func_code : "" }))
    setDirty(true)
    persisted.current = null
  }

  const onPickFile = (f: File | null) => {
    setFile(f)
    setDirty(true)
    persisted.current = null
    setErrors((prev) => ({ ...prev, file: "" }))
    if (f && !isPreviewableMime(f.type)) {
      // Office 等非可預覽格式：警示 + 二次確認（DM-MSG-DM03-002）
      confirm({
        title: "此檔案無法線上預覽",
        content: "所選檔案（如 Word / Excel）閱覽者將只能下載、無法線上預覽。是否仍使用此檔案？",
        okText: "仍使用此檔案",
        cancelText: "改傳其他檔案",
        onOk: () => {},
        onCancel: () => {
          setFile(null)
          if (fileInputRef.current) fileInputRef.current.value = ""
        },
      })
    }
  }

  function applyApiError(e: unknown) {
    const { errorCode, errorMessage } = toApiError(e)
    const field = ERROR_FIELD[errorCode]
    if (field) {
      setErrors((prev) => ({ ...prev, [field]: errorMessage }))
    } else {
      message.error(errorMessage) // DM_DOC_004 / 008 / 009 / REVIEW_002 等
    }
  }

  /** 建立 / 沿用草稿（新增→createDocument；編輯→addVersion）。回識別或 null（檔案缺）。 */
  async function persistDraft(): Promise<{ doc_id: string; version_id: number } | null> {
    if (persisted.current) return persisted.current
    if (!file) {
      setErrors((prev) => ({ ...prev, file: "請選擇要上傳的檔案" }))
      return null
    }
    let ids: { doc_id: string; version_id: number }
    if (isNew) {
      const r = await editorApi.createDocument({
        doc_name: form.doc_name.trim(),
        category_code: form.category_code,
        func_code: isManual ? form.func_code : "",
        audience_ids: form.audience_ids,
        retrieval_ids: form.retrieval_ids,
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        file,
      })
      ids = { doc_id: r.doc_id, version_id: r.version_id }
    } else {
      const r = await editorApi.addVersion(docId!, {
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        file,
      })
      ids = { doc_id: docId!, version_id: r.version_id }
    }
    persisted.current = ids
    return ids
  }

  const destAfter = (id: string) => (isNew ? `/dm/documents/${id}` : `/dm/documents/${docId}`)

  function validate(forSubmit: boolean): boolean {
    const schema = makeEditorSchema({ isNew, isManual, forSubmit })
    const result = schema.safeParse(form)
    const fieldErrors = getFieldErrors(result.success ? null : result.error)
    if (!file && !persisted.current) fieldErrors.file = "請選擇要上傳的檔案"
    setErrors(fieldErrors)
    return Object.keys(fieldErrors).length === 0
  }

  async function handleSaveDraft() {
    if (!validate(false)) return
    setBusy(true)
    try {
      const ids = await persistDraft()
      if (!ids) return
      message.success("已儲存為草稿") // DM-MSG-DM03-007
      setDirty(false)
      navigate(destAfter(ids.doc_id))
    } catch (e) {
      applyApiError(e)
    } finally {
      setBusy(false)
    }
  }

  async function handleSubmit() {
    if (!validate(true)) return
    setBusy(true)
    try {
      const ids = await persistDraft()
      if (!ids) return
      await editorApi.submit(ids.doc_id, { version_id: ids.version_id, assigned_reviewer: form.reviewer_id })
      message.success("已送交簽核，已通知指定審核者") // DM-MSG-DM03-006
      setDirty(false)
      navigate(destAfter(ids.doc_id))
    } catch (e) {
      applyApiError(e)
    } finally {
      setBusy(false)
    }
  }

  function handleCancel() {
    const leave = () => navigate(isNew ? "/dm/library" : `/dm/documents/${docId}`)
    if (!dirty) {
      leave()
      return
    }
    // 有未存變更 → 二次確認（DM-MSG-DM03-005）
    confirm({
      title: "放棄未儲存的變更？",
      content: "此表單有尚未儲存的變更，離開將不會保留。確定要離開嗎？",
      okText: "離開不儲存",
      cancelText: "繼續編輯",
      onOk: leave,
    })
  }

  if (!isNew && detailLoading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3, maxWidth: 1100, mx: "auto" }}>
      <Typography variant="h5" gutterBottom>
        {isNew ? "新增文件" : `編輯文件 — ${detail?.doc_name ?? ""}`}
      </Typography>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" }, gap: 2 }}>
        {/* 左：基本資料 + 版本 + 上傳 */}
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              基本資料
            </Typography>
            {isNew ? (
              <Stack spacing={2}>
                <TextField
                  label="文件名稱"
                  required
                  fullWidth
                  size="small"
                  value={form.doc_name}
                  onChange={(e) => setField("doc_name", e.target.value)}
                  error={!!errors.doc_name}
                  helperText={errors.doc_name}
                />
                <TextField
                  select
                  label="分類"
                  required
                  fullWidth
                  size="small"
                  value={form.category_code}
                  onChange={(e) => onCategoryChange(e.target.value)}
                  error={!!errors.category_code}
                  helperText={errors.category_code}
                >
                  {(options?.categories ?? []).map((c) => (
                    <MenuItem key={c.code} value={c.code}>
                      {c.name}
                    </MenuItem>
                  ))}
                </TextField>
                {isManual && (
                  <TextField
                    select
                    label="關聯作業項目"
                    required
                    fullWidth
                    size="small"
                    value={form.func_code}
                    onChange={(e) => setField("func_code", e.target.value)}
                    error={!!errors.func_code}
                    helperText={errors.func_code}
                  >
                    {(options?.funcs ?? []).map((f) => (
                      <MenuItem key={f.code} value={f.code}>
                        {f.code} — {f.name}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
                <Autocomplete
                  multiple
                  size="small"
                  options={audienceOptions}
                  value={selectedAudiences}
                  onChange={(_, v: OptionItem[]) => setField("audience_ids", v.map((o) => o.code))}
                  getOptionLabel={(o) => o.name}
                  isOptionEqualToValue={(a, b) => a.code === b.code}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="可見對象"
                      required
                      error={!!errors.audience_ids}
                      helperText={errors.audience_ids || "至少指定 1 個；「全體」表示所有閱覽者可見"}
                    />
                  )}
                />
                <Autocomplete
                  multiple
                  size="small"
                  options={retrievalOptions}
                  value={selectedRetrieval}
                  onChange={(_, v: OptionItem[]) => setField("retrieval_ids", v.map((o) => o.code))}
                  getOptionLabel={(o) => o.name}
                  isOptionEqualToValue={(a, b) => a.code === b.code}
                  groupBy={(o) => TAG_GROUP_LABELS[o.group_code ?? ""] ?? "標籤"}
                  renderInput={(params) => <TextField {...params} label="檢索標籤（選填）" />}
                />
              </Stack>
            ) : (
              <Stack spacing={1.5}>
                {/* 編輯模式：身份欄唯讀 */}
                <TextField label="文件名稱" fullWidth size="small" value={detail?.doc_name ?? ""} disabled />
                <TextField label="分類" fullWidth size="small" value={detail?.category_name ?? ""} disabled />
                {detail?.func_code && (
                  <TextField
                    label="關聯作業項目"
                    fullWidth
                    size="small"
                    value={`${detail.func_code} — ${detail.func_name ?? ""}`}
                    disabled
                  />
                )}
                <Alert severity="info">
                  可見對象與檢索標籤沿用文件既有設定，於此不變更。
                </Alert>
              </Stack>
            )}
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              版本資訊
            </Typography>
            {!isNew && (
              <TextField
                label="目前版本"
                fullWidth
                size="small"
                value={detail?.current_version_no ?? "—"}
                disabled
                sx={{ mb: 2 }}
              />
            )}
            <Stack spacing={2}>
              <TextField
                label={isNew ? "首版版本號" : "新版本號"}
                required
                fullWidth
                size="small"
                value={form.version_no}
                onChange={(e) => setField("version_no", e.target.value)}
                error={!!errors.version_no}
                helperText={errors.version_no || "由撰寫者自行輸入（系統不建議版號）"}
              />
              <TextField
                label={isNew ? "首版摘要" : "變更摘要"}
                required
                fullWidth
                multiline
                minRows={2}
                size="small"
                value={form.change_summary}
                onChange={(e) => setField("change_summary", e.target.value)}
                error={!!errors.change_summary}
                helperText={errors.change_summary}
              />
            </Stack>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              文件檔案
            </Typography>
            <Stack spacing={1}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
                <Button variant="outlined" component="label" size="small">
                  選擇檔案
                  <input
                    ref={fileInputRef}
                    type="file"
                    hidden
                    onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
                  />
                </Button>
                <Typography variant="body2" color={file ? "text.primary" : "text.secondary"}>
                  {file ? file.name : "尚未選擇檔案（單檔）"}
                </Typography>
              </Box>
              {errors.file && <Typography variant="caption" color="error">{errors.file}</Typography>}
              {fileNotPreviewable && (
                <Alert severity="warning">
                  此檔案格式（如 Word / Excel）無法線上預覽，閱覽者僅能下載。
                </Alert>
              )}
            </Stack>
          </Paper>
        </Stack>

        {/* 右：指定審核者 + 動作 */}
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              送交簽核
            </Typography>
            <TextField
              select
              label="指定審核者"
              fullWidth
              size="small"
              value={form.reviewer_id}
              onChange={(e) => setReviewer(e.target.value)}
              error={!!errors.reviewer_id}
              helperText={errors.reviewer_id || "送簽時必填；不含您本人"}
            >
              {(reviewers ?? []).map((r) => (
                <MenuItem key={r.user_id} value={r.user_id}>
                  {r.user_name}
                </MenuItem>
              ))}
            </TextField>
            <Divider sx={{ my: 2 }} />
            <Stack spacing={1}>
              <Button variant="contained" onClick={handleSubmit} disabled={busy}>
                送交簽核
              </Button>
              <Button variant="outlined" onClick={handleSaveDraft} disabled={busy}>
                儲存為草稿
              </Button>
              <Button color="inherit" onClick={handleCancel} disabled={busy}>
                取消
              </Button>
            </Stack>
          </Paper>
        </Stack>
      </Box>
    </Box>
  )
}