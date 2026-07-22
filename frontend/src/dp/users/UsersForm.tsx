import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useState } from "react"

import { FormCard } from "../../components/FormCard"
import { getFieldErrors } from "../../utils/zodUtils"
import { UserCreateSchema, UserUpdateSchema } from "./schemas"
import type { UserCreatePayload, UserRow, UserUpdatePayload } from "./usersService"

interface UsersFormProps {
  /** 有值＝編輯基本資料（姓名 / Email）；null＝建立帳號（Email / 姓名 / 初始密碼）。 */
  editingRecord: UserRow | null
  saving: boolean
  onSave: (values: UserCreatePayload | UserUpdatePayload) => void
  onCancel: () => void
}

/**
 * 使用者建立 / 編輯表單。
 * - 建立：Email + 姓名 + 初始密碼（帳號建立後首次登入強制變更）。
 * - 編輯：姓名 + Email（管理者代改直接生效，不走驗證信）。
 */
export function UsersForm({ editingRecord, saving, onSave, onCancel }: UsersFormProps) {
  const isEdit = editingRecord !== null
  const [email, setEmail] = useState(editingRecord?.email ?? "")
  const [userName, setUserName] = useState(editingRecord?.user_name ?? "")
  const [password, setPassword] = useState("")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const handleSave = () => {
    if (isEdit) {
      const values = { user_name: userName, email }
      const parsed = UserUpdateSchema.safeParse(values)
      setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
      if (parsed.success) onSave(parsed.data)
    } else {
      const values = { email, user_name: userName, password }
      const parsed = UserCreateSchema.safeParse(values)
      setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
      if (parsed.success) onSave(parsed.data)
    }
  }

  return (
    <FormCard
      title={isEdit ? "編輯帳號基本資料" : "建立帳號"}
      onSave={handleSave}
      onCancel={onCancel}
      saving={saving}
      saveLabel={isEdit ? "儲存" : "建立"}
    >
      <Stack spacing={2}>
        <TextField
          label="帳號（Email）"
          size="small"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={Boolean(fieldErrors.email)}
          helperText={fieldErrors.email}
          fullWidth
        />
        <TextField
          label="姓名"
          size="small"
          value={userName}
          onChange={(e) => setUserName(e.target.value)}
          error={Boolean(fieldErrors.user_name)}
          helperText={fieldErrors.user_name}
          fullWidth
        />
        {!isEdit && (
          <TextField
            label="初始密碼"
            type="password"
            size="small"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={Boolean(fieldErrors.password)}
            helperText={fieldErrors.password ?? "至少 8 字元，含大小寫 / 數字 / 特殊符號至少 3 種"}
            fullWidth
          />
        )}
      </Stack>
    </FormCard>
  )
}
