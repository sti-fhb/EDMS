import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
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
import { QuizIntroPanel } from "../quiz/QuizIntroPanel"
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
 * 測驗項目入口（AC 10）。
 *
 * 測驗資訊**就地呈現**——影片與文件都是點了就看得到內容，測驗沒有理由先給一顆按鈕、
 * 按了才跳到另一頁看題數與及格分數。`ET-6a`（#279）原本導向 `/et/quizzes/:quizId`，
 * 該頁已移除，內容改由 [QuizIntroPanel](../quiz/QuizIntroPanel.tsx) 在此渲染。
 *
 * `quiz_id` 為 `null` 屬資料異常（項目型別是測驗卻沒有測驗），由面板自行提示。
 */
function QuizEntry({ item }: { item: ItemNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      {item.quiz_id === null ? (
        <Alert severity="warning">此測驗內容不完整，請聯繫課程教師</Alert>
      ) : (
        <QuizIntroPanel quizId={item.quiz_id} />
      )}
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
