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
 * 故先向 `POST /videos/{id}/ticket` 取一張 5 分鐘、綁單一影片的票，放進 query string
 * ——形同 S3 presigned URL。
 *
 * ⚠️ **票不是「只用於發起連線」**（初版這樣假設，是錯的）。`<video>` 對同一個 URL 會
 * 反覆發出新請求：`preload="metadata"` 只預抓 metadata，內容要等按下播放才抓；久停後
 * 續播、拖到未緩衝區段亦然。它們都帶著同一張票，過期就會失敗。故除了拉長 TTL，
 * 另以 `onError` 自動重取票並復位進度（見 `handleVideoError`）。
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
  /** 票過期只重試一次——換了新票仍失敗表示不是過期問題，再重試會變無窮迴圈。 */
  const retriedRef = useRef(false)

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

  /**
   * 票過期後的自動復原。
   *
   * `<video>` 會對同一個 URL **反覆**發出請求（按下播放才抓內容、久停後續播、拖到
   * 未緩衝區段），而它們都帶著同一張票。只靠拉長 TTL 只是把撞到的機率降低，不是修好
   * ——學員把頁面開著吃完午餐回來按播放，一樣會失敗。
   *
   * 故播放失敗時重新取票並換上新 URL，**並復位播放進度**（換 `src` 會讓
   * `currentTime` 歸零，不復位就等於每次過期都被丟回片頭）。
   *
   * 只重試一次：若換了新票仍失敗，那不是過期問題（檔案不見、被移除權限），再重試
   * 只會變成無窮迴圈。
   */
  async function handleVideoError() {
    if (retriedRef.current) {
      setError("影片播放失敗，請重新整理頁面")
      return
    }
    retriedRef.current = true
    const resumeAt = videoRef.current?.currentTime ?? 0
    try {
      const ticket = await requestVideoTicket(video.video_id)
      setSrc(videoFileUrl(video.video_id, ticket))
      // `loadeddata` 之後才能設 currentTime——換 src 會重新載入
      const el = videoRef.current
      if (el) {
        const restore = () => {
          el.currentTime = resumeAt
          // **重取成功即解除「已重試」旗標**。不解除的話一個掛載週期只能救一次——
          // 學員在同一支長影片上第二次撞到過期就會看到錯誤訊息，而 300 秒 TTL 的
          // 正當性正是建立在「有自動重取兜底」之上。旗標的用途是擋住「換了新票仍
          // 立刻失敗」的無窮迴圈，而那種情況走不到這裡（`loadeddata` 不會觸發）。
          retriedRef.current = false
          el.removeEventListener("loadeddata", restore)
        }
        el.addEventListener("loadeddata", restore)
      }
    } catch {
      setError("影片播放失敗，請重新整理頁面")
    }
  }

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
          onError={() => void handleVideoError()}
          sx={{ width: "100%", maxHeight: 480, bgcolor: "common.black", borderRadius: 1 }}
        />
      )}

      {/*
        與影片下緣拉開距離——否則這排會和播放器自己的控制列（暫停 / 全螢幕）擠在一起，
        視覺上分不出哪些是播放器的、哪些是頁面的。

        ⚠️ **用 `pt` 不能用 `mt`**：父層 `<Stack spacing>` 以
        `& > :not(style) ~ :not(style) { margin-top }` 對子元素設定間距，其特異性
        （0,1,2）高過子元素自己 `sx` 產生的類別（0,1,0）——寫 `mt` 會被靜默蓋掉，
        畫面完全沒有變化。padding 不在它的覆寫範圍內。
      */}
      <Stack direction="row" spacing={2} alignItems="center" sx={{ pt: 1.5 }}>
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
