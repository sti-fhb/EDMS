import LockIcon from "@mui/icons-material/Lock"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Chip from "@mui/material/Chip"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { getFieldErrors } from "../../utils/zodUtils"
import { ParamItemCreateSchema, ParamValueSchema } from "./schemas"
import type { DetailCreatePayload, ParamMaster } from "./paramsService"

interface ParamCardProps {
  master: ParamMaster
  onSaveValue: (master: ParamMaster, paramKey: string, value: string) => void | Promise<void>
  onToggle: (master: ParamMaster, paramKey: string, isEnabled: boolean) => void | Promise<void>
  onAdd: (master: ParamMaster, payload: DetailCreatePayload) => Promise<void>
}

/** 單一參數主檔卡：VALUE 型逐值編輯；LIST 型清單項改名 / 啟停 / 新增（DETAIL_LOCK 時碼唯讀、不可新增）。 */
export function ParamCard({ master, onSaveValue, onToggle, onAdd }: ParamCardProps) {
  // 各明細的編輯值（key→輸入值），未編輯者以 details 原值為主
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState("")
  const [newValue, setNewValue] = useState("")
  const [addErrors, setAddErrors] = useState<{ param_key?: string; param_value?: string }>({})

  const valueOf = (key: string, original: string | null) => edits[key] ?? original ?? ""
  const setEdit = (key: string, v: string) => setEdits((prev) => ({ ...prev, [key]: v }))

  const handleSave = (paramKey: string, original: string | null) => {
    const value = valueOf(paramKey, original)
    if (!ParamValueSchema.safeParse(value).success) return
    void onSaveValue(master, paramKey, value.trim())
  }

  const handleAdd = () => {
    const result = ParamItemCreateSchema.safeParse({ param_key: newKey, param_value: newValue })
    if (!result.success) {
      const f = getFieldErrors(result.error)
      setAddErrors({ param_key: f.param_key, param_value: f.param_value })
      return
    }
    setAddErrors({})
    void onAdd(master, result.data).then(() => {
      setNewKey("")
      setNewValue("")
    })
  }

  const isList = master.param_type === "LIST"

  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="h6" component="h2">
            {master.param_name}
          </Typography>
          <Chip size="small" label={master.param_id} variant="outlined" />
          {master.detail_lock && <Chip size="small" icon={<LockIcon />} label="代碼鎖定" color="default" />}
        </Stack>
        {master.description && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {master.description}
          </Typography>
        )}

        <Stack spacing={1.5}>
          {master.details.map((d) => (
            <Stack key={d.param_key} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              {isList && (
                <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 140 }}>
                  <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                    {d.param_key}
                  </Typography>
                  {master.detail_lock && <LockIcon fontSize="inherit" color="disabled" titleAccess="碼值唯讀" />}
                </Stack>
              )}
              <TextField
                size="small"
                label={isList ? `${d.param_key} 名稱` : d.param_key}
                value={valueOf(d.param_key, d.param_value)}
                onChange={(e) => setEdit(d.param_key, e.target.value)}
                sx={{ minWidth: 220 }}
              />
              <Button size="small" variant="outlined" onClick={() => handleSave(d.param_key, d.param_value)}>
                儲存
              </Button>
              {isList &&
                (d.is_enabled ? (
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
                ))}
            </Stack>
          ))}
        </Stack>

        {isList && !master.detail_lock && (
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
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              error={Boolean(addErrors.param_value)}
              helperText={addErrors.param_value}
            />
            <Button size="small" variant="contained" onClick={handleAdd}>
              新增
            </Button>
          </Stack>
        )}
      </CardContent>
    </Card>
  )
}
