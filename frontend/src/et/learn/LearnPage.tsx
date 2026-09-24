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
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"

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
 * | AC 12 測驗未及格阻擋 | ✅ #361（提示依 `blocking_item_type` 分兩種；0 題測驗不當閘門）|
 * | AC 18–21 課後問卷入口 | ✅ #284（側欄底部，狀態由後端導出）|
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
  const [searchParams] = useSearchParams()
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
  //
  // ⚠️ **退回的候選都要濾掉鎖定項目**：教師事後調整章節順序後，`last_item_id` 可能指向
  // 一個現在已鎖定的項目。
  //
  // 🔴 **本過濾是 UX 層，不是防線**（#424 之後）。三支讀取端點（教材內容 / 播放票 /
  // DM 取檔）已於後端掛上解鎖判定，未解鎖的內容拿不到。留著它的理由只剩一個：
  // **不要把使用者送到一個必然 404 的畫面**——落在鎖定項目上會是一片空白的內容區，
  // 而他沒做錯任何事。
  //
  // ⛔ 別把它當成「鎖定內容的保護」而在別處省掉後端判定。`progress/service.py` 的模組
  // docstring 講得很清楚：AC 9 寫的是系統阻擋，不是畫面不給點。
  //
  // 📌 沿革：此處原本寫的理由是「不濾的話會對它送出 `markViewed`、後端回 404」——
  // 那個理由早已被下方 `activeItemIdForEffect` 的 `!active.locked` 涵蓋（#416 查證）；
  // 接著改寫為「防止未解鎖內容被渲染」，而那一半已於 #424 由後端接手。
  const allItems = data?.chapters.flatMap((c) => c.items) ?? []
  const openable = allItems.filter((i) => !i.locked)

  // #416：測驗結果頁以 `?quiz=` 指定落點，**優先於所有推導**。
  //
  // 原本結果頁只導 `/learn`，落點交給下方三段 fallback。而 `last_item_id` 那段外面包了
  // `openable`，指到的項目一旦鎖定就被靜默丟棄、掉到 `openable[0]`＝第一章第一項——
  // 同一顆「回課程重新作答」兩次會落在不同地方。即使沒掉到第三段，`last_item_id` 也只是
  // 「上次檢視的項目」，本來就不保證等於他剛考完的那個測驗。
  //
  // 用 `quiz_id` 而非 `item_id` 對應：`AttemptResult` 本來就帶 `quiz_id`，而每個項目也
  // 都有 `quiz_id`——後端不必多存一份 item 快照。⛔ 不在閱卷路徑上現查 item：
  // `attempt/service.py` 已說明那條反查在章節被刪時會 raise，而它位在閱卷 flush 之後，
  // 一 raise 就把剛寫入的成績一起回滾掉。
  const requestedQuizId = Number(searchParams.get("quiz")) || null
  const requested = requestedQuizId === null ? null : (allItems.find((i) => i.quiz_id === requestedQuizId) ?? null)

  const active =
    allItems.find((i) => i.item_id === activeItemId) ??
    // 鎖定時**不**採用——改由下方的提示告知原因，而不是把未解鎖項目顯示出來。
    (requested !== null && !requested.locked ? requested : null) ??
    openable.find((i) => i.item_id === data?.last_item_id) ??
    openable[0] ??
    null

  // 切換項目時記錄「正在看這一項」；純文件 / 說明文字項目一併標記完成（AC 10）。
  //
  // ⚠️ 依賴只放 `item_id`——放整個 `active` 物件會在每次 query 重抓時觸發（物件identity
  // 變了），而本 effect 自己就會 invalidate 那個 query，於是變成無窮迴圈。
  const activeItemIdForEffect = active !== null && !active.locked ? active.item_id : null
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
   *
   * 🔴 **提示依前緣的型別分兩種**（#361）。AC 12 啟用前，鎖定的唯一成因是教材沒看完，
   * 寫死「請先完成本章節之影片學習」永遠是對的；啟用後多了「測驗未通過」這個成因，
   * 同一句話會把學員指向**錯的動作**——叫他去看早就看完的影片，而他該做的是重考。
   *
   * ⛔ 不要在前端自行推導前緣（例如掃 `chapters` 找第一個 `!completed`）：那會漏掉
   * 「0 題測驗不當閘門」的例外而指向一個不是真兇的項目。後端已算好。
   */
  const blockingItemType = data?.blocking_item_type ?? null
  const handleSelect = useCallback(
    (item: ItemNode) => {
      if (item.locked) {
        message.warning(
          blockingItemType === "QUIZ"
            ? "請通過本章節之測驗後解鎖" // ET-MSG-ET05-002
            : "請先完成本章節之影片學習", // ET-MSG-ET05-001
        )
        return
      }
      setActiveItemId(item.item_id)
    },
    [message, blockingItemType],
  )

  /**
   * #416 AC 4：`?quiz=` 指定的項目**當下鎖定**時，明確說明而不是靜默落到別處。
   *
   * ⚠️ 這條路今天很難走到：學員能開始作答代表該項目當時未鎖定，而
   * `progress/rules.locked_item_ids` 的「已完成永不鎖定」使**考不及格不會讓它自己變鎖定**。
   * 成立情境是這中間教師調整了章節順序，或要求已通過學員重測（#361）而使後續項目回鎖。
   *
   * ⛔ 刻意**沿用側欄點選的同一組訊息**，而不是把鎖定項目顯示出來——後者等於做出一個
   * 通用的「顯示未解鎖項目」能力，而未解鎖**教材**的內容端點後端並不擋
   * （見 `learning/service.py` 算 `locked` 那段的註解），那會直接開一個洞。
   *
   * `warnedQuizIdRef` 讓同一個目標只提示一次：本元件會因 query 重抓而多次 render，
   * 少了它每次都會再彈一個 snackbar。
   */
  const requestedLockedQuizId = requested !== null && requested.locked ? requested.quiz_id : null
  const warnedQuizIdRef = useRef<number | null>(null)
  useEffect(() => {
    if (requestedLockedQuizId === null || warnedQuizIdRef.current === requestedLockedQuizId) return
    warnedQuizIdRef.current = requestedLockedQuizId
    message.warning(
      blockingItemType === "QUIZ"
        ? "請通過本章節之測驗後解鎖" // ET-MSG-ET05-002
        : "請先完成本章節之影片學習", // ET-MSG-ET05-001
    )
  }, [requestedLockedQuizId, blockingItemType, message])

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
            showProgress={!data.is_owner}
            survey={data.survey}
            onSurveyClick={() => navigate(`/et/courses/${courseId}/survey`)}
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
