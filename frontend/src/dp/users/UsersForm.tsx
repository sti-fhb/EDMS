import LockIcon from "@mui/icons-material/Lock"
import InputAdornment from "@mui/material/InputAdornment"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useState } from "react"

import { FormCard } from "../../components/FormCard"
import { getFieldErrors } from "../../utils/zodUtils"
import { UserCreateSchema, UserUpdateSchema } from "./schemas"
import type { UserCreatePayload, UserRow, UserUpdatePayload } from "./usersService"

interface UsersFormProps {
  /** 有值＝編輯（僅改姓名，Email 唯讀）；null＝建立帳號（Email + 姓名，寄邀請信）。 */
  editingRecord: UserRow | null
  saving: boolean
  onSave: (values: UserCreatePayload | UserUpdatePayload) => void
  onCancel: () => void
}

/**
 * 使用者建立 / 編輯表單（US4 #67）。
 * - 建立：Email + 姓名 → 送出後寄邀請信，使用者自設密碼啟用（管理者不設密碼）。
 * - 編輯：僅可改姓名；Email 為登入帳號、唯讀不可代改（本人變更走個人資料維護）。
 */
export function UsersForm({ editingRecord, saving, onSave, onCancel }: UsersFormProps) {
  const isEdit = editingRecord !== null
  const [email, setEmail] = useState(editingRecord?.email ?? "")
  const [userName, setUserName] = useState(editingRecord?.user_name ?? "")
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const handleSave = () => {
    if (isEdit) {
      const parsed = UserUpdateSchema.safeParse({ user_name: userName })
      setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
      if (parsed.success) onSave(parsed.data)
    } else {
      const parsed = UserCreateSchema.safeParse({ email, user_name: userName })
      setFieldErrors(getFieldErrors(parsed.success ? null : parsed.error))
      if (parsed.success) onSave(parsed.data)
    }
  }

  return (
    <FormCard
      title={isEdit ? "編輯帳號" : "建立帳號（寄送邀請）"}
      onSave={handleSave}
      onCancel={onCancel}
      saving={saving}
      saveLabel={isEdit ? "儲存" : "寄送邀請"}
    >
      <Stack spacing={2}>
        <TextField
          label="帳號（Email）"
          size="small"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={Boolean(fieldErrors.email)}
          // 編輯時 Email 唯讀（登入帳號不可代改）；建立時可填並提示將寄邀請信
          helperText={
            isEdit ? "Email 為登入帳號，不可修改；使用者可於個人資料維護自行變更" : fieldErrors.email ?? "將寄送邀請信至此 Email"
          }
          disabled={isEdit}
          InputProps={
            isEdit
              ? { readOnly: true, startAdornment: (
                  <InputAdornment position="start">
                    <LockIcon fontSize="small" color="disabled" />
                  </InputAdornment>
                ) }
              : undefined
          }
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
      </Stack>
    </FormCard>
  )
}