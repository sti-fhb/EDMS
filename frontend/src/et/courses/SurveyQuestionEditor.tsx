import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import {
  SURVEY_MIN_OPTIONS,
  SURVEY_OPTION_TEXT_MAX_LEN,
  SURVEY_STEM_MAX_LEN,
  SurveyQuestionFormSchema,
} from "./surveySchemas"
import type { SurveyQuestionDraft, SurveyQuestionFormValues } from "./surveySchemas"

interface SurveyQuestionEditorProps {
  initial: SurveyQuestionDraft
  saving?: boolean
  onSave: (values: SurveyQuestionFormValues) => void
  onCancel: () => void
}

/**
 * 單一問卷題目之行內編輯器（新增與編輯共用）。
 *
 * ## 與測驗題目編輯器（`QuestionEditor`）的三處差異
 *
 * | 項目 | 測驗題目 | 問卷題目 |
 * |------|---------|---------|
 * | 題型選擇 | 單選 / 多選下拉 | **無**——問卷一律單選（data-model 不設題型欄位）|
 * | 正確答案 | Radio / Checkbox 標記 | **無**——問卷收集意見，沒有對錯 |
 * | 配分 | 有 | **無**——問卷不計分、不計入學習進度 |
 *
 * 選項數也不同：測驗為 2–6，問卷只有下限 2、**無上限**，故「新增選項」不設停用條件。
 */
export function SurveyQuestionEditor({ initial, saving = false, onSave, onCancel }: SurveyQuestionEditorProps) {
  const [draft, setDraft] = useState<SurveyQuestionDraft>(initial)
  const [error, setError] = useState<string | null>(null)

  const patch = (next: Partial<SurveyQuestionDraft>) => setDraft((prev) => ({ ...prev, ...next }))

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
