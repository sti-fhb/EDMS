import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Chip from "@mui/material/Chip"
import LinearProgress from "@mui/material/LinearProgress"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useCallback, useEffect, useRef, useState } from "react"

import type { MaterialVideoRow } from "./learnSchemas"
import { requestVideoTicket, videoFileUrl } from "./learnService"
import type { Segment, TrackerState } from "./playbackTracker"
import { IDLE_TRACKER, beginSegment, endSegment, observeTime, seekTo } from "./playbackTracker"
import { progressApi } from "./progressService"

/** 覆蓋率達此值即解鎖下一項（FR-ET-US5-05，與後端 `COVERAGE_THRESHOLD_PCT` 一致）。 */
const COVERAGE_THRESHOLD_PCT = 80

/**
 * `seeked` 的緩衝時間（毫秒）。
 *
 * 拖動進度條時 `seeked` 會連續觸發數十次；逐次送出等於一次拖動打數十個請求。緩衝後
 * 一次送一批（後端單次上限 200 段，遠高於任何正常操作）。
 *
 * **只有 `seeked` 需要緩衝**——`pause` / `ended` 是刻意且低頻的動作，延後兩秒送只是
 * 讓覆蓋率慢兩秒才更新，沒有換到任何東西。
 *
 * ⚠️ 這是**節流，不是可靠性機制**——離開頁面時一律強制 flush（見 `flushNow`）。
 */
const SEEK_FLUSH_DELAY_MS = 2000

interface Props {
  video: MaterialVideoRow
  /** 已由後端依 `ET_VIDEO_PLAYBACK_MAX_RATE` 往下限縮之可選倍速。 */
  playbackRates: number[]
  /** 課程已關閉 → 不上報（#255 裁示 Q2：讀照舊、寫全停）。 */
  readOnly: boolean
  /** 覆蓋率變動時通知上層重抓側欄（解鎖狀態可能改變）。 */
  onProgress?: (coverage: number) => void
}

/**
 * HTML5 影片播放器（AC 3 / AC 4 / #274 進度上報）。
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
 * ## 進度上報（#274）
 *
 * `play` 記起點、`pause` / `seeked` / `ended` 送出一段——邏輯全在
 * [`playbackTracker`](./playbackTracker.ts)，本元件只負責接線與送出。
 *
 * ⚠️ **不用 `timeupdate` 累加**：它每秒觸發約 4 次，用它累加等於在前端做聯集，而前端
 * 沒有既有區段可比對。這裡只用它記下「最後觀察到的位置」，供 `seeked` 取跳躍前的終點。
 *
 * **教師預覽照常上報**：後端對擁有者預覽是靜默忽略（回 200 不寫入）。前端不自行判斷
 * `is_owner` 就跳過——教師若真的用邀請碼加入自己的課，他就是學員，進度該照常累積，
 * 而前端分不出這兩種情況。
 */
