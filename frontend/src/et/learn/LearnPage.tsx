import ArrowBackIcon from "@mui/icons-material/ArrowBack"
import VisibilityIcon from "@mui/icons-material/Visibility"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import CircularProgress from "@mui/material/CircularProgress"
import Grid from "@mui/material/Grid"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import { ChapterNav } from "./ChapterNav"
import { ContentPane } from "./ContentPane"
import type { ItemNode } from "./learnSchemas"
import { learnApi } from "./learnService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { toApiError } from "../../services/http"

/**
 * ET05 章節學習頁（US5 / #255）。
 *
 * ## 本 issue 的範圍（`ET-5a`）
 *
 * 「看得到內容」——左側導覽 + 中間內容區，影片可播、PDF 可看、非 PDF 可下載。
 * **完全不寫入任何進度表**；「看了算數」（區段上報、覆蓋率、解鎖、上次位置恢復）
 * 屬 `ET-5b`。
 *
 * | spec | 為何到不了 | 做到哪 |
 * |---|---|---|
 * | AC 3 定位至上次觀看位置 | `ET_PROGRESS`（`ET-5b`）| 定位第 1 章第 1 項（AC 2）|
 * | AC 8–12 解鎖阻擋 | 同上 | 側欄三態 UI 備妥，值恆為「可學習」|
 * | AC 12 測驗作答 | `ET-6` 未實作 | 「開始測驗」入口 + 提示 |
 * | AC 18–21 課後問卷入口 | `ET-15` 未實作 + 需完課判定 | 不顯示 |
 *
 * ## 課程關閉
 *
 * #255 裁示 Q2=A：**讀照舊、寫全停**。關閉只多一條頂部提示，**不過濾任何內容**
 * （依據 Canvas 結課唯讀 / Moodle 結束日期不限制存取之實際做法）。
 */
export function EtLearnPage() {
  const { courseId: courseIdParam } = useParams<{ courseId: string }>()
  const courseId = Number(courseIdParam)
  const navigate = useNavigate()
  const [activeItemId, setActiveItemId] = useState<number | null>(null)

  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etLearn.structure(courseId),
    queryFn: () => learnApi.structure(courseId),
    enabled: Number.isFinite(courseId) && courseId > 0,
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

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

  const allItems = data.chapters.flatMap((c) => c.items)
  // AC 2：首次進入定位至第 1 章節之第 1 項目。
  // `ET-5b` 交付後改為 `ET_PROGRESS.LAST_POSITION` 指向的項目（AC 3）。
  const active = allItems.find((i) => i.item_id === activeItemId) ?? allItems[0] ?? null

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
            onSelect={(item: ItemNode) => setActiveItemId(item.item_id)}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 9 }}>
          <ContentPane item={active} playbackRates={data.playback_rates} />
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
