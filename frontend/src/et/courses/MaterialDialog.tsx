import CloudUploadIcon from "@mui/icons-material/CloudUpload"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined"
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline"
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline"
import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useRef, useState } from "react"

import { RichTextEditor } from "./RichTextEditor"
import { MATERIAL_NAME_MAX_LEN, formatDuration, formatFileSize, isBlankHtml } from "./itemSchemas"
import type { DmDocOption, DocRow, MaterialDetail, VideoRow } from "./itemSchemas"

export interface MaterialSavePayload {
  material_name: string
  description_html: string | null
  /** 最終要引用的 DM 文件（全量覆寫；未列出的既有引用會被刪除）。 */
  doc_ids: string[]
  /** 最終要保留的影片 ID（未列出者視為刪除）。 */
  video_ids: number[]
}

interface MaterialDialogProps {
  open: boolean
  loading: boolean
  readOnly: boolean
  material: MaterialDetail | null
  dmOptions: DmDocOption[]
  error: string | null
  uploading: boolean
  /** `dirty` 為 true 表示有未儲存的變更，由呼叫端決定是否先確認。 */
  onClose: (dirty: boolean) => void
  onSave: (values: MaterialSavePayload) => void
  onUploadVideo: (file: File) => void
}

/** 影片列：檔名 + 長度 + 大小 + 移除。 */
function VideoItem({ video, readOnly, onRemove }: { video: VideoRow; readOnly: boolean; onRemove: () => void }) {
  return (
    <Paper variant="outlined" sx={{ p: 1, bgcolor: "background.default" }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <PlayCircleOutlineIcon fontSize="small" color="error" />
        <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
          {video.file_name}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
          {formatFileSize(video.file_size_bytes)} ｜ {formatDuration(video.duration_sec)}
        </Typography>
        {!readOnly && (
          <IconButton size="small" color="error" aria-label={`移除影片 ${video.file_name}`} onClick={onRemove}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Stack>
    </Paper>
  )
}

/** DM 文件引用列：名稱 + 版號 + 廢止 / 失效標記 + 移除。 */
function DocItem({ doc, readOnly, onRemove }: { doc: DocRow; readOnly: boolean; onRemove: () => void }) {
  return (
    <Paper variant="outlined" sx={{ p: 1, bgcolor: "background.default" }}>
      <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
        <DescriptionOutlinedIcon fontSize="small" color="primary" />
        <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
          {doc.doc_name ?? doc.doc_id}
        </Typography>
        {doc.version_no && (
          <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
            {doc.doc_id} {doc.version_no}
          </Typography>
        )}
        {/* 常駐標記而非 snackbar——需要指出「是哪一筆」有問題（訊息類型視覺規則） */}
        {doc.obsolete && <Chip size="small" color="warning" label="此文件已廢止" />}
        {doc.unavailable && <Chip size="small" color="error" icon={<ErrorOutlineIcon />} label="文件已失效" />}
        {!readOnly && (
          <IconButton size="small" color="error" aria-label={`移除文件引用 ${doc.doc_id}`} onClick={onRemove}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Stack>
    </Paper>
  )
}

/**
 * 教材編輯視窗（ET02）。
 *
 * ## 除了影片上傳，一切都等到按「儲存」才生效
 *
 * 名稱、說明文字、文件引用的增刪、影片的移除——全部只改本地狀態，按儲存時以
 * `PUT /materials/{id}` 送**最終狀態**一次套用。按取消就什麼都沒發生。
 *
 * 原本文件是逐筆即時生效的（加一筆打一次 API），2026-08-26 實測發現兩個問題：
 *
 * 1. **「取消」不再是取消**——刪掉一份文件再按取消，那次刪除早就送出去了
 * 2. **「至少擇一媒材」被繞過**——刪到一份不剩時沒有檢核，教材直接變成空的
 *
 * **影片上傳是唯一的例外**：檔案傳輸沒辦法暫存在請求裡（單檔上限 500 MB），
 * 一選檔就送出。代價是上傳後按取消影片仍在——但那不會造成空教材，使用者可再
 * 開啟教材把它移除。
 */
export function MaterialDialog({
  open,
  loading,
  readOnly,
  material,
  dmOptions,
  error,
  uploading,
  onClose,
  onSave,
  onUploadVideo,
}: MaterialDialogProps) {
  const [name, setName] = useState("")
  const [descriptionHtml, setDescriptionHtml] = useState("")
  const [docs, setDocs] = useState<DocRow[]>([])
  const [videoIds, setVideoIds] = useState<number[]>([])
  const [loadedId, setLoadedId] = useState<number | null>(null)
  const [loadedVideos, setLoadedVideos] = useState("")
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  /**
   * 尚未落地之引用的暫時 id（遞減計數器）。
   *
   * **不可由陣列索引推導**——移除中間一筆後其餘索引會變動，React 會誤判為同一個
   * 元件而重用實例。#202 的章節拖拉就是這樣壞掉的。
   */
  const nextStagedId = useRef(-1)

  // render 期間衍生 state（不放 useEffect）。以 material_id 判斷而非 open：
  // 同一個視窗切換不同教材時 open 不會變。
  //
  // 上傳影片後 material 會重新載入（多一筆影片），此時**只同步影片清單**——
  // 若連表單一起重設，使用者正在打的說明文字會被自己的上傳動作沖掉。
  const videoSignature = material?.videos.map((v) => v.video_id).join(",") ?? ""
  if (material && (loadedId !== material.material_id || videoSignature !== loadedVideos)) {
    const switchedMaterial = loadedId !== material.material_id
    setLoadedId(material.material_id)
    setLoadedVideos(videoSignature)
    setVideoIds(material.videos.map((v) => v.video_id))
    if (switchedMaterial) {
      setName(material.material_name)
      setDescriptionHtml(material.description_html ?? "")
      setDocs(material.docs)
    }
  }
  if (!open && loadedId !== null) {
    setLoadedId(null)
    setLoadedVideos("")
  }

  // 空編輯器會產出 `<p></p>` 之類的空殼——原樣送出會讓後端誤判為「有說明文字」，
  // 使一個實際空白的教材通過「至少擇一媒材」的檢核。
  const cleanedHtml = isBlankHtml(descriptionHtml) ? null : descriptionHtml.trim()
  const keptVideos = material?.videos.filter((v) => videoIds.includes(v.video_id)) ?? []

  const isDirty =
    material !== null &&
    (name !== material.material_name ||
      cleanedHtml !== material.description_html ||
      docs.map((d) => d.doc_id).join(",") !== material.docs.map((d) => d.doc_id).join(",") ||
      videoIds.length !== material.videos.length)

  const hasNoMedia = keptVideos.length === 0 && docs.length === 0 && cleanedHtml === null

  const addDoc = (option: DmDocOption) => {
    if (docs.some((d) => d.doc_id === option.doc_id)) return
    setDocs((prev) => [
      ...prev,
      {
        mat_doc_id: nextStagedId.current--,
        doc_id: option.doc_id,
        doc_name: option.doc_name,
        version_no: option.version_no,
        obsolete: false,
        unavailable: false,
        sort_order: prev.length + 1,
      },
    ])
  }

  const pickFile = (file: File | undefined) => {
    if (file) onUploadVideo(file)
  }

  return (
    <Dialog open={open} onClose={() => onClose(isDirty)} maxWidth="md" fullWidth>
      <DialogTitle>{readOnly ? "檢視教材" : "編輯教材"}</DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Stack alignItems="center" sx={{ py: 6 }}>
            <CircularProgress />
          </Stack>
        ) : (
          <Stack spacing={2.5} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            {!error && hasNoMedia && !readOnly && (
              <Alert severity="info">教材須至少提供影片、文件或說明文字其中一項才能儲存。</Alert>
            )}

            <TextField
              label="項目標題"
              required
              size="small"
              fullWidth
              value={name}
              disabled={readOnly}
              slotProps={{ htmlInput: { maxLength: MATERIAL_NAME_MAX_LEN } }}
              onChange={(e) => setName(e.target.value)}
            />

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                說明文字
              </Typography>
              <RichTextEditor value={descriptionHtml} onChange={setDescriptionHtml} disabled={readOnly} />
            </Box>

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                影片檔
              </Typography>
              {!readOnly && (
                <Box
                  role="button"
                  tabIndex={0}
                  aria-label="拖拉或點擊選擇影片檔"
                  onClick={() => !uploading && fileInputRef.current?.click()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click()
                  }}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragOver(true)
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setDragOver(false)
                    if (!uploading) pickFile(e.dataTransfer.files?.[0])
                  }}
                  sx={{
                    border: 2,
                    borderStyle: "dashed",
                    borderColor: dragOver ? "primary.main" : "divider",
                    borderRadius: 1,
                    bgcolor: dragOver ? "action.hover" : "action.disabledBackground",
                    py: 3,
                    textAlign: "center",
                    cursor: uploading ? "default" : "pointer",
                    mb: 1,
                  }}
                >
                  {uploading ? (
                    <Stack alignItems="center" spacing={1}>
                      <CircularProgress size={28} />
                      <Typography variant="body2" color="text.secondary">
                        上傳中⋯
                      </Typography>
                    </Stack>
                  ) : (
                    <Stack alignItems="center" spacing={0.5}>
                      <CloudUploadIcon sx={{ fontSize: 32, color: "text.disabled" }} />
                      <Typography variant="body2" color="text.secondary">
                        拖拉上傳影片檔或點擊選擇
                      </Typography>
                      <Typography variant="caption" color="text.disabled">
                        支援 mp4 / webm，單檔最大 500 MB
                      </Typography>
                    </Stack>
                  )}
                </Box>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/webm,.mp4,.webm"
                hidden
                aria-label="選擇影片檔"
                onChange={(e) => {
                  pickFile(e.target.files?.[0])
                  // 清掉 value，否則選同一支檔案第二次不會觸發 change
                  e.target.value = ""
                }}
              />
              {!readOnly && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                  影片<strong>選檔後立即上傳</strong>（檔案無法暫存），其餘變更按「儲存」才生效。
                  長度由系統自動解析，解析不出的檔案無法上傳。
                </Typography>
              )}
              <Stack spacing={0.75}>
                {keptVideos.map((video) => (
                  <VideoItem
                    key={video.video_id}
                    video={video}
                    readOnly={readOnly}
                    onRemove={() => setVideoIds((prev) => prev.filter((id) => id !== video.video_id))}
                  />
                ))}
              </Stack>
            </Box>

            <Box>
              <Typography variant="subtitle2" gutterBottom>
                教材文件
              </Typography>
              {!readOnly && (
                <Autocomplete
                  size="small"
                  options={dmOptions.filter((o) => !docs.some((d) => d.doc_id === o.doc_id))}
                  getOptionLabel={(option) => option.doc_name}
                  isOptionEqualToValue={(option, value) => option.doc_id === value.doc_id}
                  value={null}
                  blurOnSelect
                  onChange={(_, selected) => selected && addDoc(selected)}
                  renderOption={(props, option) => (
                    <li {...props} key={option.doc_id}>
                      <Stack sx={{ width: "100%" }}>
                        <Typography variant="body2">{option.doc_name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {option.doc_id} {option.version_no}
                        </Typography>
                      </Stack>
                    </li>
                  )}
                  renderInput={(params) => (
                    <TextField {...params} label="從 DM「訓練教材」選取" placeholder="輸入關鍵字搜尋" />
                  )}
                  sx={{ mb: 1 }}
                />
              )}
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                僅列出 DM「訓練教材」分類之已發布文件；引用後恆帶最新發布版，DM 改版時自動更新。
              </Typography>
              <Stack spacing={0.75}>
                {docs.map((doc) => (
                  <DocItem
                    key={doc.mat_doc_id}
                    doc={doc}
                    readOnly={readOnly}
                    onRemove={() => setDocs((prev) => prev.filter((d) => d.mat_doc_id !== doc.mat_doc_id))}
                  />
                ))}
              </Stack>
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => onClose(isDirty)}>{readOnly ? "關閉" : "取消"}</Button>
        {!readOnly && (
          <Button
            variant="contained"
            disabled={loading || uploading}
            onClick={() =>
              onSave({
                material_name: name,
                description_html: cleanedHtml,
                doc_ids: docs.map((d) => d.doc_id),
                video_ids: videoIds,
              })
            }
          >
            儲存
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
