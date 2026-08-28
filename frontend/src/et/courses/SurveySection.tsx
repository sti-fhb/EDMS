import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import EditOutlinedIcon from "@mui/icons-material/EditOutlined"
import LockIcon from "@mui/icons-material/Lock"
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { SURVEY_NAME_MAX_LEN, SurveyNameSchema } from "./surveySchemas"
import type { SurveyDetail } from "./surveySchemas"

interface SurveySectionProps {
  /** `null` = 尚未建立問卷（正常狀態，非錯誤）；`undefined` = 尚在載入。 */
  survey: SurveyDetail | null | undefined
  readOnly: boolean
  /** 新增模式（課程尚未建立於後端）時停用——問卷須掛在已存在的課程下。 */
  disabled?: boolean
  /** 課程是否為草稿——決定「刪除問卷」入口是否出現（#238）。 */
  isDraftCourse: boolean
  saving?: boolean
  error?: string | null
  onCreate: (surveyName: string) => void
  onOpen: () => void
  onDeactivate: () => void
  onDelete: () => void
}

/**
 * ET02 課後問卷**摘要卡**（US3 / #238）。
 *
 * 題目管理已於 #238 移入 `SurveyDialog`（比照教材 / 測驗的視窗形狀），本元件只負責：
 * 建立、開啟視窗、停用、刪除，以及顯示摘要（題數、填答狀況、凍結標示）。
 *
 * ## 刪除 vs 停用（#238 推翻 #204 之裁示 Q1）
 *
 * | 課程狀態 | 可用動作 |
 * |---------|---------|
 * | 草稿 | 編輯、停用、**刪除**（垃圾桶）|
 * | 已發布 / 已關閉 | 編輯、停用——**不顯示刪除** |
 *
 * 前端隱藏僅為 UX，後端另以 `ET_SURVEY_007` 把關。
 *
 * ## 凍結（沿用 #204）
 *
 * 有學員填答後題目與選項凍結，但**停用仍可用**——AC 21 明訂此時教師僅可停用問卷，
 * 把停用也鎖掉等於整張卡片變成死的。
 */
export function SurveySection({
  survey,
  readOnly,
  disabled = false,
  isDraftCourse,
  saving = false,
  error = null,
  onCreate,
  onOpen,
  onDeactivate,
  onDelete,
}: SurveySectionProps) {
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [nameError, setNameError] = useState("")

  const header = (
    <Typography variant="subtitle2" fontWeight={700}>
      課後問卷{" "}
      <Typography component="span" variant="caption" color="text.secondary" fontWeight={400}>
        （選配；一門課程 0～1 份）
      </Typography>
    </Typography>
  )

  // ── 尚未建立 ────────────────────────────────────────────────────────────
  if (survey === null || survey === undefined) {
    const creating = nameDraft !== null
    return (
      <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          {header}
          {!readOnly && !creating && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              disabled={disabled || survey === undefined}
              onClick={() => {
                setNameError("")
                // 空字串而非預設名稱——#203 實測回饋：不要幫使用者填預設值
                setNameDraft("")
              }}
            >
              新增問卷
            </Button>
          )}
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          學員完課後開放填寫（具名、一人一次）。填寫問卷不是完課條件、不計入學習進度。
        </Typography>

        {creating ? (
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField
              autoFocus
              size="small"
              label="問卷名稱"
              required
              fullWidth
              value={nameDraft}
              error={Boolean(nameError)}
              helperText={nameError}
              slotProps={{ htmlInput: { maxLength: SURVEY_NAME_MAX_LEN } }}
              onChange={(e) => setNameDraft(e.target.value)}
            />
            <Button size="small" onClick={() => setNameDraft(null)}>
              取消
            </Button>
            <Button
              size="small"
              variant="contained"
              disabled={saving}
              onClick={() => {
                const parsed = SurveyNameSchema.safeParse(nameDraft ?? "")
                if (!parsed.success) {
                  setNameError(parsed.error.issues[0]?.message ?? "問卷名稱不正確")
                  return
                }
                setNameError("")
                setNameDraft(null)
                onCreate(parsed.data)
              }}
            >
              建立
            </Button>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.disabled" sx={{ display: "block", py: 1 }}>
            {disabled ? "請先儲存草稿後再新增問卷" : "尚未建立課後問卷"}
          </Typography>
        )}
      </Paper>
    )
  }

  // ── 已建立（摘要卡）──────────────────────────────────────────────────────
  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        {header}
        <Stack direction="row" spacing={1} alignItems="center">
          {!survey.is_active && <Chip size="small" label="已停用" />}
          {survey.frozen && <Chip size="small" color="warning" icon={<LockIcon />} label="已凍結" />}
          <Button size="small" variant="outlined" startIcon={<EditOutlinedIcon />} onClick={onOpen}>
            {readOnly ? "檢視" : "編輯"}
          </Button>
          {/* 停用**不受凍結限制**——AC 21 明訂凍結後教師僅可停用問卷 */}
          {!readOnly && survey.is_active && (
            <Button
              size="small"
              color="warning"
              variant="outlined"
              startIcon={<PauseCircleOutlineIcon />}
              disabled={saving}
              onClick={onDeactivate}
            >
              停用問卷
            </Button>
          )}
          {/* 刪除僅草稿課程；後端另以 ET_SURVEY_007 把關（#238）*/}
          {!readOnly && isDraftCourse && (
            <IconButton size="small" color="error" aria-label="刪除問卷" disabled={saving} onClick={onDelete}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          )}
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      <Stack direction="row" spacing={2} alignItems="baseline" flexWrap="wrap" useFlexGap>
        <Typography variant="body2">{survey.survey_name}</Typography>
        <Typography variant="caption" color="text.secondary">
          {survey.questions.length} 題
        </Typography>
        <Typography variant="caption" color="text.secondary">
          填答狀況：已填 {survey.responded_count} / 未填 {survey.pending_count}
        </Typography>
      </Stack>

      {survey.questions.length === 0 && (
        // 0 題的問卷會擋住課程發布（#204 之第七項檢核），在這裡先講比讓他按發布才發現好
        <Typography variant="caption" color="warning.main" sx={{ display: "block", mt: 1 }}>
          尚無題目——問卷至少須有 1 題才能發布課程
        </Typography>
      )}
    </Paper>
  )
}
