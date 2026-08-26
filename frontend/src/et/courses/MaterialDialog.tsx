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

interface MaterialDialogProps {
  open: boolean
  loading: boolean
  readOnly: boolean
  material: MaterialDetail | null
  dmOptions: DmDocOption[]
  /** 三類媒材皆空時的提示——與後端 `ET_MATERIAL_002` 同一條規則。 */
  error: string | null
  uploading: boolean
  onClose: () => void
  onSave: (values: { material_name: string; description_html: string | null }) => void
  onUploadVideo: (file: File) => void
  onDeleteVideo: (video: VideoRow) => void
  onAddDoc: (docId: string) => void
  onDeleteDoc: (doc: DocRow) => void
}

/** 影片列：檔名 + 長度 + 大小 + 刪除。 */
function VideoItem({ video, readOnly, onDelete }: { video: VideoRow; readOnly: boolean; onDelete: () => void }) {
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
          <IconButton size="small" color="error" aria-label={`刪除影片 ${video.file_name}`} onClick={onDelete}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        )}
      </Stack>
    </Paper>
  )
}

/** DM 文件引用列：名稱 + 版號 + 廢止 / 失效標記 + 刪除。 */
function DocItem({ doc, readOnly, onDelete }: { doc: DocRow; readOnly: boolean; onDelete: () => void }) {
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
        {doc.unavailable && (
          <Chip size="small" color="error" icon={<ErrorOutlineIcon />} label="文件已失效" />
        )}
        {!readOnly && (
          <IconButton size="small" color="error" aria-label={`移除文件引用 ${doc.doc_id}`} onClick={onDelete}>
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
 * 三類媒材（說明文字 / 影片 / DM 文件引用）各自獨立操作：
 *
 * - **說明文字**隨「儲存」一起送出（純表單欄位）
 * - **影片與文件引用**是**即時生效**的——選檔即上傳、點刪即刪除，不等按儲存
 *
 * 這個不對稱是刻意的：影片上傳是長時間操作（500 MB），塞進儲存流程會讓使用者
 * 盯著一個沒有進度的按鈕；文件引用則需要即時向 DM 確認可用性。故兩者一動作一請求，
 * 「儲存」只負責名稱與說明文字。
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
  onDeleteVideo,
  onAddDoc,
  onDeleteDoc,
}: MaterialDialogProps) {
  const [name, setName] = useState("")
  const [descriptionHtml, setDescriptionHtml] = useState("")
  const [loadedId, setLoadedId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // render 期間衍生 state（不放 useEffect）——載入新教材時把表單重設為它的值。
  // 以 material_id 判斷而非 open：同一個視窗切換不同教材時 open 不會變。
  if (material && loadedId !== material.material_id) {
    setLoadedId(material.material_id)
    setName(material.material_name)
    setDescriptionHtml(material.description_html ?? "")
  }
  if (!open && loadedId !== null) setLoadedId(null)

  const handleSave = () => {
    const trimmed = descriptionHtml.trim()
    onSave({
      material_name: name,
      // 空編輯器會產出 `<p></p>` 之類的空殼——原樣送出會讓後端誤判為「有說明文字」，
      // 使一個實際空白的教材通過「至少擇一媒材」的檢核。
      description_html: isBlankHtml(trimmed) ? null : trimmed,
    })
  }

  const hasNoMedia =
    (material?.videos.length ?? 0) === 0 &&
    (material?.docs.length ?? 0) === 0 &&
    isBlankHtml(descriptionHtml)

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
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
              <Alert severity="info">
                教材須至少提供影片、文件或說明文字其中一項才能儲存。
              </Alert>
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
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2">影片檔</Typography>
                {!readOnly && (
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={uploading ? <CircularProgress size={16} /> : <CloudUploadIcon />}
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {uploading ? "上傳中⋯" : "選擇影片"}
                  </Button>
                )}
              </Stack>
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/webm,.mp4,.webm"
                hidden
                aria-label="選擇影片檔"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) onUploadVideo(file)
                  // 清掉 value，否則選同一支檔案第二次不會觸發 change
                  e.target.value = ""
                }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                支援 mp4 / webm，單檔最大 500 MB。影片長度由系統自動解析——解析不出的檔案無法上傳。
              </Typography>
              <Stack spacing={0.75}>
                {material?.videos.map((video) => (
                  <VideoItem
                    key={video.video_id}
                    video={video}
                    readOnly={readOnly}
                    onDelete={() => onDeleteVideo(video)}
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
                  options={dmOptions}
                  getOptionLabel={(option) => option.doc_name}
                  isOptionEqualToValue={(option, value) => option.doc_id === value.doc_id}
                  value={null}
                  blurOnSelect
                  onChange={(_, selected) => selected && onAddDoc(selected.doc_id)}
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
                {material?.docs.map((doc) => (
                  <DocItem key={doc.mat_doc_id} doc={doc} readOnly={readOnly} onDelete={() => onDeleteDoc(doc)} />
                ))}
              </Stack>
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{readOnly ? "關閉" : "取消"}</Button>
        {!readOnly && (
          <Button variant="contained" disabled={loading || uploading} onClick={handleSave}>
            儲存
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
