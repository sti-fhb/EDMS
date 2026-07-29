import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import ManageAccountsIcon from "@mui/icons-material/ManageAccounts"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { ChangePasswordDialog } from "./ChangePasswordDialog"
import { PROFILE_ME_QUERY_KEY, profileApi } from "./profileService"
import { EmailChangeSchema, NameSchema } from "./schemas/profileSchemas"
import { useNotification } from "../../contexts/NotificationContext"
import { formatCountdown, useCooldown } from "../../hooks/useCooldown"
import { toApiError } from "../../services/http"
import { getFieldErrors } from "../../utils/zodUtils"

/**
 * 個人資料維護頁（US8 / UCDP004，dp-profile）。所有登入者維護**自己的**姓名 / Email / 密碼。
 * 姓名直接生效；Email 採新信箱驗證後切換（延遲生效）；密碼變更於對話框。共用 DP_USER，ET / DM 同步。
 */
export function ProfilePage() {
  const { message } = useNotification()
  const qc = useQueryClient()
  const { data: me } = useQuery({ queryKey: PROFILE_ME_QUERY_KEY, queryFn: profileApi.getMe })

  // 姓名顯示值：使用者編輯過用草稿，否則帶伺服器現值（避免以 effect 同步 query→state）
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const name = nameDraft ?? me?.user_name ?? ""
  const [newEmail, setNewEmail] = useState("")
  const [nameError, setNameError] = useState<string | undefined>()
  const [emailError, setEmailError] = useState<string | undefined>()
  const [savingName, setSavingName] = useState(false)
  const [sendingEmail, setSendingEmail] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  // 寄驗證信冷卻（#74）：成功寄出 / 冷卻中（429）皆依 retry_after 起算，倒數期間 disable 按鈕
  const cooldown = useCooldown()

  const saveName = async () => {
    const parsed = NameSchema.safeParse({ user_name: name })
    setNameError(getFieldErrors(parsed.success ? null : parsed.error).user_name)
    if (!parsed.success) return
    setSavingName(true)
    try {
      await profileApi.updateName(parsed.data.user_name)
      await qc.invalidateQueries({ queryKey: PROFILE_ME_QUERY_KEY })
      message.success("姓名已更新")
    } catch (err) {
      message.error(toApiError(err).errorMessage)
    } finally {
      setSavingName(false)
    }
  }

  const sendEmailVerify = async () => {
    const parsed = EmailChangeSchema.safeParse({ new_email: newEmail })
    setEmailError(getFieldErrors(parsed.success ? null : parsed.error).new_email)
    if (!parsed.success) return
    setSendingEmail(true)
    try {
      const retryAfter = await profileApi.requestEmailChange(parsed.data.new_email)
      await qc.invalidateQueries({ queryKey: PROFILE_ME_QUERY_KEY })
      setNewEmail("")
      if (retryAfter) cooldown.start(retryAfter) // 成功寄出 → 起算冷卻倒數
      message.success("驗證信已寄至新 Email，請於效期內完成驗證；驗證前原 Email 仍可登入")
    } catch (err) {
      const apiErr = toApiError(err)
      // Email 已被使用（PROFILE-006）→ 清空欄位，提示使用者換一個（該值已知不可用）
      if (apiErr.errorCode === "DP_USER_007") setNewEmail("")
      // 冷卻中（429）→ 依 retry_after 起算倒數，disable 按鈕
      if (apiErr.retryAfter) cooldown.start(apiErr.retryAfter)
      message.error(apiErr.errorMessage)
    } finally {
      setSendingEmail(false)
    }
  }

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <ManageAccountsIcon color="primary" />
        <Typography variant="h5" component="h1">
          個人資料維護
        </Typography>
      </Stack>
      <Alert severity="info" sx={{ mb: 2 }}>
        姓名 / 帳號 / 密碼為共用資料，變更後於 ET / DM 兩端同步生效。
      </Alert>

      <Stack spacing={2}>
        {/* 姓名 */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              姓名
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems="flex-start">
              <TextField
                label="姓名"
                size="small"
                value={name}
                onChange={(e) => setNameDraft(e.target.value)}
                error={nameError !== undefined}
                helperText={nameError}
                fullWidth
              />
              <Button variant="contained" onClick={saveName} disabled={savingName} sx={{ flexShrink: 0 }}>
                儲存姓名
              </Button>
            </Stack>
          </CardContent>
        </Card>

        {/* 帳號（Email） */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              帳號（Email）
            </Typography>
            <Stack spacing={1.5}>
              <TextField label="目前帳號" size="small" value={me?.email ?? ""} disabled fullWidth />
              {me?.pending_email != null && (
                <Alert severity="warning">
                  變更審核中：{me.pending_email}（請至新信箱點驗證連結完成切換；驗證前原 Email 仍可登入）
                </Alert>
              )}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems="flex-start">
                <TextField
                  label="變更為新 Email"
                  size="small"
                  type="email"
                  placeholder="new@example.com"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  error={emailError !== undefined}
                  helperText={emailError ?? "寄驗證信至新 Email，點連結後才切換（延遲生效）；逾時未驗證則作廢"}
                  fullWidth
                />
                <Button
                  variant="outlined"
                  onClick={sendEmailVerify}
                  disabled={sendingEmail || cooldown.active}
                  sx={{ flexShrink: 0, whiteSpace: "nowrap" }}
                >
                  {cooldown.active ? `寄驗證信（${formatCountdown(cooldown.remaining)} 後）` : "寄驗證信"}
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        {/* 密碼 */}
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>
              密碼
            </Typography>
            <Button variant="outlined" onClick={() => setPwdOpen(true)}>
              變更密碼
            </Button>
          </CardContent>
        </Card>
      </Stack>

      <ChangePasswordDialog open={pwdOpen} onClose={() => setPwdOpen(false)} />
    </Box>
  )
}