export function VideoPlayer({ video, playbackRates, readOnly, onProgress }: Props) {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rate, setRate] = useState(1)
  const [coverage, setCoverage] = useState(video.coverage_pct)
  const videoRef = useRef<HTMLVideoElement>(null)
  /** 票過期只重試一次——換了新票仍失敗表示不是過期問題，再重試會變無窮迴圈。 */
  const retriedRef = useRef(false)
  const trackerRef = useRef<TrackerState>(IDLE_TRACKER)
  const bufferRef = useRef<Segment[]>([])
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  /** 只在首次載入復位；換票重載走 `handleVideoError` 自己的復位。 */
  const resumedRef = useRef(false)
  /** 收尾只跑一次——`visibilitychange`(hidden) 與 `pagehide` 在關閉分頁時**都會**觸發。 */
  const finishedRef = useRef(false)
  /**
   * 最後已知的播放位置。
   *
   * ⚠️ **收尾時不可讀 `videoRef.current?.currentTime`**：`useEffect` 的 cleanup 是
   * passive effect，React 在跑它**之前**就已經把 DOM ref 設成 `null`。於是切換項目
   * （最常見的離開方式）時 `currentTime` 會讀成 `0`——
   *
   * - `endSegment(tracker, 0)`：`0 > anchor` 恆為假 → **最後那一段被整個丟掉**
   * - `last_position_sec: 0`：後端對非 `null` 值一律覆寫 → **把續看位置重置為 0**（AC 11 壞掉）
   *
   * 故一律以本 ref 為位置來源，由各事件處理器同步更新。
   */
  const lastTimeRef = useRef(0)

  /**
   * 送出緩衝中的區段。
   *
   * **失敗靜默**——這條路徑常在「離開頁面」時執行，跳錯誤訊息學員也處理不了；而後端
   * 的覆蓋率一律先聯集再算，下次補送同一段不會灌水。
   */
  const flushNow = useCallback(async () => {
    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    const pending = bufferRef.current
    if (readOnly || pending.length === 0) return
    bufferRef.current = []
    try {
      const result = await progressApi.reportIntervals(video.video_id, pending, Math.floor(lastTimeRef.current))
      setCoverage(result.coverage_pct)
      onProgress?.(result.coverage_pct)
    } catch {
      // 靜默：下次離開時後端仍能由既有區段算出正確覆蓋率
    }
  }, [onProgress, readOnly, video.video_id])

  /**
   * 收下一段並決定何時送出。
   *
   * ⚠️ **`segment` 為 `null` 時仍要 flush**（非 debounce 路徑）：學員拖動進度條後直接
   * 暫停，那次 `pause` 產生不了新區段，但緩衝裡還躺著剛才 `seeked` 的那幾段。若因為
   * 「沒有新東西」就提早返回，它們得等 2 秒的計時器——而學員可能在那之前就切走了。
   */
  const enqueue = useCallback(
    (segment: Segment | null, { debounce = false }: { debounce?: boolean } = {}) => {
      if (readOnly) return
      if (segment !== null) bufferRef.current = [...bufferRef.current, segment]
      if (!debounce) {
        void flushNow()
        return
      }
      if (segment === null) return
      if (flushTimerRef.current !== null) clearTimeout(flushTimerRef.current)
      flushTimerRef.current = setTimeout(() => void flushNow(), SEEK_FLUSH_DELAY_MS)
    },
    [flushNow, readOnly],
  )

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
   * 離開時收尾：送出殘留區段 + normalize（AC 2）。
   *
   * `visibilitychange`（hidden）而非 `beforeunload`——後者在行動裝置與分頁切換時常常
   * 不觸發，而「切到別的分頁去做別的事」正是最常見的離開方式。`pagehide` 補上真正
   * 關閉分頁的情形。
   *
   * ⚠️ 這兩個時機都**不保證請求送得出去**。可以接受，因為 normalize 只是儲存壓縮：
   * 沒跑成功只是後端的列數變多，覆蓋率照樣正確（AC 3）。
   */
  useEffect(() => {
    if (readOnly) return
    const finish = () => {
      // 關閉分頁時 `visibilitychange`(hidden) 與 `pagehide` 會接連觸發。不去重的話會對
      // 同一支影片送出兩組並行的「上報 + normalize」——首次觀看該影片時兩個請求會同時
      // 嘗試建立 `ET_PROGRESS_VIDEO` 那一列。後端已改用 `ON CONFLICT` 擋住競態，此處
      // 去重則是連多餘的請求都不要送。
      if (finishedRef.current) return
      finishedRef.current = true
      const { segment } = endSegment(trackerRef.current, lastTimeRef.current)
      trackerRef.current = IDLE_TRACKER
      if (segment !== null) bufferRef.current = [...bufferRef.current, segment]
      void flushNow().then(() => progressApi.normalize(video.video_id).catch(() => undefined))
    }
    const onVisibility = () => {
      if (document.visibilityState === "hidden") finish()
      // 切回分頁 → 學員還要繼續看，解除旗標讓下次離開能再收尾一次
      if (document.visibilityState === "visible") finishedRef.current = false
    }
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("pagehide", finish)
    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("pagehide", finish)
      // 切換教材 / 離開頁面：同樣要收尾，否則最後一段永遠不會被送出
      finish()
    }
  }, [flushNow, readOnly, video.video_id])

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

  /**
   * 續看定位（AC 11 的後半）。
   *
   * 只做一次——`handleVideoError` 換票重載時有自己的復位點（復到當下位置，不是上次
   * 的位置），兩者搶著設 `currentTime` 會把學員丟回更早的地方。
   *
   * 已看到最後一秒者不復位：那等於一按播放就立刻結束，看起來像壞掉。
   */
  function handleLoadedMetadata() {
    const el = videoRef.current
    const resumeAt = video.last_position_sec
    if (el === null || resumedRef.current || resumeAt === null || resumeAt <= 0) return
    resumedRef.current = true
    // 已看到最後一秒者不復位——那等於一按播放就立刻結束，看起來像壞掉。
    // `Math.max(0, ...)` 讓 1 秒以內的極短影片不會因為門檻變成負數而永遠不復位。
    if (resumeAt < Math.max(0, video.duration_sec - 1)) el.currentTime = resumeAt
  }

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2">{video.file_name}</Typography>
        {coverage >= COVERAGE_THRESHOLD_PCT && <Chip size="small" color="success" label="已完成" />}
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}

      {src && (
        <Box
          component="video"
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          onError={() => void handleVideoError()}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={(e) => {
            lastTimeRef.current = e.currentTarget.currentTime
            trackerRef.current = beginSegment(e.currentTarget.currentTime)
          }}
          onTimeUpdate={(e) => {
            lastTimeRef.current = e.currentTarget.currentTime
            trackerRef.current = observeTime(trackerRef.current, e.currentTarget.currentTime)
          }}
          onPause={(e) => {
            lastTimeRef.current = e.currentTarget.currentTime
            const result = endSegment(trackerRef.current, e.currentTarget.currentTime)
            trackerRef.current = result.state
            enqueue(result.segment)
          }}
          onSeeked={(e) => {
            const result = seekTo(trackerRef.current, e.currentTarget.currentTime, {
              paused: e.currentTarget.paused,
            })
            lastTimeRef.current = e.currentTarget.currentTime
            trackerRef.current = result.state
            // 拖動進度條會連續觸發——這是唯一需要緩衝的事件
            enqueue(result.segment, { debounce: true })
          }}
          onEnded={(e) => {
            lastTimeRef.current = e.currentTarget.currentTime
            const result = endSegment(trackerRef.current, e.currentTarget.currentTime)
            trackerRef.current = result.state
            enqueue(result.segment)
          }}
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

      {!readOnly && (
        <Box sx={{ pt: 0.5 }}>
          <LinearProgress
            variant="determinate"
            value={Math.min(100, coverage)}
            color={coverage >= COVERAGE_THRESHOLD_PCT ? "success" : "primary"}
            aria-label="影片觀看進度"
          />
          <Typography variant="caption" color="text.secondary">
            {coverage >= COVERAGE_THRESHOLD_PCT
              ? `完成 ${coverage}%`
              : `完成 ${coverage}%（達 ${COVERAGE_THRESHOLD_PCT}% 後解鎖下一項）`}
          </Typography>
        </Box>
      )}
    </Stack>
  )
}

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, "0")}`
}
