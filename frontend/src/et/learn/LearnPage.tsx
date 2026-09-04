import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import CircularProgress from "@mui/material/CircularProgress"
import Grid from "@mui/material/Grid"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { ChapterNav } from "./ChapterNav"
import { ContentPane } from "./ContentPane"
import type { ItemNode } from "./learnSchemas"
import { learnApi } from "./learnService"
import { progressApi } from "./progressService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/**
 * ET05 章節學習頁（US5 / #255 + #274）。
 *
 * `ET-5a`（#255）讓學員看得到內容；**`ET-5b`（#274）讓看了算數**——區段上報、覆蓋率、
 * 解鎖判定、定位至上次觀看位置。
 *
 * | spec | 狀態 |
 * |---|---|
 * | AC 3 定位至上次觀看位置 | ✅ #274（`last_item_id` + 影片內 `last_position_sec`）|
 * | AC 8–11 解鎖阻擋 | ✅ #274 |
 * | AC 12 測驗未及格阻擋 | ⛔ `ET-6` 未實作——測驗恆視為通過，不擋住後續 |
 * | AC 18–21 課後問卷入口 | ⛔ `ET-15` 未實作 | 不顯示 |
 *
 * ## 課程關閉
 *
 * #255 裁示 Q2=A：**讀照舊、寫全停**。關閉只多一條頂部提示與「不上報進度」，
 * **不過濾任何內容**（依據 Canvas 結課唯讀 / Moodle 結束日期不限制存取之實際做法）。
 */
export function EtLearnPage() {
  const { courseId: courseIdParam } = useParams<{ courseId: string }>()
  const courseId = Number(courseIdParam)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message } = useNotification()
  const [activeItemId, setActiveItemId] = useState<number | null>(null)

  // 路由參數非數字（網址被手改）時 query 之 `enabled` 為 false，`isPending` 會恆為
  // true——使用者只會看到一個永遠轉不完的圈。提前給明確訊息。
  const courseIdValid = Number.isFinite(courseId) && courseId > 0

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etLearn.structure(courseId),
    queryFn: () => learnApi.structure(courseId),
    enabled: courseIdValid,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  const refreshStructure = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.etLearn.structure(courseId) })
  }, [courseId, queryClient])

  // AC 11 前半：定位至上次檢視之項目；沒有紀錄（或教師預覽）時退回第 1 章第 1 項（AC 2）。
  //
  // 以 `data` 推導而非存進 state：`last_item_id` 是伺服器狀態，複製一份到 state 只會多
  // 一個要同步的來源，而 query 重抓時那份會過期。
  const allItems = data?.chapters.flatMap((c) => c.items) ?? []
  const active =
    allItems.find((i) => i.item_id === activeItemId) ??
    allItems.find((i) => i.item_id === data?.last_item_id) ??
    allItems[0] ??
    null

  // 切換項目時記錄「正在看這一項」；純文件 / 說明文字項目一併標記完成（AC 10）。
  //
  // ⚠️ 依賴只放 `item_id`——放整個 `active` 物件會在每次 query 重抓時觸發（物件identity
  // 變了），而本 effect 自己就會 invalidate 那個 query，於是變成無窮迴圈。
  const activeItemIdForEffect = active?.item_id ?? null
  useEffect(() => {
    if (activeItemIdForEffect === null) return
    let cancelled = false
    progressApi
      .markViewed(activeItemIdForEffect)
      .then((result) => {
        // **只在真的變成已完成時才重抓**——否則每次切換項目都白跑一趟側欄查詢，
        // 而側欄的內容（鎖定 / 完成）在沒有完成任何東西時根本不會變。
        if (!cancelled && result.completed) refreshStructure()
      })
      .catch(() => {
        // 靜默：課程已關閉（409）時本來就不該累積，學員不需要為此看到錯誤
      })
    return () => {
      cancelled = true
    }
  }, [activeItemIdForEffect, refreshStructure])

  /**
   * 側欄點選（AC 6）。
   *
   * 鎖定項目**擋下並提示**（ET-MSG-ET05-001），不是靜默無反應——學員需要知道為什麼
   * 點不動，否則只會以為系統壞了。
   */
  const handleSelect = useCallback(
    (item: ItemNode) => {
      if (item.locked) {
        message.warning("請先完成本章節之影片學習")
        return
      }
      setActiveItemId(item.item_id)
    },
    [message],
  )

  if (!courseIdValid) {
    return (
      <Box>
        <BackButton onBack={() => navigate("/et/my-courses")} />
        <Alert severity="error" sx={{ mt: 2 }}>
          課程代碼無效
        </Alert>
      </Box>
    )
  }
  if (isPending) {
    return (
      <Stack alignItems="center" sx={{ py: 6 }}>
        <CircularProgress />
      </Stack>
    )
  }
  if (error) {
    return (
      <Box>
        <BackButton onBack={() => navigate("/et/my-courses")} />
        <Alert severity="error" sx={{ mt: 2 }}>
          {toApiError(error).errorMessage}
        </Alert>
      </Box>
    )
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <BackButton onBack={() => navigate("/et/my-courses")} />
        <Typography variant="h5">{data.course_name}</Typography>
      </Stack>

      {/* ET-MSG-ET05-005；非阻擋進入之訊息頁，內容照常可看 */}
      {data.is_closed && (
        <Alert severity="info" sx={{ mb: 2 }}>
          此課程目前關閉中，僅可回看已學內容
        </Alert>
      )}

      {/* 教師預覽（#255 裁示 Q1=A）——明示身分，避免他以為自己正在累積進度 */}
      {data.is_owner && (
        <Alert severity="warning" icon={<VisibilityIcon />} sx={{ mb: 2 }}>
          <strong>預覽模式</strong> — 您是本課程的建立者，此頁呈現學員實際看到的內容；預覽不會累積學習進度。
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 3 }}>
          <ChapterNav
            chapters={data.chapters}
            activeItemId={active?.item_id ?? null}
            onSelect={handleSelect}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 9 }}>
          <ContentPane
            item={active}
            playbackRates={data.playback_rates}
            readOnly={data.is_closed}
            onProgress={refreshStructure}
          />
        </Grid>
      </Grid>
    </Box>
  )
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <IconButton size="small" aria-label="返回我的課程" onClick={onBack}>
      <ArrowBackIcon />
    </IconButton>
  )
}
