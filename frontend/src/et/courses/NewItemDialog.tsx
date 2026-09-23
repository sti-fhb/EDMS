import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { ITEM_TITLE_MAX_LEN, ItemTitleSchema } from "./itemSchemas"
import type { ItemType } from "./itemSchemas"

interface NewItemDialogProps {
  /** `null` = 不開啟；有值即為本次要建立的項目型別。 */
  itemType: ItemType | null
  submitting: boolean
  onCancel: () => void
  onConfirm: (title: string) => void
}

/**
 * 新增項目前先取得名稱（ET02 / #414）。
 *
 * ## 為何要多這一個視窗
 *
 * 2026-08-27 曾把名稱改為建立時可留空，理由是「不代填『新教材』——使用者開了視窗第一
 * 件事就是把預設值選起來刪掉」。⭐ **那個判斷仍然成立**，本視窗也沒有代填任何東西。
 *
 * 被推翻的是它的前提：「空名稱只是還沒填的過渡狀態，儲存時後端仍必填」。⚠️ 那對**更新**
 * 路徑成立，但**空殼在按下「新增項目」的當下就已經進 DB 了**，而清理只掛在「取消」上
 * ——換頁、重新整理、按「儲存草稿」都會把一個沒有名稱的項目留在章節裡。2026-09-23
 * 手測即回報此狀況。
 *
 * 故改為**先問名稱、確認才建立**：既不代填也不留空。形狀比照 #386 對課後問卷的處理
 * （「新增問卷改為直接開視窗，名稱於視窗內填、取消不留空問卷」）。
 *
 * ## ⛔ 不要改成「關閉視窗時跳確認框要求補名稱」
 *
 * 教師中途離開是正常行為——手測回報的情境就是「編輯到一半跳掉」。用確認框攔他等於把
 * 正常操作變成障礙，而且攔不住重新整理與按上一頁。要擋就擋在建立的那一刻。
 *
 * ## 條件渲染，不常駐掛載
 *
 * ⚠️ MUI 的 Dialog 即使 `open=false` 也會參與 `aria-hidden` 的簿記，常駐會讓**同檔其他
 * 測試**查不到背景的按鈕而逾時（#361 實測：`CourseEditorPage.test` 由 30/30 變 28/30，
 * 且紅的是別人的測試）。故以 `itemType === null` 判斷是否渲染，而非傳 `open`。
 */
export function NewItemDialog({ itemType, submitting, onCancel, onConfirm }: NewItemDialogProps) {
  const [title, setTitle] = useState("")
  const [error, setError] = useState("")
  const [openedFor, setOpenedFor] = useState<ItemType | null>(null)

  // 每次開啟都從空白開始——留著上一次的輸入會讓教師連續新增兩個項目時，第二個
  // 莫名其妙帶著第一個的名字。
  //
  // ⚠️ **render 期間衍生，不放 `useEffect`**：放進 effect 會觸發
  // `react-hooks` 的 `Calling setState synchronously within an effect can trigger
  // cascading renders`，且多一輪重繪。形狀比照 `MaterialDialog` 的既有做法（該檔註解：「render 期間衍生 state（不放 useEffect）」）。
  if (itemType !== openedFor) {
    setOpenedFor(itemType)
    setTitle("")
    setError("")
  }

  if (itemType === null) return null

  const label = itemType === "MATERIAL" ? "教材" : "測驗"

  const submit = () => {
    const parsed = ItemTitleSchema.safeParse(title)
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "名稱不正確")
      return
    }
    setError("")
    onConfirm(parsed.data)
  }

  return (
    <Dialog open onClose={onCancel} fullWidth maxWidth="xs">
      <DialogTitle>新增{label}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ py: 1 }}>
          <Typography variant="body2" color="text.secondary">
            先為{label}命名，建立後即可接著編輯內容。
          </Typography>
          <TextField
            autoFocus
            size="small"
            fullWidth
            required
            label={`${label}名稱`}
            value={title}
            error={Boolean(error)}
            helperText={error}
            slotProps={{ htmlInput: { maxLength: ITEM_TITLE_MAX_LEN } }}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                submit()
              }
            }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>取消</Button>
        <Button variant="contained" disabled={submitting} onClick={submit}>
          建立
        </Button>
      </DialogActions>
    </Dialog>
  )
}
