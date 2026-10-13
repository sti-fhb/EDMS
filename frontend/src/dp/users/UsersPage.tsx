import Badge from "@mui/material/Badge"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Divider from "@mui/material/Divider"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Tooltip from "@mui/material/Tooltip"
import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudActions } from "../../components/CrudActions"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { Pagination } from "../../components/Pagination"
import { useDebouncedValue } from "../../hooks/useDebouncedValue"
import { formatDateTime } from "../../utils/date"
import { PROFILE_ME_QUERY_KEY, profileApi } from "../user/profileService"
import { isDisabled, isLocked } from "./accountStatus"
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

/**
 * 「停用」按鈕：對自己那列灰階並以 tooltip 說明原因（#603）。
 *
 * 後端 `DP_USER_006` 本來就會擋，但那是**按下去、過完二次確認之後**才知道——而確認視窗寫著
 * 「停用後 ET / DM 兩端將同步失效」，使用者會以為真的發生了；失敗後對話框還會留著邀請重試一個
 * 永遠不會成功的動作。`spec_us4.md` FR-DP-US4-06 的用字是 MUST NOT **可**，所以畫面層也要擋。
 *
 * ⛔ 不用隱藏按鈕：專案既有模式（DM07 `LockableButton`）是灰階 + 提示，隱藏會讓人以為功能壞了。
 * disabled 的 MUI Button 不觸發 tooltip 事件，故以 span 包裹作為事件載體（同 DM07）。
 */
function SelfAwareDisableButton({ isSelf, onDisable }: { isSelf: boolean; onDisable: () => void }) {
  const reason = isSelf ? "無法停用自己的帳號" : ""
  return (
    <Tooltip title={reason}>
      <Box component="span" sx={{ display: "inline-flex" }} aria-label={reason || undefined}>
        <Button size="small" disabled={isSelf} onClick={onDisable}>
          停用
        </Button>
      </Box>
    </Tooltip>
  )
}

function StatusChip({ row }: { row: UserRow }) {
  if (isDisabled(row)) return <Chip size="small" label="已停用" />
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

  /**
   * 目前登入者——用來判斷哪一列是自己（#603）。與 `AppHeader` / `ProfilePage` 共用同一 query key。
   *
   * ⚠️ **刻意不為它加載入閘**：`AppHeader` 常駐於 `AppShell`、而本頁在 `AppShell` 之下，使用者走到
   * DP01 時這筆必定已在快取、`useQuery` 同步回值。為「進得了本頁卻尚未取得 me」這個不存在的路徑
   * 加防禦碼，違反 `sti-coding-style.md`「不為不存在的情境寫防禦碼」。
   */
  const { data: me } = useQuery({ queryKey: PROFILE_ME_QUERY_KEY, queryFn: profileApi.getMe })
  const myUserId = me?.user_id
  // useCallback：供下方 accountColumns 的 useMemo 正確列入依賴（me 晚到時要重算，否則自己那列仍可按）
  const isSelf = useCallback((row: UserRow) => row.user_id === myUserId, [myUserId])

  // 即時查詢：關鍵字去抖（350ms）避免每字元一次 request；帳號狀態變動即時反映，免按「查詢」。
  // 篩選條件變動視為情境切換，一併收起可能開著的編輯 / 建立表單（避免停留在已被篩掉的列）。
  const debouncedKeyword = useDebouncedValue(keyword, 350)
  const debouncedInviteKeyword = useDebouncedValue(inviteKeyword, 350)
  // 解構出穩定的 useCallback 參照供 effect 依賴（accounts / invites 物件每次 render 重建，方法本身穩定）
  const { search: searchAccountsQuery, closeForm: closeAccountsForm } = accounts
  const { search: searchInvitesQuery } = invites
  useEffect(() => {
    closeAccountsForm()
    searchAccountsQuery(debouncedKeyword, status)
  }, [debouncedKeyword, status, searchAccountsQuery, closeAccountsForm])
  useEffect(() => {
    closeAccountsForm()
    searchInvitesQuery(debouncedInviteKeyword)
  }, [debouncedInviteKeyword, searchInvitesQuery, closeAccountsForm])

  // 切頁籤 / 重新整理時，收起可能開著的編輯（建立）表單，避免停留在上一情境
  const handleTabChange = (v: number) => {
    accounts.closeForm()
    setTab(v)
  }
  const refreshAccounts = () => {
    accounts.closeForm()
    accounts.search(keyword, status)
  }
  const refreshInvites = () => {
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
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-start">
            {/* 走共用的 isDisabled()，不自己比對狀態字面值——那支判定存在的理由就是避免 DP01 / DP02 漂移 */}
            {isDisabled(r) ? (
              <Button size="small" color="success" onClick={() => accounts.enableUser(r)}>
                啟用
              </Button>
            ) : isLocked(r) ? (
              <Button size="small" color="warning" onClick={() => accounts.unlockUser(r)}>
                解鎖
              </Button>
            ) : (
              <SelfAwareDisableButton isSelf={isSelf(r)} onDisable={() => accounts.disableUser(r)} />
            )}
            <Button size="small" onClick={() => accounts.openEdit(r)}>
              編輯
            </Button>
          </Stack>
        ),
      },
    ],
    // isSelf 不可省：它閉包捕獲 myUserId，少了這項則 me 晚到時 memo 不重算、自己那列仍可按
    [accounts, isSelf],
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
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-start">
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
        code="DP01"
        actions={<CrudActions onRefresh={refreshInvites} onAdd={accounts.openCreate} addLabel="建立帳號" />}
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
            </Stack>
          </>
        }
        table={
          <AppTable
            columns={inviteColumns}
            data={invites.items}
            rowKey="invite_id"
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
      code="DP01"
      actions={<CrudActions onRefresh={refreshAccounts} onAdd={accounts.openCreate} addLabel="建立帳號" />}
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
