import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import FormHelperText from "@mui/material/FormHelperText"
import IconButton from "@mui/material/IconButton"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"

import { audienceKey } from "./schemas"
import type { AudienceDraft, AudiencePair, TagOption } from "./schemas"

interface Props {
  /** `/et/tags` 的選項：啟用中，加上本課程既有配對中的停用標籤。 */
  options: TagOption[]
  value: AudienceDraft[]
  /**
   * 不可移除、不可修改的列（已發布課程的既有配對，FR-ET-US3-02）。以 `audienceKey` 比對。
   *
   * 用**值**判定而非列索引：教師新增 / 刪除其他列時索引會位移，鎖定若跟著索引走，就會
   * 鎖到錯的那一列。
   */
  lockedKeys: Set<string>
  /** 唯讀（非擁有者）：以 chip 呈現，不顯示下拉。 */
  readOnly: boolean
  /** 唯讀模式顯示用——後端組好的顯示文字。 */
  readOnlyPairs: AudiencePair[]
  rowErrors: Record<number, string>
  /** 整區的錯誤（例如發布時一組都沒有）。 */
  error?: string
  onChange: (next: AudienceDraft[]) => void
}

/**
 * 受訓對象配對列表（#538，ET05）。一列＝一組「單位 + 職位」。
 *
 * 兩欄必須成對設定：掛 [(軍醫局, 護理師), (三總, 行政人員)] 意為「僅此兩種人」；拆成兩個
 * 獨立多選會連「軍醫局的行政人員」也一併帶入（#437 否決該設計的理由，ET 同樣適用）。
 *
 * ⚠️ 不與 DM03 的配對列表共用元件：DM 的那份綁著送審流程與可見對象的錯誤 key，抽共用會動到
 * 已驗收的 DM 畫面（#538 規劃 §6）。版面與互動刻意比照它。
 */
export function CourseAudiencePairs({
  options,
  value,
  lockedKeys,
  readOnly,
  readOnlyPairs,
  rowErrors,
  error,
  onChange,
}: Props) {
  if (readOnly) {
    return (
      <Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          受訓對象
        </Typography>
        {readOnlyPairs.length === 0 ? (
          <Typography variant="body2">—</Typography>
        ) : (
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            {readOnlyPairs.map((p) => (
              <Chip key={audienceKey(p)} size="small" variant="outlined" label={p.label} />
            ))}
          </Stack>
        )}
      </Box>
    )
  }

  // 停用的標籤不可**新選**，但既有列已選的要能顯示出名字——故選項只濾掉「停用且非本列現值」者
  const choices = (type: TagOption["tag_type"], current: number | null) =>
    options.filter((o) => o.tag_type === type && (o.is_active || o.tag_id === current))
  const optionOf = (id: number | null) => options.find((o) => o.tag_id === id) ?? null
  const nameOf = (o: TagOption) => (o.is_active ? o.tag_name : `${o.tag_name}（已停用）`)

  const update = (idx: number, patch: Partial<AudienceDraft>) =>
    onChange(value.map((row, i) => (i === idx ? { ...row, ...patch } : row)))

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        受訓對象
      </Typography>
      <Stack spacing={1}>
        {value.map((row, idx) => {
          const locked = lockedKeys.has(audienceKey(row))
          return (
            <Stack
              // 完全受控（值皆來自 state），用索引不會有狀態殘留；把值寫進 key 會讓「選完單位」
              // 當下整列卸載重建（比照 DM03 的同一段）
              key={idx}
              direction="row"
              spacing={1}
              alignItems="flex-start"
            >
              {(["UNIT", "AUDIENCE"] as const).map((type) => {
                const field = type === "UNIT" ? "unit_tag_id" : "tag_id"
                const label = type === "UNIT" ? "單位" : "職位"
                return (
                  <Autocomplete
                    key={type}
                    size="small"
                    sx={{ flex: 1 }}
                    disabled={locked}
                    options={choices(type, row[field])}
                    value={optionOf(row[field])}
                    onChange={(_, v: TagOption | null) => update(idx, { [field]: v?.tag_id ?? null })}
                    getOptionLabel={nameOf}
                    isOptionEqualToValue={(a, b) => a.tag_id === b.tag_id}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label={label}
                        required
                        error={Boolean(rowErrors[idx]) && row[field] === null}
                        inputProps={{ ...params.inputProps, "aria-label": `第 ${idx + 1} 組的${label}` }}
                      />
                    )}
                  />
                )
              })}
              {/* 已發布課程的既有列不可移除（後端另以 ET_COURSE_003 把關）——不顯示刪除鈕，
                  而非顯示了再擋：點了才被拒絕，教師會以為是系統錯誤 */}
              {!locked && (
                <IconButton
                  size="small"
                  aria-label={`移除第 ${idx + 1} 組受訓對象`}
                  onClick={() => onChange(value.filter((_, i) => i !== idx))}
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              )}
              {rowErrors[idx] && (
                <FormHelperText error sx={{ alignSelf: "center", whiteSpace: "nowrap" }}>
                  {rowErrors[idx]}
                </FormHelperText>
              )}
            </Stack>
          )
        })}
      </Stack>
      <Button
        size="small"
        startIcon={<AddIcon />}
        onClick={() => onChange([...value, { unit_tag_id: null, tag_id: null }])}
        sx={{ mt: 1 }}
      >
        新增受訓對象
      </Button>
      <FormHelperText error={Boolean(error)}>
        {error ||
          (lockedKeys.size > 0
            ? "已發布課程可新增受訓對象、不可移除既有者"
            : "每組為「單位 + 職位」；「全單位」＝不限單位、「全體」＝不限職位。發布時至少 1 組")}
      </FormHelperText>
    </Box>
  )
}
