import LockIcon from "@mui/icons-material/Lock"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Tooltip from "@mui/material/Tooltip"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { useNotification } from "../../contexts/NotificationContext"
import { getFieldErrors } from "../../utils/zodUtils"
import { ControlledCodeSchema, ControlledNameSchema } from "./schemas"
import type { ControlledSection } from "./paramsService"

/**
 * 受控清單維護面板（#182）。
 *
 * **未複用 `ParamEditPanel` 的 `ListEdit`**：後者綁 `DP_PARAM` 的形狀（`param_key` / `description`
 * 與 master 層 `detail_lock`），而受控項是 `code` / `name`、鎖定語意在**項目層**（`is_builtin`），
 * 且停用需先確認並回報受影響數。把兩者併成通用元件需要 6 個以上的取值 / 判定 prop，
 * 為兩個呼叫端引入的間接成本高於重複的 MUI 標記。
 */
interface ControlledEditPanelProps {
  section: ControlledSection
  onAdd: (section: ControlledSection, name: string, code?: string) => Promise<void>
  onRename: (section: ControlledSection, code: string, name: string) => Promise<void>
  onToggle: (section: ControlledSection, code: string, enabled: boolean) => void | Promise<void>
  onClose: () => void
}

export function ControlledEditPanel({ section, onAdd, onRename, onToggle, onClose }: ControlledEditPanelProps) {
  const { message } = useNotification()
  const [edited, setEdited] = useState<Record<string, string>>({})
  const [newName, setNewName] = useState("")
  const [newCode, setNewCode] = useState("")
  const [addErrors, setAddErrors] = useState<{ code?: string; name?: string }>({})

  const title = section.group_name ? `${section.name}／${section.group_name}` : section.name
  const nameOf = (code: string, fallback: string) => edited[code] ?? fallback

  /** 還原該筆的未儲存輸入（沿用 ParamEditPanel 的 dropKey 寫法）。 */
  const dropKey = (code: string) => (prev: Record<string, string>) => {
    const next = { ...prev }
    delete next[code]
    return next
  }

  const handleRename = (code: string, value: string) => {
    const parsed = ControlledNameSchema.safeParse(value)
    if (!parsed.success) {
      message.error(getFieldErrors(parsed.error)._form)
      setEdited(dropKey(code))
      return
    }
    void onRename(section, code, parsed.data).catch(() => {})
  }

  const handleAdd = () => {
    const parsedName = ControlledNameSchema.safeParse(newName)
    // 僅 requires_code 之分區需要代碼；其餘由模組配號或以所屬分組帶入
    const parsedCode = section.requires_code ? ControlledCodeSchema.safeParse(newCode) : null
    const errors = {
      name: parsedName.success ? undefined : getFieldErrors(parsedName.error)._form,
      code: !parsedCode || parsedCode.success ? undefined : getFieldErrors(parsedCode.error)._form,
    }
    setAddErrors(errors)
    if (!parsedName.success || (parsedCode && !parsedCode.success)) return

    void onAdd(section, parsedName.data, parsedCode?.success ? parsedCode.data : undefined)
      .then(() => {
        setNewName("")
        setNewCode("")
      })
      .catch(() => {})
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mt: 2, maxWidth: 600, border: 2, borderColor: "primary.main" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Typography variant="h6">{title}</Typography>
        <Chip size="small" label={section.module} />
      </Stack>

      <Stack divider={<Divider flexItem />} spacing={1.5}>
        {section.items.map((item) => (
          <Stack key={item.code} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 96 }}>
              <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                {item.code}
              </Typography>
              {item.is_builtin && (
                <Tooltip title="內建項：代碼建立後鎖定，僅可修改名稱">
                  <LockIcon fontSize="inherit" color="disabled" titleAccess="代碼唯讀" />
                </Tooltip>
              )}
            </Stack>
            <TextField
              size="small"
              label={`${item.code} 名稱`}
              value={nameOf(item.code, item.name)}
              onChange={(e) => setEdited((prev) => ({ ...prev, [item.code]: e.target.value }))}
              sx={{ flexGrow: 1 }}
            />
            <Button size="small" variant="outlined" onClick={() => handleRename(item.code, nameOf(item.code, item.name))}>
              儲存
            </Button>
            {item.is_enabled ? (
              <Button size="small" color="warning" onClick={() => onToggle(section, item.code, false)}>
                停用
              </Button>
            ) : (
              <>
                <Chip size="small" label="已停用" />
                <Button size="small" color="success" onClick={() => onToggle(section, item.code, true)}>
                  啟用
                </Button>
              </>
            )}
          </Stack>
        ))}
      </Stack>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
        淘汰請改為停用（不提供刪除）；停用後既有引用保留，僅擋後續新增。
      </Typography>

      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        alignItems={{ sm: "flex-start" }}
        flexWrap="wrap"
        useFlexGap
        sx={{ mt: 2 }}
      >
        {section.requires_code && (
          <TextField
            size="small"
            label="新增代碼"
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
            error={Boolean(addErrors.code)}
            helperText={addErrors.code}
          />
        )}
        <TextField
          size="small"
          label="新增名稱"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          error={Boolean(addErrors.name)}
          helperText={addErrors.name}
        />
        <Button size="small" variant="contained" onClick={handleAdd}>
          新增
        </Button>
      </Stack>

      <Stack direction="row" justifyContent="flex-end" sx={{ mt: 3 }}>
        <Button onClick={onClose}>關閉</Button>
      </Stack>
    </Paper>
  )
}
