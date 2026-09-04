import ContentCopyIcon from "@mui/icons-material/ContentCopy"
import EmailIcon from "@mui/icons-material/Email"
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined"
import PersonAddIcon from "@mui/icons-material/PersonAdd"
import SendIcon from "@mui/icons-material/Send"
import VpnKeyIcon from "@mui/icons-material/VpnKey"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { QRCodeSVG } from "qrcode.react"
import { useCallback, useState } from "react"

import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { InviteEmailsSchema, parseEmails } from "./invitationSchemas"
import type { InvitePreview } from "./invitationSchemas"
import { invitationsApi } from "./invitationsService"

interface InviteStudentsDialogProps {
  open: boolean
  courseId: number
  courseName: string
  /** 課程邀請碼（發布時產生）。無碼時「邀請碼」頁籤顯示提示而非空白。 */
  invitationCode: string | null
  onClose: () => void
}

/** 加入課程頁（ET04）之網址——邀請碼連結與 QR Code 皆導向此處的加入流程。 */
function joinUrlFor(code: string): string {
  return `${window.location.origin}/et/my-courses?code=${code}`
}

/**
 * ET02 邀請學員視窗（US8 / #273）。
 *
 * ## 這個視窗是「補件」用的
 *
 * 學員的主要來源是**發布課程時依受訓單位標籤自動帶入**（並自動寄出通知信）。本視窗
 * 供教師追加不在標籤內的人（Email 邀請），或把邀請碼交給學員自行加入。頂部的說明是
 * 刻意的——否則教師會以為必須逐一邀請每一位學員。
 *
 * ## 為何預覽是唯讀
 *
 * FR-ET-US8-07：信件主旨與內文由管理者於平台後台之「通知範本」統一維護，教師不可逐課
 * 編輯。預覽由**後端以同一支範本渲染**後回傳（非前端拼字串），故所見即所得。
 */
