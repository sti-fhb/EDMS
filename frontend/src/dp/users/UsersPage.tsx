import PeopleIcon from "@mui/icons-material/People"
import Badge from "@mui/material/Badge"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Divider from "@mui/material/Divider"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import { useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudActions } from "../../components/CrudActions"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { formatDateTime } from "../../utils/date"
import { UsersForm } from "./UsersForm"
import { useInvites } from "./useInvites"
import { useUsers } from "./useUsers"
import type { InviteRow, UserRow } from "./usersService"

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

function StatusChip({ row }: { row: UserRow }) {
  if (row.status === "DISABLED") return <Chip size="small" label="已停用" />
  if (isLocked(row)) return <Chip size="small" color="warning" label="已鎖定" />
  return <Chip size="small" color="success" label="啟用中" />
}

/** 邀請是否逾期（expires_date 已過）。 */
function isExpired(row: InviteRow): boolean {
  return new Date(row.expires_date) <= new Date()
}

export function UsersPage() {
  const [tab, setTab] = useState(0)
  const accounts = useUsers()
  const invites = useInvites(tab === 1)

  const [keyword, setKeyword] = useState("")
  const [status, setStatus] = useState("")
  const [inviteKeyword, setInviteKeyword] = useState("")

  // 切頁籤 / 查詢 / 重新整理時，收起可能開著的編輯（建立）表單，避免停留在上一情境
  const handleTabChange = (v: number) => {
    accounts.closeForm()
    setTab(v)
  }
  const searchAccounts = () => {
    accounts.closeForm()
    accounts.search(keyword, status)
  }
  const searchInvites = () => {
    accounts.closeForm()
    invites.search(inviteKeyword)
  }

  const accountColumns = useMemo<AppColumn<UserRow>[]>(
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
              <Button size="small" color="success" onClick={() => accounts.enableUser(r)}>
                啟用
              </Button>
            ) : isLocked(r) ? (
              <Button size="small" color="warning" onClick={() => accounts.unlockUser(r)}>
                解鎖
              </Button>
            ) : (
              <Button size="small" onClick={() => accounts.disableUser(r)}>
                停用
              </Button>
            )}
            <Button size="small" onClick={() => accounts.openEdit(r)}>
              編輯
            </Button>
          </Stack>
        ),
      },
    ],
    [accounts],
  )

  const inviteColumns = useMemo<AppColumn<InviteRow>[]>(
    () => [
      { key: "user_name", title: "姓名", dataIndex: "user_name" },
      { key: "email", title: "帳號（Email）", dataIndex: "email" },
      { key: "invited", title: "邀請寄出時間", render: (_v, r) => formatDateTime(r.created_date) },
      {
        key: "invite_status",
        title: "邀請狀態",
        render: (_v, r) =>
          isExpired(r) ? (
            <Chip size="small" color="warning" label="已逾期" />
          ) : (
            <Chip size="small" color="info" label="有效中" />
          ),
      },
      {
        key: "actions",
        title: "操作",
        align: "right",
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Button size="small" onClick={() => invites.resendInvite(r)}>
              重寄邀請
            </Button>
            <Button size="small" color="error" onClick={() => invites.cancelInvite(r)}>
              取消邀請
            </Button>
          </Stack>
        ),
      },
    ],
    [invites],
  )

  const tabsBar = (
    <Tabs value={tab} onChange={(_e, v) => handleTabChange(v)}>
      <Tab label="帳號" />
      <Tab
        label={
          <Badge color="secondary" badgeContent={invites.total} showZero={false} sx={{ pr: invites.total ? 1.5 : 0 }}>
            待啟用邀請
          </Badge>
        }
      />
    </Tabs>
  )

  if (tab === 1) {
    // 待啟用邀請頁籤
    return (
      <CrudPageLayout
        icon={<PeopleIcon color="primary" />}
        title="使用者管理"
        actions={<CrudActions onRefresh={searchInvites} onAdd={accounts.openCreate} addLabel="建立帳號" />}
        filterContent={
          <>
            {tabsBar}
            <Divider sx={{ mb: 2 }} />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "flex-end" }}>
              <TextField
                size="small"
                label="關鍵字（姓名 / Email）"
                value={inviteKeyword}
                onChange={(e) => setInviteKeyword(e.target.value)}
                sx={{ minWidth: 240 }}
              />
              <Button variant="outlined" size="small" onClick={searchInvites}>
                查詢
              </Button>
            </Stack>
          </>
        }
        table={
          <AppTable
            columns={inviteColumns}
            data={invites.items}
            rowKey="res_id"
            loading={invites.loading}
            emptyText="目前無待啟用邀請"
          />
        }
        pagination={<Pagination page={invites.page} total={invites.total} onPageChange={invites.setPage} />}
        form={
          accounts.formVisible && (
            <UsersForm
              key={accounts.editingRecord?.user_id ?? "create"}
              editingRecord={accounts.editingRecord}
              saving={accounts.saving}
              onSave={accounts.handleSave}
              onCancel={accounts.closeForm}
            />
          )
        }
      />
    )
  }

  // 帳號頁籤
  return (
    <CrudPageLayout
      icon={<PeopleIcon color="primary" />}
      title="使用者管理"
      actions={<CrudActions onRefresh={searchAccounts} onAdd={accounts.openCreate} addLabel="建立帳號" />}
      filterContent={
        <>
          {tabsBar}
          <Divider sx={{ mb: 2 }} />
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
            <Button variant="outlined" size="small" onClick={searchAccounts}>
              查詢
            </Button>
          </Stack>
        </>
      }
      table={
        <AppTable
          columns={accountColumns}
          data={accounts.items}
          rowKey="user_id"
          loading={accounts.loading}
          emptyText="查無使用者"
        />
      }
      pagination={<Pagination page={accounts.page} total={accounts.total} onPageChange={accounts.setPage} />}
      form={
        accounts.formVisible && (
          <UsersForm
            key={accounts.editingRecord?.user_id ?? "create"}
            editingRecord={accounts.editingRecord}
            saving={accounts.saving}
            onSave={accounts.handleSave}
            onCancel={accounts.closeForm}
          />
        )
      }
    />
  )
}
