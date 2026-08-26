import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined"
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
import { useEffect, useMemo, useRef, useState } from "react"
import { useBlocker, useNavigate, useParams } from "react-router-dom"

import { EMPTY_EDITOR_FORM, isPreviewableMime, makeEditorSchema, MANUAL_CATEGORY } from "./schemas"
import type { EditorForm, OptionItem } from "./schemas"
import { editorApi } from "./editorService"
import { useDocTags, useDraftMeta, useEditorOptions, useReviewers } from "./useEditor"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"
import { useDetail, useVersions } from "../detail/useDetail"

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
  // 續編模式 meta（草稿匣「繼續編輯」）：有本人草稿 → 續編（draftMeta + PUT 更新既有版本）；
  // 無（後端 404 → null）→ 從 DM02 詳細載已發布文件 meta、走「加新版」（addVersion）。
  const { data: draftMeta, isPending: draftMetaPending } = useDraftMeta(docId ?? "", !isNew)
  const isContinueDraft = !isNew && !!draftMeta
  const { data: detail, isPending: detailLoading } = useDetail(isNew ? "" : docId!)
  const { data: recentVersions } = useVersions(isNew ? "" : docId!, !isNew)
  const { data: docTags } = useDocTags(isNew ? "" : docId!, !isNew)

  const [form, setForm] = useState<EditorForm>(EMPTY_EDITOR_FORM)
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  // 已建立之草稿識別（送簽失敗重試時沿用，避免重複建立 / 單一草稿擋）
  const persisted = useRef<{ doc_id: string; version_id: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 我方主動導向（存草稿 / 送簽成功、取消確認後）→ 略過離開攔截，避免自家導向被再次攔問。
  const bypassGuard = useRef(false)
  // 編輯模式標籤只預帶一次，之後尊重使用者編輯（避免 refetch 覆蓋）。
  const tagsPrefilled = useRef(false)
  // 續編模式草稿內容（名稱 / 版號 / 摘要 / 審核者）只預帶一次。
  const metaPrefilled = useRef(false)

  const isManual = isNew && form.category_code === MANUAL_CATEGORY
  const fileNotPreviewable = file !== null && !isPreviewableMime(file.type)

  // 續編模式名稱可編（首版草稿 Q1=A）；其餘編輯情境名稱唯讀。
  const nameEditable = isContinueDraft && !!draftMeta?.name_editable
  // 編輯模式身份欄顯示值：續編取 draftMeta、加新版取 DM02 詳細。
  const editName = isContinueDraft ? (draftMeta?.doc_name ?? "") : (detail?.doc_name ?? "")
  const editCategoryName = isContinueDraft ? (draftMeta?.category_name ?? "") : (detail?.category_name ?? "")
  const editFuncCode = isContinueDraft ? draftMeta?.func_code : detail?.func_code
  const editFuncName = isContinueDraft ? draftMeta?.func_name : detail?.func_name

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

  /** 建立 / 沿用草稿（新增→createDocument；編輯→addVersion）。檔案可為 null（存草稿允許不附）。 */
  async function persistDraft(): Promise<{ doc_id: string; version_id: number }> {
    if (persisted.current) return persisted.current
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
    } else if (isContinueDraft) {
      // 續編：更新既有 DRAFT 版本（in-place，不另開版本 → 不撞單一草稿唯一索引）
      const r = await editorApi.updateDraftVersion(docId!, draftMeta!.draft_version_id, {
        doc_name: nameEditable ? form.doc_name.trim() : null, // 首版草稿可改名（Q1=A）；已發布文件唯讀 → null
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        audience_ids: form.audience_ids,
        retrieval_ids: form.retrieval_ids,
        file,
      })
      ids = { doc_id: docId!, version_id: r.version_id }
    } else {
      const r = await editorApi.addVersion(docId!, {
        version_no: form.version_no.trim(),
        change_summary: form.change_summary.trim(),
        audience_ids: form.audience_ids,
        retrieval_ids: form.retrieval_ids,
        file,
      })
      ids = { doc_id: docId!, version_id: r.version_id }
    }
    persisted.current = ids
    return ids
  }

  // 成功後導向：新增模式回文件庫（草稿 / 送審中不在詳細頁呈現，US4 對未發布一律 404）；
  // 編輯模式回原文件詳細頁（文件仍為已發布，可見送審中鎖定狀態）。
  const destAfter = () => (isNew ? "/dm/library" : `/dm/documents/${docId}`)

  // 我方主動導向：先舉旗略過離開攔截再 navigate。
  const go = (path: string) => {
    bypassGuard.current = true
    navigate(path)
  }

  function validate(forSubmit: boolean): boolean {
    const schema = makeEditorSchema({ isNew, isManual, forSubmit, requireName: nameEditable })
    const result = schema.safeParse(form)
    const fieldErrors = getFieldErrors(result.success ? null : result.error)
    // 檔案僅送簽時必填；存草稿可先不附檔（US5「存草稿不卡」）
    if (forSubmit && !file && !persisted.current) fieldErrors.file = "請選擇要上傳的檔案"
    setErrors(fieldErrors)
    return Object.keys(fieldErrors).length === 0
  }

  async function handleSaveDraft() {
    if (!validate(false)) return
    setBusy(true)
    try {
      await persistDraft()
      message.success("已儲存為草稿") // DM-MSG-DM03-007
      setDirty(false)
      go(destAfter())
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
      await editorApi.submit(ids.doc_id, { version_id: ids.version_id, assigned_reviewer: form.reviewer_id })
      message.success("已送交簽核，已通知指定審核者") // DM-MSG-DM03-006
      setDirty(false)
      go(destAfter())
    } catch (e) {
      applyApiError(e)
    } finally {
      setBusy(false)
    }
  }

  function handleCancel() {
    // 取消鈕：回來源頁（新增→文件庫、編輯→原詳細頁）。有未存變更先二次確認（DM-MSG-DM03-005），
    // 確認後以 go() 略過離開攔截，避免與 useBlocker 重複彈窗。
    const leave = () => go(isNew ? "/dm/library" : `/dm/documents/${docId}`)
    if (!dirty) {
      leave()
      return
    }
    confirm({
      title: "尚未儲存",
      content: "編輯項目將不會保留，確定要離開嗎？",
      okText: "離開不儲存",
      cancelText: "繼續編輯",
      onOk: leave,
    })
  }

  // 離開攔截（DM-MSG-DM03-005）：表單有未存變更且非我方主動導向（go）時，攔下其他 in-app 導向
  //（左側功能列切換、瀏覽器返回等），彈同款二次確認。取消鈕自帶確認、走 go() 不重複攔問。
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !bypassGuard.current && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    if (blocker.state !== "blocked") return
    confirm({
      title: "尚未儲存",
      content: "編輯項目將不會保留，確定要離開嗎？",
      okText: "離開不儲存",
      cancelText: "繼續編輯",
      onOk: () => blocker.proceed(),
      onCancel: () => blocker.reset(),
    })
  }, [blocker, confirm])

  // 編輯模式：載入文件現有標籤 → 一次性預帶進表單（不標記 dirty，尊重後續使用者編輯）。
  useEffect(() => {
    if (isNew || tagsPrefilled.current || !docTags) return
    tagsPrefilled.current = true
    setForm((prev) => ({ ...prev, audience_ids: docTags.audience_ids, retrieval_ids: docTags.retrieval_ids }))
  }, [isNew, docTags])

  // 續編模式：一次性預帶既有草稿內容（名稱 / 版號 / 摘要 / 前次審核者），解決續編須重填之痛點（#222）。
  useEffect(() => {
    if (isNew || metaPrefilled.current || !draftMeta) return
    metaPrefilled.current = true
    setForm((prev) => ({
      ...prev,
      doc_name: draftMeta.doc_name,
      version_no: draftMeta.version_no ?? "",
      change_summary: draftMeta.change_summary ?? "",
      reviewer_id: draftMeta.assigned_reviewer ?? "",
    }))
  }, [isNew, draftMeta])

  // 續編須等 draftMeta 解析（決定續編 / 加新版）；加新版情境再等 DM02 詳細載入。
  if (!isNew && (draftMetaPending || (!draftMeta && detailLoading))) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {isNew ? "新增文件" : `編輯文件 — ${editName}`}
      </Typography>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" }, gap: 2 }}>
        {/* 左：基本資料 + 版本 + 上傳 */}
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              基本資料
            </Typography>
            <Stack spacing={2}>
              {isNew ? (
                <>
                  {/* 新增模式：身份欄可編 */}
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
                </>
              ) : (
                <>
                  {/* 編輯模式：分類 / func 唯讀；文件名稱於續編首版草稿（未發布）時可改（Q1=A），其餘唯讀 */}
                  {nameEditable ? (
                    <TextField
                      label="文件名稱"
                      required
                      fullWidth
                      size="small"
                      value={form.doc_name}
                      onChange={(e) => setField("doc_name", e.target.value)}
                      error={!!errors.doc_name}
                      helperText={errors.doc_name || "此文件尚未發布，續編期間可修改名稱"}
                    />
                  ) : (
                    <TextField label="文件名稱" fullWidth size="small" value={editName} disabled />
                  )}
                  <TextField label="分類" fullWidth size="small" value={editCategoryName} disabled />
                  {editFuncCode && (
                    <TextField
                      label="關聯作業項目"
                      fullWidth
                      size="small"
                      value={`${editFuncCode} — ${editFuncName ?? ""}`}
                      disabled
                    />
                  )}
                </>
              )}
              {/* 可見對象 + 檢索標籤：新增與編輯模式皆可編（文件層屬性、即時生效） */}
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
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              版本資訊
            </Typography>
            {!isNew && detail?.current_version_no && (
              <TextField
                label="目前版本"
                fullWidth
                size="small"
                value={detail.current_version_no}
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
              文件內容（上傳檔案）
            </Typography>
            {isContinueDraft && draftMeta?.file_name && !file && (
              <Alert severity="info" sx={{ mb: 1 }}>
                目前檔案：{draftMeta.file_name}（未重新上傳則沿用既有檔案）
              </Alert>
            )}
            <Stack spacing={1}>
              <Box
                component="label"
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragOver(false)
                  onPickFile(e.dataTransfer.files?.[0] ?? null)
                }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 0.5,
                  py: 4,
                  px: 2,
                  border: "2px dashed",
                  borderColor: dragOver ? "primary.main" : errors.file ? "error.main" : "divider",
                  borderRadius: 1,
                  bgcolor: dragOver ? "action.selected" : "action.hover",
                  cursor: "pointer",
                  textAlign: "center",
                  transition: "border-color .15s, background-color .15s",
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  hidden
                  onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
                />
                <CloudUploadOutlinedIcon sx={{ fontSize: 44, color: "action.active", mb: 0.5 }} />
                {file ? (
                  <>
                    <Typography variant="body2" color="text.primary">
                      已選擇：{file.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      點擊或拖拉可重新選擇
                    </Typography>
                  </>
                ) : (
                  <>
                    <Typography variant="body2" color="text.secondary">
                      拖拉檔案至此或<Box component="span" sx={{ color: "primary.main" }}>點擊選擇</Box>
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      支援 PDF / Word / Excel / PPT / 圖片，單檔最大 50 MB
                    </Typography>
                  </>
                )}
              </Box>
              {errors.file && (
                <Typography variant="caption" color="error">
                  {errors.file}
                </Typography>
              )}
              {fileNotPreviewable && (
                <Alert severity="warning">此檔案格式（如 Word / Excel）無法線上預覽，閱覽者僅能下載。</Alert>
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

          {/* 最近版本（編輯模式）：呈現本文件近期版本 / 狀態 / 發布日期，供撰寫者對照定版號 */}
          {!isNew && (recentVersions?.length ?? 0) > 0 && (
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                最近版本
              </Typography>
              <Stack divider={<Divider flexItem />} spacing={1}>
                {(recentVersions ?? []).slice(0, 5).map((v) => (
                  <Box
                    key={v.version_id}
                    sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}
                  >
                    <Box>
                      <Typography variant="body2">{v.version_no}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {v.published_date?.slice(0, 10) ?? "—"}
                      </Typography>
                    </Box>
                    <Typography variant="caption" color={v.is_current ? "success.main" : "text.secondary"}>
                      {v.is_current ? "目前發布版" : "已被取代"}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Paper>
          )}
        </Stack>
      </Box>
    </Box>
  )
}