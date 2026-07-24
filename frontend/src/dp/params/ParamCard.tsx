import LockIcon from "@mui/icons-material/Lock"
import Button from "@mui/material/Button"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Chip from "@mui/material/Chip"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"

import { useNotification } from "../../contexts/NotificationContext"
import { getFieldErrors } from "../../utils/zodUtils"
import { ParamItemCreateSchema, ParamValueSchema } from "./schemas"
import type { DetailCreatePayload, DetailUpdatePayload, ParamMaster } from "./paramsService"

interface ParamCardProps {
  master: ParamMaster
  onSaveDetail: (
    master: ParamMaster,
    paramKey: string,
    payload: DetailUpdatePayload,
    onCancel?: () => void,
  ) => void | Promise<void>
  onToggle: (master: ParamMaster, paramKey: string, isEnabled: boolean) => void | Promise<void>
  onAdd: (master: ParamMaster, payload: DetailCreatePayload) => Promise<void>
}

/**
 * 單一參數主檔卡。
 * - VALUE 型：欄位標籤＝中文名稱（param_name，來自資料），編輯實際值（param_value）
 * - LIST 型：清單項改名（param_name）/ 啟停 / 新增（DETAIL_LOCK 時碼唯讀、不可新增）
 */
export function ParamCard({ master, onSaveDetail, onToggle, onAdd }: ParamCardProps) {
  const { message } = useNotification()
  const isList = master.param_type === "LIST"
  // 各明細的編輯值（key→輸入值）：VALUE 型編輯 param_value、LIST 型編輯 param_name
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState("")
  const [newName, setNewName] = useState("")
  const [addErrors, setAddErrors] = useState<{ param_key?: string; param_name?: string }>({})

  const editedOf = (key: string, original: string | null) => edits[key] ?? original ?? ""
  const setEdit = (key: string, v: string) => setEdits((prev) => ({ ...prev, [key]: v }))
  const revertEdit = (key: string) =>
    setEdits((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })

  const handleSave = (paramKey: string, edited: string) => {
    if (!ParamValueSchema.safeParse(edited).success) {
      message.error("請輸入內容")
      revertEdit(paramKey) // 空值不留白，還原為原值
      return
    }
    // VALUE 型送 param_value（實際值）；LIST 型送 param_name（中文名稱）
    const payload: DetailUpdatePayload = isList ? { param_name: edited.trim() } : { param_value: edited.trim() }
    // onCancel：平台級警告被取消時還原欄位（避免 UI 顯示未儲存值誤導）
    // 錯誤已由 useParams 內部以 toast 呈現並 rethrow；此處吞掉 rejection 避免未捕捉警告
    void Promise.resolve(onSaveDetail(master, paramKey, payload, () => revertEdit(paramKey))).catch(() => {})
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
          {master.details.map((d) => {
            // VALUE：標籤＝中文名稱、編輯值；LIST：顯示碼、編輯中文名稱
            const original = isList ? d.param_name : d.param_value
            const label = isList ? `${d.param_key} 名稱` : d.param_name
            return (
              <Stack
                key={d.param_key}
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                alignItems={{ sm: "center" }}
              >
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
                  label={label}
                  value={editedOf(d.param_key, original)}
                  onChange={(e) => setEdit(d.param_key, e.target.value)}
                  sx={{ minWidth: 240 }}
                />
                <Button size="small" variant="outlined" onClick={() => handleSave(d.param_key, editedOf(d.param_key, original))}>
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
            )
          })}
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
      </CardContent>
    </Card>
  )
}