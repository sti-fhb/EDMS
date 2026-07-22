import PeopleIcon from "@mui/icons-material/People"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import TextField from "@mui/material/TextField"
import { useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudActions } from "../../components/CrudActions"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
import { UsersForm } from "./UsersForm"
import { useUsers } from "./useUsers"
import type { UserRow } from "./usersService"

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "active", label: "啟用中" },
  { value: "disabled", label: "已停用" },
  { value: "locked", label: "已鎖定" },
]

/** 帳號是否鎖定中（ACTIVE 且 locked_until 尚未逾時）。 */
function isLocked(row: UserRow): boolean {
  return row.status === "ACTIVE" && row.locked_until !== null && new Date(row.locked_until) > new Date()
}

/** 衍生狀態 Chip：已停用 / 已鎖定 / 啟用中。 */
function StatusChip({ row }: { row: UserRow }) {
  if (row.status === "DISABLED") return <Chip size="small" label="已停用" />
  if (isLocked(row)) return <Chip size="small" color="warning" label="已鎖定" />
  return <Chip size="small" color="success" label="啟用中" />
}

export function UsersPage() {
  const {
    items,
    total,
    loading,
    page,
    setPage,
    search,
    formVisible,
    editingRecord,
    saving,
    openCreate,
    openEdit,
    closeForm,
    handleSave,
    disableUser,
    enableUser,
    unlockUser,
  } = useUsers()

  const [keyword, setKeyword] = useState("")
  const [status, setStatus] = useState("")

  const columns = useMemo<AppColumn<UserRow>[]>(
    () => [
      { key: "user_name", title: "姓名", dataIndex: "user_name" },
      { key: "email", title: "帳號（Email）", dataIndex: "email" },
      { key: "status", title: "狀態", render: (_v, r) => <StatusChip row={r} /> },
      { key: "last_login", title: "最後登入", render: (_v, r) => formatDateTime(r.last_login_date) },
      { key: "created", title: "建立日期", render: (_v, r) => formatDateTime(r.created_date) },
      {
        key: "actions",
        title: "操作",
        align: "right",
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            {r.status === "DISABLED" ? (
              <Button size="small" color="success" onClick={() => enableUser(r)}>
                啟用
              </Button>
            ) : isLocked(r) ? (
              <Button size="small" color="warning" onClick={() => unlockUser(r)}>
                解鎖
              </Button>
            ) : (
              <Button size="small" onClick={() => disableUser(r)}>
                停用
              </Button>
            )}
            <Button size="small" onClick={() => openEdit(r)}>
              編輯
            </Button>
          </Stack>
        ),
      },
    ],
    [enableUser, unlockUser, disableUser, openEdit],
  )

  return (
    <CrudPageLayout
      icon={<PeopleIcon color="primary" />}
      title="使用者管理"
      actions={<CrudActions onRefresh={() => search(keyword, status)} onAdd={openCreate} addLabel="建立帳號" />}
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
          <Button variant="outlined" size="small" onClick={() => search(keyword, status)}>
            查詢
          </Button>
        </Stack>
      }
      table={<AppTable columns={columns} data={items} rowKey="user_id" loading={loading} emptyText="查無使用者" />}
      pagination={<Pagination page={page} total={total} onPageChange={setPage} />}
      form={
        formVisible && (
          <UsersForm editingRecord={editingRecord} saving={saving} onSave={handleSave} onCancel={closeForm} />
        )
      }
    />
  )
}
