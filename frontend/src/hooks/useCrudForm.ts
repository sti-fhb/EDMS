import { useCallback, useState } from "react"

interface UseCrudFormOptions {
  /** 關閉表單時的額外清理（選填）。 */
  onClose?: () => void
}

export interface CrudFormState<T> {
  formVisible: boolean
  editingRecord: T | null
  saving: boolean
  setSaving: (saving: boolean) => void
  openCreate: () => void
  openEdit: (record: T) => void
  closeForm: () => void
}

/**
 * CRUD 表單開關與編輯狀態管理。
 *
 * 統一 formVisible / editingRecord / saving 狀態機，禁止各頁手寫開關邏輯。
 * 不含 `handleSave`（各頁 API 簽名不同），由各頁 hook 自行實作。
 */
export function useCrudForm<T>(options: UseCrudFormOptions = {}): CrudFormState<T> {
  const { onClose } = options
  const [formVisible, setFormVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<T | null>(null)
  const [saving, setSaving] = useState(false)

  const openCreate = useCallback(() => {
    setEditingRecord(null)
    setFormVisible(true)
  }, [])

  const openEdit = useCallback((record: T) => {
    setEditingRecord(record)
    setFormVisible(true)
  }, [])

  const closeForm = useCallback(() => {
    setFormVisible(false)
    setEditingRecord(null)
    onClose?.()
  }, [onClose])

  return { formVisible, editingRecord, saving, setSaving, openCreate, openEdit, closeForm }
}
