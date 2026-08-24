import AttachFileIcon from "@mui/icons-material/AttachFile"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { detailApi } from "./detailService"
import { ObsoleteRequestSchema } from "./obsoleteSchema"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"
import { useReviewers } from "../editor/useEditor"

interface Props {
  open: boolean
  docId: string
  docName: string
  onClose: () => void
  onSuccess: () => void
}

/** 後端 error_code → 對應欄位 / 訊息（DM02-012 需以廢止情境文案覆寫後端泛用送審訊息）。 */
const SERVER_FIELD: Record<string, "reason" | "reviewer_id" | "file"> = {
  DM_DOC_014: "reason",
  DM_DOC_015: "reviewer_id",
  DM_REVIEW_001: "reviewer_id",
  DM_FILE_001: "file",
  DM_FILE_002: "file",
}

/**
 * 廢止申請對話框（US8 / DM02）：必填廢止原因 + 選填單檔附件 + 選指定審核者（排除自己）。
 * 送出後文件轉「廢止待簽核」並通知審核者；核准 / 退回於簽核中心處理。
 */
export function DmObsoleteDialog({ open, docId, docName, onClose, onSuccess }: Props) {
  const { message } = useNotification()
  const { data: reviewers } = useReviewers()
  const [reason, setReason] = useState("")
  const [reviewerId, setReviewerId] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const reset = () => {
    setReason("")
    setReviewerId("")
    setFile(null)
    setErrors({})
    setSubmitError("")
  }

  const handleClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const handleSubmit = async () => {
    setSubmitError("")
    const result = ObsoleteRequestSchema.safeParse({ reason: reason.trim(), reviewer_id: reviewerId, file })
    const fieldErrors = getFieldErrors(result.success ? null : result.error)
    setErrors(fieldErrors)
    if (!result.success) return

    setSubmitting(true)
    try {
      await detailApi.initiateObsolete(docId, { reason: reason.trim(), reviewer_id: reviewerId, file })
      message.success("已送出廢止申請，已通知指定審核者") // DM-MSG-DM02-013
      reset()
      onSuccess()
      onClose()
    } catch (err) {
      const api = toApiError(err)
      // 併發新版本送審：以廢止情境文案呈現（DM-MSG-DM02-012），非後端泛用送審訊息
      const msg = api.errorCode === "DM_REVIEW_002" ? "此文件正進行新版本送審，無法同時發起廢止" : api.errorMessage
      const field = api.errorCode ? SERVER_FIELD[api.errorCode] : undefined
      if (field) setErrors((prev) => ({ ...prev, [field]: msg }))
      else setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>申請廢止文件</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          即將為「{docName}」送出廢止申請。送審期間文件仍持續對外提供，經指定審核者核准後才正式廢止下架。
        </Alert>
        {submitError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {submitError}
          </Alert>
        )}
        <Stack spacing={2}>
          <TextField
            label="廢止原因"
            required
            multiline
            minRows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            error={!!errors.reason}
            helperText={errors.reason}
            fullWidth
          />
          <Box sx={{ bgcolor: "action.hover", border: 1, borderColor: "divider", borderRadius: 1, p: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
              廢止附件 <Typography component="span" variant="caption" color="text.secondary">（選填單檔）</Typography>
            </Typography>
            <Button component="label" variant="outlined" size="small" startIcon={<AttachFileIcon />}>
              選擇檔案
              <input
                type="file"
                hidden
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.gif"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </Button>
            {file && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                {file.name}
              </Typography>
            )}
            {errors.file && (
              <Typography variant="caption" color="error" sx={{ display: "block", mt: 1 }}>
                {errors.file}
              </Typography>
            )}
          </Box>
          <TextField
            select
            label="指定審核者"
            required
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            error={!!errors.reviewer_id}
            helperText={errors.reviewer_id}
            fullWidth
          >
            {(reviewers ?? []).map((r) => (
              <MenuItem key={r.user_id} value={r.user_id}>
                {r.user_name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          取消
        </Button>
        <Button onClick={handleSubmit} color="error" variant="contained" disabled={submitting}>
          送出廢止申請
        </Button>
      </DialogActions>
    </Dialog>
  )
}
