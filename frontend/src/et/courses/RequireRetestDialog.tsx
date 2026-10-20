import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogContentText from "@mui/material/DialogContentText"
import DialogTitle from "@mui/material/DialogTitle"

interface Props {
  open: boolean
  /** 要求重測會影響的學員人數（作答過者，不限已通過）；對話框只在 > 0 時由呼叫端開啟。 */
  affectedCount: number
  /**
   * 這門課的編輯是否進暫存區（已發布 / 已關閉課程，#631）。
   *
   * 影響的是**生效時點**：暫存模式下重測不在按下去的當下執行，而是延到教師按「更新」
   * ——那是 2026-10-17 的裁示（學員被退回的那一刻新題目必須已經生效，否則他重考的是
   * 剛剛才通過的同一份舊題）。文案不跟著改的話，教師會以為信已經寄出去了。
   */
  staged?: boolean
  /**
   * 本次編輯工作階段是否**已有**一筆待生效的重測要求（`QuizDetail.require_retest_pending`）。
   *
   * 🔴 不顯示這件事，「僅儲存，不要求重測」就是一顆會**靜默取消**先前決定的按鈕：
   * 旗標寄在暫存節點上，而測驗設定的儲存會依本次選擇覆寫它。教師第二次只是來改個錯字，
   * 不會想到自己正在撤銷十分鐘前的決定。
   */
  retestPending?: boolean
  /**
   * 本次儲存選「僅儲存」是否會**取消**待生效的重測要求。
   *
   * 只有測驗設定那一支會（`quiz/service.py` 的 `update_settings`）；改題 / 刪題的「僅儲存」
   * 意思是「這一次不另外要求」，不碰先前的決定。兩者講同一句話，改題時那句就是假的（#767 A1）。
   */
  cancelsPending?: boolean
  /** 關閉而不儲存（含 ESC 與點背景）。 */
  onCancel: () => void
  /** `true` = 要求學員重新測驗；`false` = 僅儲存。 */
  onDecide: (requireRetest: boolean) => void
}

/**
 * 測驗內容變更時，詢問是否要求學員重新測驗（#361，SA 裁示方案 C）。
 *
 * #709 起對象為**作答過的學員，不限已通過**：要求重測的情境是舊題目有問題（出題疏失），
 * 所有人都拿到同樣的新一輪。
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
export function RequireRetestDialog({
  open,
  affectedCount,
  staged = false,
  retestPending = false,
  cancelsPending = false,
  onCancel,
  onDecide,
}: Props) {
  return (
    <Dialog open={open} onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>是否要求學員重新測驗？</DialogTitle>
      <DialogContent>
        <DialogContentText component="div">
          本測驗目前有 <strong>{affectedCount}</strong> 位學員已作答。
          <br />
          <br />
          選「要求重測」：這 {affectedCount} 位學員（不論是否已通過）的作答次數將重新計算、測驗回到未完成，
          完課狀態隨之回退，最高分只計重測後的作答，並各收到一封通知信。
          {staged && (
            <>
              <br />
              <br />
              ⚠️ 本課程已發布，編輯會先存在暫存區：重測
              <strong>不會立刻執行</strong>，而是在您按下「更新」、新內容對學員生效的那一刻才一起發生。
            </>
          )}
          {retestPending && (
            <>
              <br />
              <br />
              ℹ️ 本次編輯<strong>已有一筆待生效的重測要求</strong>。
              {cancelsPending
                ? "選「僅儲存，不要求重測」會把它一併取消。"
                : "本次選「僅儲存，不要求重測」不會取消它；要取消，請到「測驗設定」分頁存檔並選「僅儲存，不要求重測」。"}
            </>
          )}
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
