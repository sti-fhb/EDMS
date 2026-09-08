import CancelIcon from "@mui/icons-material/Cancel"
import CheckCircleIcon from "@mui/icons-material/CheckCircle"
import CloseIcon from "@mui/icons-material/Close"
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked"
import WarningAmberIcon from "@mui/icons-material/WarningAmber"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import Typography from "@mui/material/Typography"

import type { OptionResult, QuestionResult } from "./attemptSchemas"

/**
 * 選項的四種狀態——**顏色是這個視窗的主要資訊**。
 *
 * 「你的答案 A, B, C ／ 正確答案 A, B, C, E」這種兩串文字要讀者自己做集合減法才知道
 * 差在哪；逐項上色則一眼看得出「哪個選對了、哪個選錯了、哪個漏了」。
 */
type OptionState = "correct" | "wrong" | "missed" | "neutral"

function optionState(option: OptionResult): OptionState {
  if (option.selected && option.is_correct) return "correct"
  if (option.selected) return "wrong"
  if (option.is_correct) return "missed"
  return "neutral"
}

const STATE_STYLE: Record<
  OptionState,
  { bg: string; border: string; icon: typeof CheckCircleIcon; iconColor: "success" | "error" | "warning" | "disabled"; badge?: { text: string; color: "success" | "error" | "warning" } }
> = {
  correct: {
    bg: "success.light",
    border: "success.main",
    icon: CheckCircleIcon,
    iconColor: "success",
    badge: { text: "你的答案 ✓ 正確", color: "success" },
  },
  wrong: {
    bg: "error.light",
    border: "error.main",
    icon: CancelIcon,
    iconColor: "error",
    badge: { text: "你的答案 ✗ 錯誤", color: "error" },
  },
  missed: {
    bg: "warning.light",
    border: "warning.main",
    icon: WarningAmberIcon,
    iconColor: "warning",
    badge: { text: "正確答案 ⚠ 你漏選", color: "warning" },
  },
  neutral: { bg: "transparent", border: "divider", icon: RadioButtonUncheckedIcon, iconColor: "disabled" },
}

interface Props {
  /** `null` = 不開啟。 */
  question: QuestionResult | null
  /** 題號（1 起算），供標題與導覽顯示。 */
  index: number
  total: number
  onClose: () => void
  onPrev: () => void
  onNext: () => void
}

/** 逗號分隔的選項文字；空選擇顯示「未作答」而非空白（空白看起來像壞掉）。 */
function joinOptions(options: OptionResult[], predicate: (o: OptionResult) => boolean) {
  const picked = options.filter(predicate).map((o) => o.text)
  return picked.length > 0 ? picked.join("、") : "未作答"
}

/**
 * 題目檢討視窗（wireframe：明細表「點任一列檢視題目與選項，複習檢討」）。
 *
 * ## 為何是彈出視窗而不是列內展開
 *
 * 題幹上限 500 字、選項至多 6 個——展開在表格內會把整列撐到佔滿畫面，而且相鄰題目的
 * 對照關係全被推開。獨立視窗給得起完整篇幅，也讓「上一題 / 下一題」的連續檢討成立：
 * 那是複習時真正在做的動作，而在表格裡它等於反覆展開收合。
 *
 * 表格因此**不顯示題幹**——摘要就該是摘要，題目在這裡看。
 */
export function AnswerReviewDialog({ question, index, total, onClose, onPrev, onNext }: Props) {
  return (
    <Dialog open={question !== null} onClose={onClose} fullWidth maxWidth="sm">
      {question !== null && (
        <>
          <DialogTitle sx={{ pr: 6 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <span>題目檢討 — Q{index + 1}</span>
              <Chip
                size="small"
                color={question.question_type === "MULTIPLE" ? "info" : "default"}
                label={question.question_type === "MULTIPLE" ? "多選題" : "單選題"}
              />
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
              <Paper variant="outlined" sx={{ p: 2, bgcolor: "action.hover" }}>
                <Typography variant="caption" color="text.secondary">
                  題目
                </Typography>
                <Typography variant="body1">{question.stem}</Typography>
              </Paper>

              <Box>
                <Typography variant="caption" color="text.secondary">
                  選項（依顏色判讀對錯）
                </Typography>
                <Stack spacing={1} sx={{ mt: 1 }}>
                  {question.options.map((option) => {
                    const state = optionState(option)
                    const style = STATE_STYLE[state]
                    const Icon = style.icon
                    return (
                      <Paper
                        key={option.option_id}
                        variant="outlined"
                        sx={{
                          p: 1.5,
                          bgcolor: style.bg,
                          borderColor: style.border,
                          // 純底色對色覺障礙者不可靠——icon 與右側標籤同時承載同一個資訊
                          display: "flex",
                          alignItems: "center",
                          gap: 1,
                        }}
                      >
                        <Icon fontSize="small" color={style.iconColor} />
                        <Typography variant="body2" sx={{ flexGrow: 1 }}>
                          {option.text}
                        </Typography>
                        {style.badge && <Chip size="small" color={style.badge.color} label={style.badge.text} />}
                      </Paper>
                    )
                  })}
                </Stack>
              </Box>

              <Stack
                direction="row"
                spacing={2}
                justifyContent="space-between"
                flexWrap="wrap"
                sx={{ pt: 1, borderTop: 1, borderColor: "divider" }}
              >
                <Typography variant="body2" color="text.secondary">
                  你的答案：<strong>{joinOptions(question.options, (o) => o.selected)}</strong>
                  {"　｜　"}
                  {/* AC 11：強制顯示，無教師可關閉之選項 */}
                  正確答案：<strong>{joinOptions(question.options, (o) => o.is_correct)}</strong>
                </Typography>
                <Typography variant="body2">
                  本題得分：
                  <strong>
                    {question.score} / {question.points}
                  </strong>
                </Typography>
              </Stack>
            </Stack>
          </DialogContent>

          <DialogActions>
            <Button size="small" disabled={index <= 0} onClick={onPrev}>
              ← 上一題
            </Button>
            <Button size="small" disabled={index >= total - 1} onClick={onNext}>
              下一題 →
            </Button>
            <Button variant="contained" size="small" onClick={onClose}>
              關閉
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  )
}
