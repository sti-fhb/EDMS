import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker"
import dayjs from "dayjs"
import type { Dayjs } from "dayjs"
import { useState } from "react"

import { BlockerList } from "./BlockerList"
import { validateReopenSchedule } from "./reopenSchedule"
import type { ReopenScheduleErrors } from "./reopenSchedule"
import type { PublishBlocker } from "./surveySchemas"

interface ReopenCourseDialogProps {
  open: boolean
  submitting: boolean
  /** 再開課重跑發布檢核所回的缺漏項目（422 `ET_PUBLISH_001`）；空陣列 = 沒有缺漏。 */
  blockers: PublishBlocker[]
  /** 缺漏項目所指向的測驗名稱（`quiz_id` → 名稱），由頁面自課程詳細對照後傳入。 */
  quizNames: Record<number, string>
  /** 同上，但為 `chapter_id` → 章節名稱。兩者是獨立序號，不可混用。 */
  chapterNames: Record<number, string>
  /** item_id → **所屬章節**名稱（`ITEM_NO_TITLE` 用；該項目自己沒有名稱）。 */
  itemChapterNames: Record<number, string>
  onSubmit: (openStartAt: string, openEndAt: string) => void
  onClose: () => void
}

/**
 * 再開課視窗（US11 AC 8 / FR-ET-US11-09 / #288）。
 *
 * ## 為何兩個時間都不預填
 *
 * FR-ET-US11-09 明訂「強制要求重新設定一組新的起訖時間」。預填舊值會讓教師直接按下
 * 確認、把課程再開成一段**已經過去**的期間——後端會以 `ET_COURSE_008` 擋下，但那是
 * 一次不必要的往返，而且畫面上填著兩個看似合理的值卻被拒絕，很難理解。留空迫使教師
 * 實際選一次，是這條 FR 的用意。
 *
 * ## 兩個時間的下限不同
 *
 * | 欄位 | 下限 | 理由 |
 * |---|---|---|
 * | 起始 | 無 | 「補開一段已經開始的期間」是合理操作（讓學員從上週就能看）|
 * | 訖止 | 起始與當下之較晚者 | 後端 `ensure_reopen_schedule` 只要求訖止晚於當下 |
 *
 * 起始刻意不設下限，與後端一致——`ensure_reopen_schedule` 的 docstring 說明了為何
 * 只檢核訖止。前端若擅自要求「起始 ≥ 當下」，會擋掉後端允許的合法操作。
 *
 * ## 缺漏清單
 *
 * 再開課會**重跑發布六項檢核**（SA Q2 裁示 A）：關閉期間教師端仍可編輯內容，課程可能
 * 已不符發布條件。缺漏的呈現與文案沿用 `PublishDialog` 的 `BLOCKER_HINT`，兩處是同
 * 一份檢核、同一份「去哪裡修」的導引。
 */
export function ReopenCourseDialog({
  open,
  submitting,
  blockers,
  quizNames,
  chapterNames,
  itemChapterNames,
  onSubmit,
  onClose,
}: ReopenCourseDialogProps) {
  const [startAt, setStartAt] = useState<Dayjs | null>(null)
  const [endAt, setEndAt] = useState<Dayjs | null>(null)
  const [errors, setErrors] = useState<ReopenScheduleErrors>({})

  const handleClose = () => {
    setStartAt(null)
    setEndAt(null)
    setErrors({})
    onClose()
  }

  const handleSubmit = () => {
    const next = validateReopenSchedule(startAt, endAt, dayjs())
    setErrors(next)
    if (Object.keys(next).length > 0) return
    // 送 ISO 8601（含時區）——後端欄位為 TIMESTAMPTZ，naive 值會被以連線時區解讀而
    // 靜默位移，使「期間已過視同關閉」的判定算錯。
    onSubmit(startAt!.toISOString(), endAt!.toISOString())
  }

  const blocked = blockers.length > 0

  return (
    // ⚠️ **日曆仍會超出本對話框，這是已知且刻意不在此修的**（#413 → #428）。
    //
    // #419 曾把 `maxWidth` 由 `sm` 改為 `md`，理由寫「欄位太窄裝不下選擇器的四欄」
    // ——那個診斷是**錯的**：溢出是**垂直**的。桌面版 `DateTimePicker` 的彈出層約
    // 390px 高，而本對話框只有約 250px，**彈出層比對話框本身還高**，加寬或加高都
    // 難看。實測於 GCP 確認 `md` 完全無效，已改回 `sm`。
    //
    // ⛔ 不要再嘗試在這裡修版面。2026-09-24 裁示改為**就地清空編輯頁的起訖時間並
    // 標示**、移除本對話框（#428），屆時這個問題會隨之消失。
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>再開課</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {blocked ? (
            <Stack spacing={1}>
              <Alert severity="error">
                課程目前不符發布條件，無法再開課。關閉期間的編輯可能移除了必要內容，請先補齊以下項目。
              </Alert>
              <BlockerList
                blockers={blockers}
                names={{ quiz: quizNames, chapter: chapterNames, itemChapter: itemChapterNames }}
              />
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              再開課須重新設定一組新的開放起訖時間。學員的學習進度與成績會接續保留，
              原邀請碼沿用、恢復有效。
            </Typography>
          )}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
              gap: 2,
            }}
          >
            <DateTimePicker
              label="新的開放起始時間"
              value={startAt}
              onChange={(v) => setStartAt(v)}
              slotProps={{
                textField: {
                  size: "small",
                  fullWidth: true,
                  required: true,
                  error: Boolean(errors.start),
                  helperText: errors.start,
                },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
            <DateTimePicker
              label="新的開放訖止時間"
              value={endAt}
              minDateTime={startAt && startAt.isAfter(dayjs()) ? startAt : dayjs()}
              onChange={(v) => setEndAt(v)}
              slotProps={{
                textField: {
                  size: "small",
                  fullWidth: true,
                  required: true,
                  error: Boolean(errors.end),
                  helperText: errors.end,
                },
                actionBar: { actions: ["cancel", "accept"] },
              }}
            />
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>取消</Button>
        {/*
          缺漏未補齊時仍不 disable 送出鈕——教師可能在另一個分頁把內容補好了，
          再按一次就會重跑檢核。disable 會讓他只能關掉視窗重開，而畫面上沒有任何
          提示說「補好之後要重開視窗」。
        */}
        <Button variant="contained" disabled={submitting} onClick={handleSubmit}>
          確認再開課
        </Button>
      </DialogActions>
    </Dialog>
  )
}
