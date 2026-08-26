import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import FormControlLabel from "@mui/material/FormControlLabel"
import IconButton from "@mui/material/IconButton"
import InputAdornment from "@mui/material/InputAdornment"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Radio from "@mui/material/Radio"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { MAX_OPTIONS, OPTION_TEXT_MAX_LEN, QUESTION_TYPE_LABEL, QuestionFormSchema, STEM_MAX_LEN } from "./itemSchemas"
import type { QuestionDraft, QuestionFormValues, QuestionType } from "./itemSchemas"

interface QuestionEditorProps {
  initial: QuestionDraft
  saving?: boolean
  onSave: (values: QuestionFormValues) => void
  onCancel: () => void
}

/**
 * 單一題目之行內編輯器（新增與編輯共用）。
 *
 * ## 為何一次只編一題
 *
 * 每題各有自己的 `VERSION`（FR-ET-US3-15：不同實體並行編輯互不衝突）。若讓整份題庫
 * 同時可編、按一次儲存全部送出，就得替 N 題各自處理版本衝突——一題衝突時其餘該不該
 * 存？做成「展開一題、存一題」則每次只有一個版本要對，衝突語意單純。
 *
 * ## 單選 vs 多選的控制項
 *
 * 單選用 `Radio`（互斥）、多選用 `Checkbox`。切換題型時若原本勾了多個，會自動只留
 * 第一個——否則單選題會帶著兩個正確答案送出，被後端 `ET_QUESTION_002` 擋下，而使用者
 * 看不出是哪裡不對。
 */
export function QuestionEditor({ initial, saving = false, onSave, onCancel }: QuestionEditorProps) {
  const [draft, setDraft] = useState<QuestionDraft>(initial)
  const [error, setError] = useState<string | null>(null)

  const patch = (next: Partial<QuestionDraft>) => setDraft((prev) => ({ ...prev, ...next }))

  const changeType = (question_type: QuestionType) => {
    if (question_type === "SINGLE") {
      // 單選只能有一個正確——保留第一個已勾選者，其餘取消
      const firstCorrect = draft.options.findIndex((o) => o.is_correct)
      patch({
        question_type,
        options: draft.options.map((o, i) => ({ ...o, is_correct: i === (firstCorrect === -1 ? 0 : firstCorrect) })),
      })
      return
    }
    patch({ question_type })
  }

  const setCorrect = (index: number, checked: boolean) => {
    patch({
      options: draft.options.map((o, i) =>
        draft.question_type === "SINGLE" ? { ...o, is_correct: i === index } : i === index ? { ...o, is_correct: checked } : o,
      ),
    })
  }

  const setOptionText = (index: number, option_text: string) => {
    patch({ options: draft.options.map((o, i) => (i === index ? { ...o, option_text } : o)) })
  }

  const addOption = () => {
    if (draft.options.length >= MAX_OPTIONS) return
    patch({ options: [...draft.options, { option_text: "", is_correct: false }] })
  }

  const removeOption = (index: number) => {
    const next = draft.options.filter((_, i) => i !== index)
    // 刪掉唯一的正確選項時補回第一個——否則儲存必被擋，而使用者不會預期「刪一個選項
    // 導致整題不能存」
    if (draft.question_type === "SINGLE" && !next.some((o) => o.is_correct) && next.length > 0) {
      next[0] = { ...next[0], is_correct: true }
    }
    patch({ options: next })
  }

  const submit = () => {
    const parsed = QuestionFormSchema.safeParse(draft)
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
            onChange={(e) => changeType(e.target.value as QuestionType)}
          >
            {(Object.keys(QUESTION_TYPE_LABEL) as QuestionType[]).map((type) => (
              <MenuItem key={type} value={type}>
                {QUESTION_TYPE_LABEL[type]}
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
            slotProps={{ htmlInput: { maxLength: STEM_MAX_LEN } }}
            onChange={(e) => patch({ stem: e.target.value })}
          />
          <TextField
            size="small"
            label="配分"
            type="number"
            value={draft.points}
            // 140 而非 110：數字加上「分」的 endAdornment 在 110px 內會被截掉
            sx={{ width: 140 }}
            slotProps={{
              htmlInput: { min: 1, max: 100 },
              input: { endAdornment: <InputAdornment position="end">分</InputAdornment> },
            }}
            onChange={(e) => patch({ points: Number(e.target.value) })}
          />
        </Stack>

        <Box>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={600}>
              選項（{draft.question_type === "SINGLE" ? "點選圓鈕標記唯一正確答案" : "勾選所有正確答案"}）
            </Typography>
            <Button
              size="small"
              startIcon={<AddIcon />}
              disabled={draft.options.length >= MAX_OPTIONS}
              onClick={addOption}
            >
              新增選項
            </Button>
          </Stack>
          <Stack spacing={1}>
            {draft.options.map((option, index) => (
              // 以索引當 key：選項尚未落地故無穩定 id，且此清單**不支援拖拉重排**——
              // 索引不會在重排後錯位。對照 #202 章節拖拉之教訓：那裡出事是因為清單會重排。
              <Stack key={index} direction="row" alignItems="center" spacing={1}>
                <FormControlLabel
                  sx={{ m: 0 }}
                  control={
                    draft.question_type === "SINGLE" ? (
                      <Radio
                        size="small"
                        checked={option.is_correct}
                        inputProps={{ "aria-label": `選項 ${index + 1} 為正確答案` }}
                        onChange={() => setCorrect(index, true)}
                      />
                    ) : (
                      <Checkbox
                        size="small"
                        checked={option.is_correct}
                        inputProps={{ "aria-label": `選項 ${index + 1} 為正確答案` }}
                        onChange={(e) => setCorrect(index, e.target.checked)}
                      />
                    )
                  }
                  label=""
                />
                <TextField
                  size="small"
                  fullWidth
                  placeholder={`選項 ${index + 1}`}
                  value={option.option_text}
                  slotProps={{
                    htmlInput: { maxLength: OPTION_TEXT_MAX_LEN, "aria-label": `選項 ${index + 1} 文字` },
                  }}
                  onChange={(e) => setOptionText(index, e.target.value)}
                />
                <IconButton
                  size="small"
                  color="error"
                  aria-label={`刪除選項 ${index + 1}`}
                  onClick={() => removeOption(index)}
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
