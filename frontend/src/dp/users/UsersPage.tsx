import PeopleIcon from "@mui/icons-material/People"
import Button from "@mui/material/Button"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudActions } from "../../components/CrudActions"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { FormCard } from "../../components/FormCard"
import { Pagination } from "../../components/Pagination"
import { useCrudForm } from "../../hooks/useCrudForm"

/**
 * 使用者管理頁（US4 / dp-users）。
 *
 * PR1（本次）：以 CRUD toolkit 組出靜態骨架（篩選列 / 表格 / 分頁 / 操作 / 表單殼），
 * 作為 toolkit 的首個消費者驗證外觀與接線。實際資料查詢、建立 / 停用 / 解鎖 / 編輯
 * 與後端 `/api/dp/users` 端點於 PR2 接上。
 */

/** 清單列（PR2 將移至 dp/users/schemas 並對齊後端回應）。 */
interface UserRow {
  user_id: string
  user_name: string
  email: string
  status_label: string
  last_login_date: string | null
  created_date: string
}

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "active", label: "啟用中" },
  { value: "disabled", label: "已停用" },
  { value: "locked", label: "已鎖定" },
]

export function UsersPage() {
  const [keyword, setKeyword] = useState("")
  const [status, setStatus] = useState("")
  const [page, setPage] = useState(1)
  const { formVisible, openCreate, closeForm } = useCrudForm<UserRow>()

  const columns = useMemo<AppColumn<UserRow>[]>(
    () => [
      { key: "user_name", title: "姓名", dataIndex: "user_name" },
      { key: "email", title: "帳號（Email）", dataIndex: "email" },
      { key: "status", title: "狀態", dataIndex: "status_label" },
      { key: "last_login", title: "最後登入", dataIndex: "last_login_date" },
      { key: "created", title: "建立日期", dataIndex: "created_date" },
      {
        key: "actions",
        title: "操作",
        align: "right",
        render: () => (
          <Button size="small" disabled>
            操作（PR2）
          </Button>
        ),
      },
    ],
    [],
  )

  return (
    <CrudPageLayout
      icon={<PeopleIcon color="primary" />}
      title="使用者管理"
      actions={<CrudActions onRefresh={() => setPage(1)} onAdd={openCreate} addLabel="建立帳號" />}
      filterContent={
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "flex-end" }}>
          <TextField
            size="small"
            label="關鍵字（姓名 / Email）"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            sx={{ minWidth: 240 }}
          />
          <TextField
            select
            size="small"
            label="帳號狀態"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            sx={{ minWidth: 160 }}
          >
            {STATUS_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      }
      table={<AppTable columns={columns} data={[]} rowKey="user_id" emptyText="尚未接上資料（PR2）" />}
      pagination={<Pagination page={page} total={0} onPageChange={setPage} />}
      form={
        formVisible && (
          <FormCard title="建立帳號" onSave={closeForm} onCancel={closeForm} saveLabel="建立（PR2 接上）">
            <Stack spacing={2}>
              <TextField label="帳號（Email）" size="small" disabled />
              <TextField label="姓名" size="small" disabled />
              <TextField label="初始密碼" type="password" size="small" disabled />
            </Stack>
          </FormCard>
        )
      }
    />
  )
}
