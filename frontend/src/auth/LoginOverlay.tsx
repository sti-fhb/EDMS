import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import Link from "@mui/material/Link"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import type { FormEvent } from "react"

import { AUTH_BG_GRADIENT, AUTH_SUBTITLE_COLOR } from "./authBackground"
import { ForgotPasswordForm } from "./ForgotPasswordForm"
import { RegisterForm } from "./RegisterForm"
import { authApi } from "./authService"
import { useAuth } from "./useAuth"
import { useCooldown, formatCountdown } from "../hooks/useCooldown"
import { toApiError } from "../services/http"

/**
 * 登入 overlay（全畫面遮罩）：登入 / 註冊分頁。
 * 登入：帳密 + 錯誤提示（後端 error_message）；`DP_AUTH_007` 同時給出三條出路——「前往註冊」與
 * 「重寄驗證信」兩個連結，加上「請至信箱點選驗證連結」一行小字（#484 起主訊息不再帶這些指引）。
 * 註冊（US2 #56）：RegisterForm，送出後於分頁內顯示「驗證信已寄」（不跳登入，需驗證後才能登入）。
 */
export function LoginOverlay() {
  const { login, sessionExpired } = useAuth()
  // 版號：公開端點（未登入可取），顯示於登入卡「忘記密碼」下方
  const { data: version } = useQuery({ queryKey: ["app", "version"], queryFn: authApi.version })
  const [tab, setTab] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [resendNote, setResendNote] = useState<string | null>(null)
  const [forgotMode, setForgotMode] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const resendCooldown = useCooldown()
  // 冷卻僅對「起算時的那個 Email」生效——換 Email 後不被前一個 Email 的冷卻誤擋
  const resendCoolingDown = resendCooldown.active && resendCooldown.key === email

  /**
   * 碼與訊息必須**同進退**。
   *
   * 下方 `DP_AUTH_007` 區塊的外層閘是 `errorMessage !== null`、內層條件是 `errorCode`，
   * 兩者分開清會讓不變量（區塊出現 ⟺ 碼是 007）破掉：日後若有人只設訊息而沒碰碼
   * （例如前端加一條「請輸入 Email」的驗證錯誤），三條出路就會掛在一個毫不相干的訊息底下。
   * 一律走這個函式，不要再分開呼叫兩個 setter。
   */
  const clearError = () => {
    setErrorCode(null)
    setErrorMessage(null)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    clearError()
    setResendNote(null)
    setSubmitting(true)
    try {
      await login(email, password)
    } catch (err) {
      const apiError = toApiError(err)
      setErrorCode(apiError.errorCode)
      setErrorMessage(apiError.errorMessage)
    } finally {
      setSubmitting(false)
    }
  }

  const handleResendVerification = async () => {
    if (resendCoolingDown) return
    setResendNote(null)
    try {
      const retryAfter = await authApi.resendVerification(email)
      setResendNote("若該 Email 有待驗證的註冊，已重新寄出驗證信，請至信箱查收")
      if (retryAfter) resendCooldown.start(retryAfter, email)
    } catch (err) {
      const apiError = toApiError(err)
      setResendNote(apiError.errorMessage)
      // 冷卻中（429）→ 依 retry_after 起算倒數（綁定此 Email），避免使用者繼續狂點
      if (apiError.retryAfter) resendCooldown.start(apiError.retryAfter, email)
    }
  }

  return (
    <Box
      sx={{
        position: "fixed",
        inset: 0,
        // 淡漸層底（對齊 TBMS 登入頁：淺綠 → 米白 → 淺粉）
        background: AUTH_BG_GRADIENT,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 2000,
        p: 2,
      }}
    >
      <Card sx={{ width: 400, maxWidth: "100%", p: 4, position: "relative" }}>
        {/*
          標題區對齊主專案 TBMS 之結構（#421）：主標為系統中文名（h5 / 600 / 主色）、
          副標為英文名（13px / 次要色）。**刻意不套用 TBMS 的品牌綠**——EDMS 有自己的
          `primary.main`，登入頁標題與頂列 AppBar 同色才是系統內一致；副標色兩邊本就相同。
        */}
        <Typography variant="h5" align="center" sx={{ fontWeight: 600, color: "primary.main" }}>
          教育訓練文件管理系統
        </Typography>
        <Typography align="center" sx={{ color: AUTH_SUBTITLE_COLOR, fontSize: 13, mb: 2 }}>
          Education &amp; Document Management System
        </Typography>
        {forgotMode ? (
          <ForgotPasswordForm onBack={() => setForgotMode(false)} />
        ) : (
          <>
            <Tabs
              value={tab}
              onChange={(_e, v) => {
                setTab(v as "login" | "register")
                clearError()
                setResendNote(null)
              }}
              variant="fullWidth"
              sx={{ mb: 2 }}
            >
              <Tab value="login" label="登入" />
              <Tab value="register" label="註冊" />
            </Tabs>

            {tab === "login" ? (
              <>
                {sessionExpired && errorMessage === null && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    閒置逾時已自動登出，請重新登入
                  </Alert>
                )}
                {resendNote !== null && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    {resendNote}
                  </Alert>
                )}
                {errorMessage !== null && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {errorMessage}
                    {/*
                      #208：後端已不再區分「查無帳號」與「尚未驗證」（否則匿名者密碼隨便填即可
                      列舉待驗證列，含「誰被邀請了」）。前端因此也**不能**靠 error code 以外的
                      條件決定顯示哪一條出路——只有使用者自己知道是哪一種，所以三條並列，由本人選。

                      ⚠️ 三條缺一即讓某一類使用者走進死路：
                        缺註冊     → 逾期者被指向靜默不寄的重寄
                        缺重寄     → 剛註冊未收到信者只能重註冊
                        缺下方小字 → 信已寄到但沒點的人不會想到去收信，只會一直按重寄而卡在冷卻

                      #484 把後端主訊息縮為「帳號或密碼錯誤」後，**三條出路全部由這個區塊承擔**
                      （後端 `_NO_ACCOUNT_MESSAGE` 的註解有對應說明）。小字必須與兩個連結同進退、
                      不可另加顯示條件——那會重新開啟 #208 要擋的列舉面。
                    */}
                    {errorCode === "DP_AUTH_007" && (
                      <Box sx={{ mt: 1 }}>
                        {/*
                          出路 3。⚠️ 字級與顏色不可再調淡：另外兩條有按鈕外觀撐著，這條**只有文字**，
                          視覺上失效時測試照樣全綠（它們只驗文字在 DOM 裡，驗不到看不看得見）。
                        */}
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                          尚未完成驗證？請至信箱點選驗證連結。
                        </Typography>
                        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                          <Link component="button" type="button" underline="hover" onClick={() => setTab("register")}>
                            前往註冊
                          </Link>
                          <Link
                            component="button"
                            type="button"
                            underline="hover"
                            disabled={resendCoolingDown}
                            sx={{
                              opacity: resendCoolingDown ? 0.5 : 1,
                              pointerEvents: resendCoolingDown ? "none" : "auto",
                            }}
                            onClick={handleResendVerification}
                          >
                            {resendCoolingDown
                              ? `重寄驗證信（${formatCountdown(resendCooldown.remaining)} 後）`
                              : "重寄驗證信"}
                          </Link>
                        </Box>
                      </Box>
                    )}
                  </Alert>
                )}
                <form onSubmit={handleSubmit}>
                  <Stack spacing={2}>
                    <TextField
                      label="帳號（Email）"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      fullWidth
                      autoComplete="username"
                    />
                    <TextField
                      label="密碼"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      fullWidth
                      autoComplete="current-password"
                    />
                    <Button type="submit" variant="contained" size="large" fullWidth disabled={submitting}>
                      登入
                    </Button>
                    <Link
                      component="button"
                      type="button"
                      underline="hover"
                      variant="body2"
                      onClick={() => {
                        setForgotMode(true)
                        clearError()
                        setResendNote(null)
                      }}
                    >
                      忘記密碼？
                    </Link>
                    {version !== undefined && (
                      <Typography variant="caption" align="center" color="text.secondary">
                        版本 {version}
                      </Typography>
                    )}
                  </Stack>
                </form>
              </>
            ) : (
              <RegisterForm />
            )}
          </>
        )}
      </Card>
    </Box>
  )
}
