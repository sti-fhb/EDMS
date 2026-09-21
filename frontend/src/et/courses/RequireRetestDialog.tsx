import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"

interface Props {
  open: boolean
  /** 該測驗曾及格的學員人數；對話框只在 > 0 時由呼叫端開啟。 */
  passedCount: number
  /** 關閉而不儲存（含 ESC 與點背景）。 */
  onCancel: () => void
  /** `true` = 要求已通過的學員重新測驗；`false` = 僅儲存。 */
  onDecide: (requireRetest: boolean) => void
}

/**
 * 測驗內容變更時，詢問是否要求已通過的學員重新測驗（#361，SA 裁示方案 C）。
 *
 * ## 為何不用共用的 `confirm`
 *
 * 這是**三選一**（取消／僅儲存／儲存並要求重測），而共用 `confirm` 只有兩顆鈕，
 * 且 `<Dialog onClose={handleCancel}>` 讓 **ESC 與點背景都會觸發 `onCancel`**。
 *
 * 🔴 若把「取消」對應到「不要求但仍儲存」，一個誤按 ESC 就會靜默儲存——而本功能的
 * 裁示重點正是**系統不猜意圖、要教師有意識地選**。故關閉一律等同取消，什麼都不做。
 *
 * ⛔ 也不為此擴充共用 `confirm` 加第三顆鈕：那是為單一呼叫端改動共用基礎設施。
 *
 * ## 為何要寫出人數
 *
 * 沒有人數，教師無從判斷這個決定的份量——「要求 1 個人重考」與「要求 80 個人重考」
 * 是完全不同的決定，而畫面上看不出差別。
 */
export function RequireRetestDialog({ open, passedCount, onCancel, onDecide }: Props) {
  return (
    <Dialog open={open} onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>是否要求已通過的學員重新測驗？</DialogTitle>
      <DialogContent>
        <DialogContentText component="div">
          本測驗目前有 <strong>{passedCount}</strong> 位學員已通過。
          <br />
          <br />
          選「要求重測」：這 {passedCount} 位學員的作答次數將重新計算、測驗回到未完成，
          完課狀態隨之回退，並各收到一封通知信。
          <br />
          <br />
          ⚠️ 兩種選擇都<strong>不會刪除任何作答紀錄</strong>，學員與您都仍可回看歷次明細。
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>
          取消
        </Button>
        <Button onClick={() => onDecide(false)}>
          僅儲存，不要求重測
        </Button>
        <Button variant="contained" onClick={() => onDecide(true)}>
          儲存並要求重測
        </Button>
      </DialogActions>
    </Dialog>
  )
}
