import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useQuery } from "@tanstack/react-query"

import { DocViewer } from "./DocViewer"
import { VideoPlayer } from "./VideoPlayer"
import type { ItemNode } from "./learnSchemas"
import { learnApi } from "./learnService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

interface Props {
  item: ItemNode | null
  playbackRates: number[]
  /** 課程已關閉 → 播放器不上報進度（#255 裁示 Q2：讀照舊、寫全停）。 */
  readOnly: boolean
  /** 影片覆蓋率變動 → 通知上層重抓側欄（解鎖狀態可能改變）。 */
  onProgress: () => void
}

/** ET05 中間內容區——依項目型別切換（AC 1 / 3 / 9 / 10 / 15–17）。 */
export function ContentPane({ item, playbackRates, readOnly, onProgress }: Props) {
  if (item === null) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="body2" color="text.secondary">
          請自左側選擇要學習的項目。
        </Typography>
      </Paper>
    )
  }
  if (item.item_type === "QUIZ") return <QuizEntry item={item} />
  if (item.material_id === null) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Alert severity="warning">此教材內容不完整，請聯繫課程教師</Alert>
      </Paper>
    )
  }
  return (
    <MaterialPane
      materialId={item.material_id}
      playbackRates={playbackRates}
      readOnly={readOnly}
      onProgress={onProgress}
    />
  )
}

/**
 * 測驗項目（AC 10）。
 *
 * `ET-6` 未實作——**顯示入口但點擊只給提示**，不 `navigate` 到不存在的路由（那會給
 * 學員一個白畫面，看起來像壞掉而不像還沒做）。比照 #247 對 `ET-5` 的處理。
 */
function QuizEntry({ item }: { item: ItemNode }) {
  const { message } = useNotification()
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2} alignItems="flex-start">
        <Typography variant="h6">{item.title}</Typography>
        <Button variant="contained" onClick={() => message.info("線上測驗尚未開放")}>
          開始測驗
        </Button>
      </Stack>
    </Paper>
  )
}

function MaterialPane({
  materialId,
  playbackRates,
  readOnly,
  onProgress,
}: {
  materialId: number
  playbackRates: number[]
  readOnly: boolean
  onProgress: () => void
}) {
  const { data, isPending, error } = useQuery({
    queryKey: QUERY_KEYS.etLearn.material(materialId),
    queryFn: () => learnApi.materialContent(materialId),
    retry: (failureCount, err) => toApiError(err).status >= 500 && failureCount < 2,
  })

  if (isPending) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <CircularProgress size={24} />
      </Paper>
    )
  }
  if (error) {
    const api = toApiError(error)
    // AC 22 / ET-MSG-ET05-004：教師刪除學員正在檢視之章節
    const deleted = api.errorCode === "ET_LEARN_003"
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Alert severity={deleted ? "info" : "error"}>{deleted ? "此內容已刪除" : api.errorMessage}</Alert>
      </Paper>
    )
  }

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2.5}>
        <Typography variant="h6">{data.material_name}</Typography>

        {data.description_html && (
          <>
            {/*
              說明文字為教師以 RichTextEditor 撰寫之 HTML。**於寫入時由後端
              `common/html_sanitize.sanitize_material_html` 清洗**（`material/service.py`），
              故此處直接渲染。前端不再 sanitize 一次——那會讓「哪一份才是權威」變得
              不清楚，而兩份規則遲早分岔。
            */}
            <Box
              sx={{ "& img": { maxWidth: "100%" }, "& p": { my: 1 } }}
              dangerouslySetInnerHTML={{ __html: data.description_html }}
            />
            <Divider />
          </>
        )}

        {data.videos.map((video) => (
          <VideoPlayer
            key={video.video_id}
            video={video}
            playbackRates={playbackRates}
            readOnly={readOnly}
            onProgress={onProgress}
          />
        ))}

        {data.docs.length > 0 && data.videos.length > 0 && <Divider />}

        {data.docs.map((doc) => (
          <DocViewer key={doc.doc_id} materialId={materialId} doc={doc} />
        ))}

        {!data.description_html && data.videos.length === 0 && data.docs.length === 0 && (
          <Alert severity="info">此教材尚無內容。</Alert>
        )}
      </Stack>
    </Paper>
  )
}
