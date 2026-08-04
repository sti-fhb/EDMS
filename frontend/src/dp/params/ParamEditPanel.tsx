import LockIcon from "@mui/icons-material/Lock"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Divider from "@mui/material/Divider"
import Paper from "@mui/material/Paper"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { FormCard } from "../../components/FormCard"
import { useNotification } from "../../contexts/NotificationContext"
import { getFieldErrors } from "../../utils/zodUtils"
import { ParamDescriptionSchema, ParamItemCreateSchema, ParamItemNameSchema, ParamValueSchema } from "./schemas"
import type { DetailCreatePayload, DetailUpdatePayload, ParamDetail, ParamMaster } from "./paramsService"

/** 說明欄提示：內容會明文寫入稽核前後值且無法塗銷（#112 Security Review MEDIUM）。 */
const DESC_HINT = "供維護者辨識用途；內容會記入稽核，請勿填入密碼、金鑰等機密"

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
  const originalDesc = detail.description ?? ""
  const [value, setValue] = useState(original)
  const [description, setDescription] = useState(originalDesc)
  const [descError, setDescError] = useState<string>()

  const restore = () => {
    setValue(original)
    setDescription(originalDesc)
  }

  const handleSave = () => {
    if (!ParamValueSchema.safeParse(value).success) {
      message.error("請輸入內容")
      setValue(original) // 空值不留白，還原原值
      return
    }
    const parsedDesc = ParamDescriptionSchema.safeParse(description)
    if (!parsedDesc.success) {
      setDescError(getFieldErrors(parsedDesc.error)._form)
      return
    }
    setDescError(undefined)
    // 平台級：onSaveDetail 內部跳確認，取消時 onCancel 還原欄位。儲存後面板保留（不自動關）。
    // 值與說明合併為單次 PUT，平台級確認只跳一次；說明留白送 null（清空），回顯統一為「—」。
    void Promise.resolve(
      onSaveDetail(
        master,
        detail.param_key,
        { param_value: value.trim(), description: parsedDesc.data || null },
        restore,
      ),
    ).catch(() => {})
  }

  return (
    <FormCard title={detail.param_name} onSave={handleSave} onCancel={onClose} cancelLabel="關閉">
      <Stack spacing={2}>
        <TextField
          autoFocus
          fullWidth
          label={detail.param_name}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <TextField
          fullWidth
          label="說明"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          error={Boolean(descError)}
          helperText={descError ?? DESC_HINT}
        />
      </Stack>
    </FormCard>
  )
}

/** LIST 型：管理清單項（改名 / 啟停 / 新增）。綠框面板，右下「關閉」。 */
function ListEdit({ row, onSaveDetail, onToggle, onAdd, onClose }: ParamEditPanelProps) {
  const { message } = useNotification()
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [descEdits, setDescEdits] = useState<Record<string, string>>({})
  const [descErrors, setDescErrors] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState("")
  const [newName, setNewName] = useState("")
  const [newDesc, setNewDesc] = useState("")
  const [addErrors, setAddErrors] = useState<{ param_key?: string; param_name?: string; description?: string }>({})
  if (row.kind !== "list") return null
  const { master } = row

  const editedOf = (key: string, original: string | null) => edits[key] ?? original ?? ""
  const setEdit = (key: string, v: string) => setEdits((prev) => ({ ...prev, [key]: v }))
  const descOf = (key: string, original: string | null) => descEdits[key] ?? original ?? ""
  const setDesc = (key: string, v: string) => setDescEdits((prev) => ({ ...prev, [key]: v }))

  const dropKey = (key: string) => (prev: Record<string, string>) => {
    const next = { ...prev }
    delete next[key]
    return next
  }
  /** 還原該筆的未儲存輸入（名稱 / 說明）並清掉其說明錯誤，避免錯誤訊息殘留在已還原的欄位上。 */
  const revertEdit = (key: string) => {
    setEdits(dropKey(key))
    setDescEdits(dropKey(key))
    setDescErrors(dropKey(key))
  }

  const handleSaveItem = (paramKey: string, edited: string, editedDesc: string) => {
    // 名稱上限 100（後端 _NameStr）；不可沿用 ParamValueSchema 的 500，否則 101~500 字會被後端回無 error_code 的 422
    const parsedName = ParamItemNameSchema.safeParse(edited)
    if (!parsedName.success) {
      message.error(getFieldErrors(parsedName.error)._form)
      revertEdit(paramKey)
      return
    }
    const parsedDesc = ParamDescriptionSchema.safeParse(editedDesc)
    if (!parsedDesc.success) {
      setDescErrors((prev) => ({ ...prev, [paramKey]: getFieldErrors(parsedDesc.error)._form }))
      return
    }
    setDescErrors(dropKey(paramKey))
    // 名稱與說明合併為單次 PUT；說明留白送 null（清空）
    void Promise.resolve(
      onSaveDetail(
        master,
        paramKey,
        { param_name: edited.trim(), description: parsedDesc.data || null },
        () => revertEdit(paramKey),
      ),
    ).catch(() => {})
  }

  const handleAdd = () => {
    const result = ParamItemCreateSchema.safeParse({
      param_key: newKey,
      param_name: newName,
      description: newDesc,
    })
    if (!result.success) {
      const f = getFieldErrors(result.error)
      setAddErrors({ param_key: f.param_key, param_name: f.param_name, description: f.description })
      return
    }
    setAddErrors({})
    // 說明留白時不帶欄位（新增走 POST，省略即為 NULL）
    const { description, ...rest } = result.data
    void onAdd(master, description ? { ...rest, description } : rest)
      .then(() => {
        setNewKey("")
        setNewName("")
        setNewDesc("")
      })
      .catch(() => {})
  }

  return (
    <Paper variant="outlined" sx={{ p: 3, mt: 2, maxWidth: 600, border: 2, borderColor: "primary.main" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Typography variant="h6">{master.param_name}</Typography>
        {master.detail_lock && <Chip size="small" icon={<LockIcon />} label="代碼鎖定" />}
      </Stack>

      {/* 每筆兩行（碼＋名稱 / 說明＋操作），讓新增的「說明」欄不必撐寬面板，維持 max-width 600（sti-ui-design §5）。 */}
      <Stack divider={<Divider flexItem />} spacing={1.5}>
        {master.details.map((d) => (
          <Stack key={d.param_key} spacing={1}>
            <Stack direction="row" alignItems="center" spacing={1}>
              <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 120 }}>
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
                sx={{ flexGrow: 1 }}
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "flex-start" }}>
              <TextField
                size="small"
                label={`${d.param_key} 說明`}
                value={descOf(d.param_key, d.description)}
                onChange={(e) => setDesc(d.param_key, e.target.value)}
                error={Boolean(descErrors[d.param_key])}
                helperText={descErrors[d.param_key]}
                sx={{ flexGrow: 1 }}
              />
              <Button
                size="small"
                variant="outlined"
                onClick={() =>
                  handleSaveItem(
                    d.param_key,
                    editedOf(d.param_key, d.param_name),
                    descOf(d.param_key, d.description),
                  )
                }
              >
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
          </Stack>
        ))}
      </Stack>

      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
        {DESC_HINT}
      </Typography>

      {!master.detail_lock && (
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          alignItems={{ sm: "flex-start" }}
          flexWrap="wrap"
          useFlexGap
          sx={{ mt: 2 }}
        >
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
          <TextField
            size="small"
            label="新增說明"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            error={Boolean(addErrors.description)}
            helperText={addErrors.description}
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
