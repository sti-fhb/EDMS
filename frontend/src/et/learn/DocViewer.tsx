import DownloadIcon from "@mui/icons-material/Download"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { useEffect, useState } from "react"

import type { MaterialDocRow } from "./learnSchemas"
import { fetchDocBlob } from "./learnService"

interface Props {
  materialId: number
  doc: MaterialDocRow
}

/**
 * DM 文件教材之呈現（AC 15 / 16 / 17）。
 *
 * - **PDF**：頁內嵌入預覽
 * - **非 PDF**（Excel / Word 等）：「下載原檔以本機應用程式開啟」
 * - **已廢止**：顯示標籤，但**仍可閱讀**廢止前最後版本
 *
 * ## 為何以 blob 取檔而非直接把 URL 放進 `src`
 *
 * JWT 是 memory-only（刻意不落 cookie），`<iframe src>` / `<a href>` **不會帶
 * Authorization header**，直接放 URL 會 401。故比照 DM `detail/detailService` 的既有
 * 作法：以 axios 取 blob（帶 header）→ `URL.createObjectURL` → 放進 `src`。
 *
 * 文件通常是數百 KB 到數 MB，整份載入沒有問題。**影片不適用此法**（單檔上限 500MB，
 * blob 要整支下載完才能播且失去 Range），見 `VideoPlayer`。
 */
export function DocViewer({ materialId, doc }: Props) {
  const canPreview = doc.available && doc.previewable
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 初值即為「要預覽就是載入中」——**不在 effect 裡同步 setState**（會觸發串聯 render，
  // 且 ESLint 擋）。切換文件時 `ContentPane` 以 `key={doc.doc_id}` 重新掛載本元件，
  // 狀態自然歸零，不需要手動 reset。
  const [loading, setLoading] = useState(canPreview)

  useEffect(() => {
    if (!canPreview) return
    let revoked = false
    let url: string | null = null
    fetchDocBlob(materialId, doc.doc_id)
      .then((blob) => {
        if (revoked) return
        url = URL.createObjectURL(blob)
        setBlobUrl(url)
      })
      .catch(() => {
        if (!revoked) setError("文件載入失敗")
      })
      .finally(() => {
        if (!revoked) setLoading(false)
      })
    return () => {
      revoked = true
      // 不 revoke 會讓每次切換項目都留下一份 blob 在記憶體裡，看影片 / 文件切來切去
      // 幾十次之後就很可觀。
      if (url) URL.revokeObjectURL(url)
    }
  }, [materialId, doc.doc_id, canPreview])

  async function handleDownload() {
    setError(null)
    try {
      const blob = await fetchDocBlob(materialId, doc.doc_id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = doc.file_name ?? doc.doc_id
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("文件下載失敗")
    }
  }

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle2">{doc.doc_name ?? doc.doc_id}</Typography>
        {doc.file_name && (
          <Typography variant="caption" color="text.secondary">
            {doc.file_name}
          </Typography>
        )}
      </Stack>

      {/* AC 17：廢止仍可閱讀廢止前最後版本——標籤是提醒，不是阻擋 */}
      {doc.obsolete && <Alert severity="warning">此文件已廢止</Alert>}

      {!doc.available && <Alert severity="info">此文件目前無法取得，請聯繫課程教師</Alert>}
      {error && <Alert severity="error">{error}</Alert>}

      {canPreview && (
        <Box sx={{ height: 600, border: 1, borderColor: "divider", borderRadius: 1, overflow: "hidden" }}>
          {loading && (
            <Stack alignItems="center" justifyContent="center" sx={{ height: "100%" }}>
              <CircularProgress size={24} />
            </Stack>
          )}
          {blobUrl && (
            <iframe src={blobUrl} title={doc.doc_name ?? doc.doc_id} width="100%" height="100%" style={{ border: 0 }} />
          )}
        </Box>
      )}

      {doc.available && !doc.previewable && (
        <Box>
          <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => void handleDownload()}>
            下載原檔以本機應用程式開啟
          </Button>
        </Box>
      )}
    </Stack>
  )
}
