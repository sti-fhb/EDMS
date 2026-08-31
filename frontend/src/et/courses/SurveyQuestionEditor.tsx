import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import IconButton from "@mui/material/IconButton"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import {
  SURVEY_ANSWER_MAX_LEN,
  SURVEY_MIN_OPTIONS,
  SURVEY_OPTION_TEXT_MAX_LEN,
  SURVEY_QUESTION_TYPE_LABEL,
  SURVEY_STEM_MAX_LEN,
  SurveyQuestionFormSchema,
} from "./surveySchemas"
import type { SurveyQuestionDraft, SurveyQuestionFormValues, SurveyQuestionType } from "./surveySchemas"

interface SurveyQuestionEditorProps {
  initial: SurveyQuestionDraft
  saving?: boolean
  onSave: (values: SurveyQuestionFormValues) => void
  onCancel: () => void
}

/**
 * 單一問卷題目之行內編輯器（新增與編輯共用）。
 *
 * ## 兩種題型（#238）
 *
 * | 題型 | 教師填什麼 | 學員怎麼答 |
 * |------|-----------|-----------|
 * | 單選 | 題幹 + 至少 2 個選項 | 選一個 |
 * | 問答 | **只填題幹** | 文字，至多 150 字 |
 *
 * ## 切換題型時選項的處理
 *
 * 切到問答會**真的清空選項**，切回單選補回兩個空欄。後端對「問答題帶選項」是明確
 * 擋下（`ET_SURVEY_008`）而非靜默忽略——所以前端必須真的清掉，不能只把選項區藏起來。
 * 藏起來但仍送出，教師會拿到一個他看不懂的錯誤。
 *
 * ## 與測驗題目編輯器（`QuestionEditor`）的差異
 *
 * 測驗有正確答案（radio / checkbox 標記）與配分，問卷都沒有——問卷是收集意見，
 * 沒有對錯也不計分。選項數上限也不同：測驗 2–6，問卷單選只有下限 2、無上限。
 */
export function SurveyQuestionEditor({ initial, saving = false, onSave, onCancel }: SurveyQuestionEditorProps) {
  const [draft, setDraft] = useState<SurveyQuestionDraft>(initial)
  const [error, setError] = useState<string | null>(null)

  const patch = (next: Partial<SurveyQuestionDraft>) => setDraft((prev) => ({ ...prev, ...next }))
  const isText = draft.question_type === "TEXT"

  const changeType = (question_type: SurveyQuestionType) => {
    // 真的清空 / 補回，而不只是切換顯示——後端會擋下「問答題帶選項」，
    // 藏起來但仍送出只會讓教師拿到看不懂的錯誤
    patch({
      question_type,
      options: question_type === "TEXT" ? [] : [{ option_text: "" }, { option_text: "" }],
    })
  }

  const setOptionText = (index: number, option_text: string) => {
    patch({ options: draft.options.map((o, i) => (i === index ? { option_text } : o)) })
  }

  const submit = () => {
    const parsed = SurveyQuestionFormSchema.safeParse(draft)
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "題目內容不完整")
      return
    }
    setError(null)
    onSave(parsed.data)
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
          <TextField
            select
            size="small"
            label="題型"
            value={draft.question_type}
            sx={{ minWidth: 110 }}
            onChange={(e) => changeType(e.target.value as SurveyQuestionType)}
          >
            {(Object.keys(SURVEY_QUESTION_TYPE_LABEL) as SurveyQuestionType[]).map((type) => (
              <MenuItem key={type} value={type}>
                {SURVEY_QUESTION_TYPE_LABEL[type]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            size="small"
            label="題幹"
            required
            fullWidth
            multiline
            maxRows={3}
            value={draft.stem}
            slotProps={{ htmlInput: { maxLength: SURVEY_STEM_MAX_LEN } }}
            onChange={(e) => patch({ stem: e.target.value })}
          />
        </Stack>

        {isText ? (
          <Typography variant="caption" color="text.secondary">
            問答題無選項——學員以文字作答，至多 {SURVEY_ANSWER_MAX_LEN} 字。
          </Typography>
        ) : (
          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary" fontWeight={600}>
                選項（單選；至少 {SURVEY_MIN_OPTIONS} 個）
              </Typography>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() => patch({ options: [...draft.options, { option_text: "" }] })}
              >
                新增選項
              </Button>
            </Stack>
            <Stack spacing={1}>
              {draft.options.map((option, index) => (
                // 以索引當 key：選項尚未落地故無穩定 id，且此清單**不支援拖拉重排**——
                // 索引不會在重排後錯位。對照 #202 章節拖拉之教訓：那裡出事是因為清單會重排。
                <Stack key={index} direction="row" alignItems="center" spacing={1}>
                  <TextField
                    size="small"
                    fullWidth
                    placeholder={`選項 ${index + 1}`}
                    value={option.option_text}
                    slotProps={{
                      htmlInput: { maxLength: SURVEY_OPTION_TEXT_MAX_LEN, "aria-label": `選項 ${index + 1} 文字` },
                    }}
                    onChange={(e) => setOptionText(index, e.target.value)}
                  />
                  <IconButton
                    size="small"
                    color="error"
                    aria-label={`刪除選項 ${index + 1}`}
                    // 刪到剩下限就停用——讓使用者刪光再被儲存擋下，等於白做一次
                    disabled={draft.options.length <= SURVEY_MIN_OPTIONS}
                    onClick={() => patch({ options: draft.options.filter((_, i) => i !== index) })}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
            </Stack>
          </Box>
        )}

        <Stack direction="row" justifyContent="flex-end" spacing={1}>
          <Button size="small" onClick={onCancel}>
            取消
          </Button>
          <Button size="small" variant="contained" disabled={saving} onClick={submit}>
            儲存題目
          </Button>
        </Stack>
      </Stack>
    </Paper>
  )
}
