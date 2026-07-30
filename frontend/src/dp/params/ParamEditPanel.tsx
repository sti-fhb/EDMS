import LockIcon from "@mui/icons-material/Lock"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { FormCard } from "../../components/FormCard"
import { useNotification } from "../../contexts/NotificationContext"
import { getFieldErrors } from "../../utils/zodUtils"
import { ParamItemCreateSchema, ParamValueSchema } from "./schemas"
import type { DetailCreatePayload, DetailUpdatePayload, ParamDetail, ParamMaster } from "./paramsService"

/** 列表的一「列」：VALUE 型每個明細各一列；LIST 型整個主檔一列（展開管理項目）。 */
export type ParamRow =
  | { rowKey: string; kind: "value"; master: ParamMaster; detail: ParamDetail }
  | { rowKey: string; kind: "list"; master: ParamMaster }

interface ParamEditPanelProps {
  row: ParamRow
  onSaveDetail: (
    master: ParamMaster,
    paramKey: string,
    payload: DetailUpdatePayload,
    onCancel?: () => void,
  ) => void | Promise<void>
  onToggle: (master: ParamMaster, paramKey: string, isEnabled: boolean) => void | Promise<void>
  onAdd: (master: ParamMaster, payload: DetailCreatePayload) => Promise<void>
  onClose: () => void
}

/** 「編輯」展開的編輯面板：VALUE 型改單一值（FormCard）；LIST 型管理項目（改名 / 啟停 / 新增）。 */
export function ParamEditPanel(props: ParamEditPanelProps) {
  return props.row.kind === "value" ? <ValueEdit {...props} /> : <ListEdit {...props} />
}

/** VALUE 型：單一值編輯，套 FormCard（平台級由 onSaveDetail 內部跳影響全平台確認）。 */
function ValueEdit({ row, onSaveDetail, onClose }: ParamEditPanelProps) {
  const { message } = useNotification()
  if (row.kind !== "value") return null
  const { master, detail } = row
  return <ValueEditBody master={master} detail={detail} onSaveDetail={onSaveDetail} onClose={onClose} message={message} />
}

function ValueEditBody({
  master,
  detail,
  onSaveDetail,
  onClose,
  message,
}: {
  master: ParamMaster
  detail: ParamDetail
  onSaveDetail: ParamEditPanelProps["onSaveDetail"]
  onClose: () => void
  message: ReturnType<typeof useNotification>["message"]
}) {
  const original = detail.param_value ?? ""
  const [value, setValue] = useState(original)

  const handleSave = () => {
    if (!ParamValueSchema.safeParse(value).success) {
      message.error("請輸入內容")
      setValue(original) // 空值不留白，還原原值
      return
    }
    // 平台級：onSaveDetail 內部跳確認，取消時 onCancel 還原欄位。儲存後面板保留（不自動關）。
    void Promise.resolve(
      onSaveDetail(master, detail.param_key, { param_value: value.trim() }, () => setValue(original)),
    ).catch(() => {})
  }

  return (
    <FormCard title={detail.param_name} onSave={handleSave} onCancel={onClose} cancelLabel="關閉">
      <TextField
        autoFocus
        fullWidth
        label={detail.param_name}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    </FormCard>
  )
}

/** LIST 型：管理清單項（改名 / 啟停 / 新增）。綠框面板，右下「關閉」。 */
function ListEdit({ row, onSaveDetail, onToggle, onAdd, onClose }: ParamEditPanelProps) {
  const { message } = useNotification()
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState("")
  const [newName, setNewName] = useState("")
  const [addErrors, setAddErrors] = useState<{ param_key?: string; param_name?: string }>({})
  if (row.kind !== "list") return null
  const { master } = row

  const editedOf = (key: string, original: string | null) => edits[key] ?? original ?? ""
  const setEdit = (key: string, v: string) => setEdits((prev) => ({ ...prev, [key]: v }))
  const revertEdit = (key: string) =>
    setEdits((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })

  const handleSaveItem = (paramKey: string, edited: string) => {
    if (!ParamValueSchema.safeParse(edited).success) {
      message.error("請輸入內容")
      revertEdit(paramKey)
      return
    }
    void Promise.resolve(
      onSaveDetail(master, paramKey, { param_name: edited.trim() }, () => revertEdit(paramKey)),
    ).catch(() => {})
  }

  const handleAdd = () => {
    const result = ParamItemCreateSchema.safeParse({ param_key: newKey, param_name: newName })
    if (!result.success) {
      const f = getFieldErrors(result.error)
      setAddErrors({ param_key: f.param_key, param_name: f.param_name })
      return
    }
    setAddErrors({})
    void onAdd(master, result.data)
      .then(() => {
        setNewKey("")
        setNewName("")
      })
      .catch(() => {})
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mt: 2, maxWidth: 600, border: 2, borderColor: "primary.main" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Typography variant="h6">{master.param_name}</Typography>
        {master.detail_lock && <Chip size="small" icon={<LockIcon />} label="代碼鎖定" />}
      </Stack>

      <Stack spacing={1.5}>
        {master.details.map((d) => (
          <Stack key={d.param_key} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 140 }}>
              <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                {d.param_key}
              </Typography>
              {master.detail_lock && <LockIcon fontSize="inherit" color="disabled" titleAccess="碼值唯讀" />}
            </Stack>
            <TextField
              size="small"
              label={`${d.param_key} 名稱`}
              value={editedOf(d.param_key, d.param_name)}
              onChange={(e) => setEdit(d.param_key, e.target.value)}
              sx={{ minWidth: 240 }}
            />
            <Button size="small" variant="outlined" onClick={() => handleSaveItem(d.param_key, editedOf(d.param_key, d.param_name))}>
              儲存
            </Button>
            {d.is_enabled ? (
              <Button size="small" color="warning" onClick={() => onToggle(master, d.param_key, false)}>
                停用
              </Button>
            ) : (
              <>
                <Chip size="small" label="已停用" />
                <Button size="small" color="success" onClick={() => onToggle(master, d.param_key, true)}>
                  啟用
                </Button>
              </>
            )}
          </Stack>
        ))}
      </Stack>

      {!master.detail_lock && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "flex-start" }} sx={{ mt: 2 }}>
          <TextField
            size="small"
            label="新增代碼"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            error={Boolean(addErrors.param_key)}
            helperText={addErrors.param_key}
          />
          <TextField
            size="small"
            label="新增名稱"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            error={Boolean(addErrors.param_name)}
            helperText={addErrors.param_name}
          />
          <Button size="small" variant="contained" onClick={handleAdd}>
            新增
          </Button>
        </Stack>
      )}

      <Stack direction="row" justifyContent="flex-end" sx={{ mt: 3 }}>
        <Button onClick={onClose}>關閉</Button>
      </Stack>
    </Paper>
  )
}