export function InviteStudentsDialog({
  open,
  courseId,
  courseName,
  invitationCode,
  onClose,
}: InviteStudentsDialogProps) {
  const { message } = useNotification()
  const [tab, setTab] = useState(0)
  const [emails, setEmails] = useState("")
  const [emailsError, setEmailsError] = useState<string | null>(null)
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [sending, setSending] = useState(false)
  const [partialFailures, setPartialFailures] = useState<string[]>([])

  const resetAll = useCallback(() => {
    setEmails("")
    setEmailsError(null)
    setPreview(null)
    setPartialFailures([])
  }, [])

  const handleClose = useCallback(() => {
    resetAll()
    onClose()
  }, [onClose, resetAll])

  const handleNext = useCallback(async () => {
    const parsed = InviteEmailsSchema.safeParse({ emails })
    if (!parsed.success) {
      setEmailsError(parsed.error.issues[0]?.message ?? "請確認 Email 清單")
      return
    }
    setEmailsError(null)
    setLoadingPreview(true)
    try {
      setPreview(await invitationsApi.preview(courseId, emails))
    } catch (err) {
      message.error(toApiError(err).errorMessage)
    } finally {
      setLoadingPreview(false)
    }
  }, [courseId, emails, message])

  const handleSend = useCallback(async () => {
    setSending(true)
    try {
      const result = await invitationsApi.send(courseId, emails)
      if (result.failed.length > 0) {
        // 部分失敗**不關閉視窗**：教師需要看到是哪幾筆才知道要不要重打一次。
        setPartialFailures(result.failed)
        return
      }
      message.success("邀請信已寄出")
      handleClose()
    } catch (err) {
      message.error(toApiError(err).errorMessage)
    } finally {
      setSending(false)
    }
  }, [courseId, emails, handleClose, message])

  const copy = useCallback(
    (text: string, label: string) => {
      void navigator.clipboard?.writeText(text)
      message.success(label)
    },
    [message],
  )

  const recipientCount = parseEmails(emails).length

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md">
      <DialogTitle>
        <Stack direction="row" alignItems="center" spacing={1}>
          <PersonAddIcon color="primary" />
          <span>邀請學員 —</span>
          <Typography component="span" color="primary" fontWeight={700}>
            {courseName}
          </Typography>
        </Stack>
      </DialogTitle>

      <DialogContent dividers>
        <Alert severity="info" sx={{ mb: 2 }}>
          發布時系統已依<strong>受訓單位標籤</strong>自動邀請對應人員加入課程，並各寄一封通知信。
          本功能供「補件」— 臨時追加不在標籤內的人（Email 邀請），或提供邀請碼。
        </Alert>

        <Tabs value={tab} onChange={(_e, v: number) => setTab(v)} sx={{ mb: 2 }}>
          <Tab icon={<EmailIcon />} iconPosition="start" label="Email 邀請（補件）" />
          <Tab icon={<VpnKeyIcon />} iconPosition="start" label="邀請碼" />
        </Tabs>

        <Box role="tabpanel" hidden={tab !== 0}>
          {tab === 0 && (
            <Stack spacing={2}>
              <TextField
                label="學員 Email"
                placeholder={"user1@military.gov.tw\nuser2@military.gov.tw"}
                helperText={emailsError ?? "每行一筆或以逗號分隔"}
                error={emailsError !== null}
                value={emails}
                onChange={(e) => {
                  setEmails(e.target.value)
                  setEmailsError(null)
                  // 清單改了，先前的預覽就不再對應——留著會讓教師以為寄的是他剛改完的版本。
                  setPreview(null)
                  setPartialFailures([])
                }}
                multiline
                minRows={3}
                fullWidth
                size="small"
                slotProps={{ input: { readOnly: sending } }}
              />

              {preview !== null && (
                <Stack spacing={1}>
                  <Alert severity="info" icon={<InfoOutlinedIcon />}>
                    信件內容由管理者統一維護，僅可預覽、不可編輯
                  </Alert>
                  <Typography variant="caption" color="text.secondary">
                    收件人：{preview.recipient_sample}（以第 1 筆收件人為預覽範例）
                  </Typography>
                  <TextField
                    label="主旨"
                    value={preview.subject}
                    size="small"
                    fullWidth
                    slotProps={{ input: { readOnly: true } }}
                  />
                  <TextField
                    label="內文"
                    value={preview.body}
                    multiline
                    rows={10}
                    fullWidth
                    size="small"
                    slotProps={{ input: { readOnly: true } }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    <InfoOutlinedIcon fontSize="inherit" sx={{ verticalAlign: "middle", mr: 0.5 }} />
                    實際寄出時，系統會為每位收件人產生獨立的一次性邀請連結；連結被使用後即失效，請勿轉寄。
                  </Typography>
                </Stack>
              )}

              {partialFailures.length > 0 && (
                <Alert severity="warning">
                  部分 Email 寄送失敗，已列入待加入清單可再寄送：{partialFailures.join("、")}
                </Alert>
              )}
            </Stack>
          )}
        </Box>

        <Box role="tabpanel" hidden={tab !== 1}>
          {tab === 1 &&
            (invitationCode === null ? (
              <Alert severity="info">課程發布後系統才會自動產生邀請碼。</Alert>
            ) : (
              <Stack direction={{ xs: "column", sm: "row" }} spacing={3} alignItems="center">
                <Stack spacing={1.5} flexGrow={1}>
                  <Typography variant="body2" fontWeight={700}>
                    本課程邀請碼
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      （8 碼數字；課程發布時系統自動產生）
                    </Typography>
                  </Typography>
                  <Typography variant="h5" fontFamily="monospace" fontWeight={700} letterSpacing={6}>
                    {invitationCode}
                  </Typography>
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => copy(joinUrlFor(invitationCode), "已複製邀請連結")}
                    >
                      複製邀請連結
                    </Button>
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => copy(invitationCode, "已複製邀請碼")}
                    >
                      複製邀請碼
                    </Button>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    學員可至「我的課程 → 加入新課程」輸入此邀請碼。邀請碼於課程<strong>關閉期間失效、再開課後恢復</strong>；
                    不可手動指定、不提供重新產生。
                  </Typography>
                </Stack>
                <QRCodeSVG value={joinUrlFor(invitationCode)} size={160} title="課程邀請 QR Code" marginSize={2} />
              </Stack>
            ))}
        </Box>
      </DialogContent>

      <DialogActions>
        {tab === 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ mr: "auto", ml: 1 }}>
            將寄出 {recipientCount} 封邀請信
          </Typography>
        )}
        <Button variant="outlined" size="small" onClick={handleClose}>
          關閉
        </Button>
        {tab === 0 &&
          (preview === null ? (
            <Button
              variant="contained"
              size="small"
              onClick={() => void handleNext()}
              disabled={loadingPreview}
              startIcon={loadingPreview ? <CircularProgress size={16} /> : undefined}
            >
              下一步
            </Button>
          ) : (
            <Button
              variant="contained"
              size="small"
              startIcon={<SendIcon />}
              onClick={() => void handleSend()}
              disabled={sending}
            >
              確認寄出
            </Button>
          ))}
      </DialogActions>
    </Dialog>
  )
}
