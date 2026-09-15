import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material"
import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"

import { toBlobApiError } from "../../services/http"
import { downloadWeeklyCsv } from "./reportsService"

/**
 * 週報明細下載之中繼頁（T164 / US14 / #325）。
 *
 * ## 為何需要一個頁面
 *
 * 週報信中的連結是瀏覽器導覽，**帶不了 `Authorization` header**——直接指向後端端點
 * 只會拿到 401。本頁掛在 `/et` 之下，未登入時由既有的 `RequireModule` 與登入 overlay
 * 接手、登入後回到本路由（FR-ET-US14-11 之「未登入 MUST 導向登入頁」），登入後才由
 * 前端帶 token 取回 CSV。
 *
 * ## 不進側欄
 *
 * 唯一入口是信件連結。它沒有獨立的業務意義（內容等同信中摘要的明細版），放進導覽只會
 * 多一個使用者不知道要點來做什麼的項目。
 */
export function EtWeeklyReportDownloadPage() {
  const [params] = useSearchParams()
  const raw = params.get("courseId")
  // 以字面樣式判定而非 `Number.isInteger`：`Number("")` → 0、`Number("-5")` → -5、
  // `Number("0x10")` → 16、`Number("1e3")` → 1000 全都是整數，於是 `?courseId=` 這種
  // 壞連結會被送到後端吃 422，而不是在這裡顯示「連結無效」——那正是這段驗證的用意
  const invalidCourseId = raw !== null && !/^[1-9]\d*$/.test(raw)
  const courseId = raw === null || invalidCourseId ? undefined : Number(raw)

  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle")
  const [message, setMessage] = useState("")
  // 自動下載只跑一次：StrictMode 於開發期會重跑 effect，不擋會連下兩次檔案
  const started = useRef(false)

  const run = useCallback(async () => {
    setState("loading")
    try {
      await downloadWeeklyCsv(courseId)
      setState("done")
    } catch (err) {
      setState("error")
      // ⚠️ 必須用 `toBlobApiError`：`responseType: "blob"` 的請求失敗時 `response.data`
      // 是 Blob，一般的錯誤解析取不到 `error_message`，畫面只會顯示 axios 的
      // 「Request failed with status code 403」——把後端「僅課程擁有者可下載」這種
      // 說得清楚的訊息整個蓋掉，而點到轉寄連結的人正是最需要看到那句話的人
      const apiErr = await toBlobApiError(err)
      setMessage(apiErr.errorMessage || "下載失敗，請稍後再試")
    }
  }, [courseId])

  useEffect(() => {
    if (invalidCourseId || started.current) return
    started.current = true
    void run()
  }, [invalidCourseId, run])

  if (invalidCourseId) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">連結中的課程代碼無效。</Alert>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        週報學員明細下載
      </Typography>
      <Stack spacing={2} alignItems="flex-start">
        {state === "loading" && <CircularProgress size={24} aria-label="下載中" />}
        {state === "done" && (
          <Alert severity="success">
            明細已開始下載。內容於點擊當下即時產生，數字可能與週報信中的摘要略有時間差。
          </Alert>
        )}
        {state === "error" && <Alert severity="error">{message}</Alert>}
        {state !== "loading" && (
          <Button variant="outlined" onClick={() => void run()}>
            重新下載
          </Button>
        )}
      </Stack>
    </Box>
  )
}
