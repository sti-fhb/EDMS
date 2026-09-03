import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useEffect, useRef, useState } from "react"

import type { MaterialVideoRow } from "./learnSchemas"
import { requestVideoTicket, videoFileUrl } from "./learnService"

interface Props {
  video: MaterialVideoRow
  /** 已由後端依 `ET_VIDEO_PLAYBACK_MAX_RATE` 往下限縮之可選倍速。 */
  playbackRates: number[]
}

/**
 * HTML5 影片播放器（AC 3 / AC 4）。
 *
 * ## 為何要先取票再播
 *
 * JWT 是 memory-only，`<video src>` **送不出 Authorization header**。而影片單檔上限
 * 500MB，不能像 DM 文件那樣用 blob（整支下載完才能播、失去 Range、記憶體吃滿）。
 * 故先向 `POST /videos/{id}/ticket` 取一張 60 秒、綁單一影片的票，放進 query string
 * ——形同 S3 presigned URL。
 *
 * 票只用於**發起**連線；之後拖動進度條產生的 Range 請求沿用同一個 URL，串流不會因
 * 票過期而中斷（連線已建立）。
 *
 * ## 倍速選項由後端給
 *
 * **不要在前端寫死五段**——上限取自 `DP_PARAM.ET_VIDEO_PLAYBACK_MAX_RATE`，且該參數
 * **只能往下限縮**（FR-ET-US5-03）。後端已算好可選清單，前端照列即可；自行產生會讓
 * 參數調高時冒出播放器不該有的倍速。
 *
 * ⚠️ **本 issue 不上報觀看區段**——`ET_PROGRESS_INTERVAL` 的寫入、覆蓋率、解鎖判定
 * 全屬 `ET-5b`。此處刻意不掛 `onPause` / `onSeeked` 等事件監聽：先鋪一半的上報會讓
 * `ET-5b` 得先拆掉它。
 */
export function VideoPlayer({ video, playbackRates }: Props) {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rate, setRate] = useState(1)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    // **不在 effect 內同步 setState**（串聯 render，且 ESLint 擋）。切換教材時
    // `ContentPane` 以 `key={video.video_id}` 重新掛載本元件，狀態自然歸零。
    let cancelled = false
    requestVideoTicket(video.video_id)
      .then((ticket) => {
        if (!cancelled) setSrc(videoFileUrl(video.video_id, ticket))
      })
      .catch(() => {
        if (!cancelled) setError("影片載入失敗，請重新整理頁面")
      })
    return () => {
      cancelled = true
    }
  }, [video.video_id])

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate
  }, [rate, src])

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2">{video.file_name}</Typography>

      {error && <Alert severity="error">{error}</Alert>}

      {src && (
        <Box
          component="video"
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          sx={{ width: "100%", maxHeight: 480, bgcolor: "common.black", borderRadius: 1 }}
        />
      )}

      <Stack direction="row" spacing={2} alignItems="center">
        <TextField
          select
          size="small"
          label="播放速度"
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
          sx={{ width: 140 }}
        >
          {playbackRates.map((r) => (
            <MenuItem key={r} value={r}>
              {r}x
            </MenuItem>
          ))}
        </TextField>
        <Typography variant="caption" color="text.secondary">
          長度 {formatDuration(video.duration_sec)}
        </Typography>
      </Stack>
    </Stack>
  )
}

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, "0")}`
}
