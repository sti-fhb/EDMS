import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { toApiError } from "../../services/http"
import { invitationsApi } from "../courses/invitationsService"

/**
 * Email 邀請連結落點頁（US8 / #273）。
 *
 * ## 為何放在登入殼**之內**
 *
 * 加入課程要寫 `ET_ENROLLMENT.USER_ID`，沒有登入者就沒有人可以加。放在 `RootLayout`
 * 之內，未登入者會先看到登入 overlay、登入後本頁才繼續執行——token 一直留在網址上，
 * 不需要額外的 redirect 參數。
 *
 * 這與 `reset-password` / `verify-email` 那幾個**免登入**落點頁不同：那些的動作本身
 * 不需要身分（token 即身分），本頁的動作需要。
 *
 * ## 為何用 ref 擋重入
 *
 * 邀請 token 是**一次性**的：`accept` 成功後即消耗。React 18 的 StrictMode 會把 effect
 * 跑兩次，第二次會拿著已消耗的 token 再打一次——那一次會因為「呼叫者已在名單內」而回
 * `already_joined`（無害），但白打一支 API。用 ref 讓它只送一次。
 */
export function EtInviteLandingPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get("token")
  // 「網址上沒有 token」是從網址**直接推導**得出的，不需要跑一趟 effect 才知道
  // （在 effect 內同步 setState 會造成連鎖 render，`react-hooks/set-state-in-effect` 亦擋）。
  const hasToken = token !== null && token !== ""
  const [failure, setFailure] = useState<string | null>(null)
  const requested = useRef(false)

  useEffect(() => {
    if (!hasToken || requested.current) return
    requested.current = true

    const accept = async () => {
      try {
        const result = await invitationsApi.accept(token)
        // 已加入者同樣導向學習頁（AC 8）——「你已經加入過了」對學員不是有用的資訊。
        navigate(`/et/courses/${result.course_id}/learn`, { replace: true })
      } catch (err) {
        setFailure(toApiError(err).errorMessage)
      }
    }
    void accept()
  }, [hasToken, navigate, token])

  const error = hasToken ? failure : "邀請連結無效或已失效"

  return (
    <Box sx={{ p: 3, maxWidth: 640 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>
        加入課程
      </Typography>
      {error === null ? (
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <CircularProgress size={20} />
          <Typography variant="body2" color="text.secondary">
            正在確認邀請連結…
          </Typography>
        </Stack>
      ) : (
        <Stack spacing={2} alignItems="flex-start">
          <Alert severity="warning" sx={{ width: "100%" }}>
            {error}
          </Alert>
          <Typography variant="body2" color="text.secondary">
            邀請連結為一次性，若已被使用過會失效。請聯繫課程教師重新寄送。
          </Typography>
          <Button variant="contained" size="small" onClick={() => navigate("/et/my-courses")}>
            前往我的課程
          </Button>
        </Stack>
      )}
    </Box>
  )
}
