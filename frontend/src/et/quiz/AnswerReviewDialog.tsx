import type { SvgIconComponent } from "@mui/icons-material"
import CancelIcon from "@mui/icons-material/Cancel"
import CheckCircleIcon from "@mui/icons-material/CheckCircle"
import CloseIcon from "@mui/icons-material/Close"
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked"
import WarningAmberIcon from "@mui/icons-material/WarningAmber"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import type { OptionResult, QuestionResult } from "./attemptSchemas"

/**
 * 選項的四種狀態。
 *
 * 「你的答案 A, B, C ／ 正確答案 A, B, C, E」這種兩串文字要讀者自己做集合減法才知道
 * 差在哪；逐項標示則一眼看得出「哪個選對了、哪個選錯了、哪個漏了」。
 */
type OptionState = "correct" | "wrong" | "missed" | "neutral"

function optionState(option: OptionResult): OptionState {
  if (option.selected && option.is_correct) return "correct"
  if (option.selected) return "wrong"
  if (option.is_correct) return "missed"
  return "neutral"
}

interface StateStyle {
  color: string
  icon: SvgIconComponent
  /** 圖例用的說明；選項列上**不重複顯示**。 */
  legend: string
}

const STATE_STYLE: Record<OptionState, StateStyle> = {
  correct: { color: "success.main", icon: CheckCircleIcon, legend: "答對" },
  wrong: { color: "error.main", icon: CancelIcon, legend: "選錯" },
  missed: { color: "warning.main", icon: WarningAmberIcon, legend: "漏選" },
  neutral: { color: "text.disabled", icon: RadioButtonUncheckedIcon, legend: "未選且非答案" },
}

/** 圖例的三種狀態；`neutral` 不入列——沒選也不是答案，本來就不需要解釋。 */
const LEGEND: OptionState[] = ["correct", "wrong", "missed"]

interface Props {
  /** `null` = 不開啟。 */
  question: QuestionResult | null
  /** 題號（0 起算），供標題顯示。 */
  index: number
  onClose: () => void
}

/**
 * 題目檢討視窗（wireframe：明細表「點任一列檢視題目與選項，複習檢討」）。
 *
 * ## 為何是彈出視窗而不是列內展開
 *
 * 題幹上限 500 字、選項至多 6 個——展開在表格內會把整列撐到佔滿畫面，而且相鄰題目的
 * 對照關係全被推開。獨立視窗給得起完整篇幅。表格因此**不顯示題幹**。
 *
 * ## 對錯只靠左側色條與 icon
 *
 * 初版每個選項都是飽和色塊加一枚「你的答案 ✗ 錯誤」標籤。六個選項就是六塊飽和色加六
 * 段重複文字——顏色本來要當重點提示，結果整面都是重點，等於沒有重點。現在顏色退成 3px
 * 色條，文字回到主角位置；狀態的文字說明集中在上方圖例講一次。
 */
export function AnswerReviewDialog({ question, index, onClose }: Props) {
  return (
    <Dialog open={question !== null} onClose={onClose} fullWidth maxWidth="sm">
      {question !== null && (
        <>
          <DialogTitle sx={{ pr: 6 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <span>題目檢討 — Q{index + 1}</span>
              <Chip
                size="small"
                color={question.question_type === "MULTIPLE" ? "info" : "default"}
                label={question.question_type === "MULTIPLE" ? "多選題" : "單選題"}
              />
              {/* 得分移到標題列——它是這一題的結論，不該埋在選項底下 */}
              <Typography variant="body2" color="text.secondary" sx={{ ml: "auto" }}>
                本題得分 {question.score} / {question.points}
              </Typography>
            </Stack>
            <IconButton
              aria-label="關閉"
              onClick={onClose}
              sx={{ position: "absolute", right: 8, top: 8 }}
              size="small"
            >
              <CloseIcon />
            </IconButton>
          </DialogTitle>

          <DialogContent dividers>
            <Stack spacing={2}>
              <Typography variant="body1">{question.stem}</Typography>

              {/* 沒有文字標籤就一定要有圖例——icon 的語意不是自明的（⚠ 是「漏選」不是「警告」）*/}
              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                {LEGEND.map((state) => {
                  const Icon = STATE_STYLE[state].icon
                  return (
                    <Stack key={state} direction="row" spacing={0.5} alignItems="center">
                      <Icon fontSize="small" sx={{ color: STATE_STYLE[state].color }} />
                      <Typography variant="caption" color="text.secondary">
                        {STATE_STYLE[state].legend}
                      </Typography>
                    </Stack>
                  )
                })}
              </Stack>

              <Stack spacing={1}>
                {question.options.map((option) => {
                  const state = optionState(option)
                  const style = STATE_STYLE[state]
                  const Icon = style.icon
                  return (
                    <Stack
                      key={option.option_id}
                      direction="row"
                      spacing={1.5}
                      alignItems="center"
                      sx={{
                        py: 1.25,
                        pl: 1.5,
                        borderLeft: 3,
                        borderColor: style.color,
                        borderRadius: 0.5,
                        bgcolor: "action.hover",
                      }}
                    >
                      {/*
                        icon 與色條承載同一個狀態。色條單獨存在對色覺障礙者不可靠，
                        而 icon 的形狀（✓ / ✗ / ⚠ / ○）不依賴顏色也分得出來。

                        ⚠️ **必須用 `titleAccess` 而不是 `aria-label`**：MUI 的 `SvgIcon` 對
                        沒給 `titleAccess` 的圖示一律加 `aria-hidden="true"`，而使用者傳入的
                        `aria-label` 只會落進其後的 spread、蓋不掉它。兩者並存時整個節點被
                        移出可及性樹——螢幕報讀使用者讀不到任何狀態，畫面上卻完全正常。
                      */}
                      <Icon fontSize="small" sx={{ color: style.color }} titleAccess={style.legend} />
                      <Typography variant="body2">{option.text}</Typography>
                    </Stack>
                  )
                })}
              </Stack>
            </Stack>
          </DialogContent>

          <DialogActions>
            <Button variant="contained" size="small" onClick={onClose}>
              關閉
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  )
}
