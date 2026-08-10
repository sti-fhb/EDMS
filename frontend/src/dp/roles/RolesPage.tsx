import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import FormControlLabel from "@mui/material/FormControlLabel"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { MODULE_LABELS, MODULE_ROLES, rolesApi } from "./rolesService"
import type { AssignmentRow, GroupOption } from "./rolesService"
import { Pagination } from "../../components/Pagination"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

/**
 * 權限管理（dp-roles，US7）：ET / DM 共用之角色 / 群組指派入口。
 * DP 為轉接層——僅顯示當前使用者「可管理的模組」頁籤（後端 is_module_admin 過濾），
 * 每列角色核取 + 群組多選兩維度獨立、即時生效；核心寫入與自我保護在各模組 provider。
 */
export function RolesPage() {
  const { data: modules, isPending } = useQuery({ queryKey: ["roles", "modules"], queryFn: rolesApi.modules })
  const [selected, setSelected] = useState<string | null>(null)
  // 於 render 期衍生 active（避免 effect 內 setState）：使用者選過用其值，否則預設第一個
  const active = selected ?? (modules && modules.length > 0 ? modules[0] : null)

  if (isPending) return null
  if (!modules || modules.length === 0) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          權限管理
        </Typography>
        <Alert severity="info">您目前無可管理的模組權限。</Alert>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        權限管理（角色指派）
      </Typography>
      <Tabs value={active ?? modules[0]} onChange={(_, v) => setSelected(v)} sx={{ mb: 2 }}>
        {modules.map((m) => (
          <Tab key={m} value={m} label={MODULE_LABELS[m] ?? m} />
        ))}
      </Tabs>
      {active && <AssignmentsTab module={active} />}
    </Box>
  )
}

/** 單一模組之權限指派表（查使用者 + 角色核取 + 群組多選）。 */
function AssignmentsTab({ module }: { module: string }) {
  const qc = useQueryClient()
  const { message } = useNotification()
  const [keyword, setKeyword] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<AssignmentRow | null>(null)

  const { data } = useQuery({
    queryKey: ["roles", module, "assignments", { keyword: search, page }],
    queryFn: () => rolesApi.list({ module, keyword: search, page, limit: 20 }),
  })
  const { data: groupOptions } = useQuery({
    queryKey: ["roles", module, "group-options"],
    queryFn: () => rolesApi.groupOptions(module),
  })

  const assignMut = useMutation({
    // source 標記本次是改「角色」還是「可見對象」，供畫面只 disable 對應維度（存可見對象時角色不閃）
    mutationFn: ({
      userId,
      roles,
      groups,
    }: {
      userId: string
      roles: string[]
      groups: string[]
      source: "role" | "group"
    }) => rolesApi.assign(module, userId, { roles, groups }),
    onSuccess: () => {
      message.success("角色 / 標籤已更新並即時生效")
      qc.invalidateQueries({ queryKey: ["roles", module, "assignments"] })
      // 角色異動可能改變「當前使用者自己」的模組權限（如把自己加/移 DM 角色）→ 讓側欄 module-summary
      // 重抓，側欄 DM 功能群組即時顯示/隱藏，不必重登或硬重整（module-summary 由側欄常駐觀察）。
      qc.invalidateQueries({ queryKey: QUERY_KEYS.moduleSummary.get() })
    },
    onError: (err) => {
      message.error(toApiError(err).errorMessage)
      qc.invalidateQueries({ queryKey: ["roles", module, "assignments"] }) // 還原勾選（如自我保護擋下）
    },
  })

  const toggleRole = (row: AssignmentRow, role: string) => {
    const roles = row.roles.includes(role) ? row.roles.filter((r) => r !== role) : [...row.roles, role]
    assignMut.mutate({ userId: row.user_id, roles, groups: row.groups, source: "role" })
  }

  const roleDefs = MODULE_ROLES[module] ?? []
  const rows = data?.data ?? []

  return (
    <Stack spacing={2}>
      <Box sx={{ display: "flex", gap: 1 }}>
        <TextField
          size="small"
          label="關鍵字（姓名 / Email）"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setSearch(keyword)
              setPage(1)
            }
          }}
        />
        <Button
          variant="outlined"
          size="small"
          onClick={() => {
            setSearch(keyword)
            setPage(1)
          }}
        >
          查詢
        </Button>
      </Box>

      {/* 固定表格版面：欄寬由表頭決定、不隨儲存格內容（可見對象標籤數）變動，避免加標籤時其他欄位位移 */}
      <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: "20%" }}>帳號</TableCell>
            <TableCell sx={{ width: "10%" }}>姓名</TableCell>
            {roleDefs.map((r) => (
              <TableCell key={r.code} align="center" sx={{ width: "7%" }}>
                {r.label}
              </TableCell>
            ))}
            <TableCell sx={{ width: "26%" }}>可見對象</TableCell>
            <TableCell sx={{ width: "16%" }}>最後異動</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.user_id}>
              <TableCell>{row.email}</TableCell>
              <TableCell>{row.user_name}</TableCell>
              {roleDefs.map((r) => (
                <TableCell key={r.code} align="center">
                  <Checkbox
                    size="small"
                    checked={row.roles.includes(r.code)}
                    // 只在「正對本列做角色操作」時 disable；存可見對象（source==="group"）不影響角色 checkbox（不閃）
                    disabled={
                      assignMut.isPending &&
                      assignMut.variables?.userId === row.user_id &&
                      assignMut.variables?.source === "role"
                    }
                    onChange={() => toggleRole(row, r.code)}
                    slotProps={{ input: { "aria-label": `${row.user_name} ${r.label}` } }}
                  />
                </TableCell>
              ))}
              <TableCell sx={{ verticalAlign: "top" }}>
                {/* 標籤 + 編輯鈕以 flex-wrap 收在本欄固定寬度內，多選時只在本格內換行、不擠壓其他欄 */}
                <Box sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 0.5 }}>
                  {row.groups.length === 0 ? (
                    <Typography variant="caption" color="text.secondary">
                      未指派
                    </Typography>
                  ) : (
                    row.groups.map((g) => (
                      <Chip key={g} size="small" label={groupOptions?.find((o) => o.code === g)?.name ?? g} />
                    ))
                  )}
                  <Button size="small" onClick={() => setEditing(row)}>
                    編輯
                  </Button>
                </Box>
              </TableCell>
              <TableCell>
                <Typography variant="caption" color="text.secondary">
                  {row.last_modified_by
                    ? `${row.last_modified_by_name ?? row.last_modified_by}｜${row.last_modified_date?.slice(0, 10) ?? ""}`
                    : "—"}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {data && (
        <Pagination page={data.meta.page} total={data.meta.total} pageSize={data.meta.limit} onPageChange={setPage} />
      )}

      {editing && (
        <GroupEditDialog
          row={editing}
          options={groupOptions ?? []}
          onClose={() => setEditing(null)}
          onSave={(groups) => {
            assignMut.mutate({ userId: editing.user_id, roles: editing.roles, groups, source: "group" })
            setEditing(null)
          }}
        />
      )}
    </Stack>
  )
}

/** 群組多選 dialog（可見對象 / 標籤指派）。 */
function GroupEditDialog({
  row,
  options,
  onClose,
  onSave,
}: {
  row: AssignmentRow
  options: GroupOption[]
  onClose: () => void
  onSave: (groups: string[]) => void
}) {
  const [selected, setSelected] = useState<string[]>(row.groups)
  const toggle = (code: string) =>
    setSelected((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]))

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>編輯可見對象</DialogTitle>
      <DialogContent>
        {options.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            尚無可選群組。
          </Typography>
        ) : (
          <Stack>
            {options.map((o) => (
              <FormControlLabel
                key={o.code}
                control={<Checkbox checked={selected.includes(o.code)} onChange={() => toggle(o.code)} />}
                label={o.name}
              />
            ))}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button variant="contained" onClick={() => onSave(selected)}>
          儲存
        </Button>
      </DialogActions>
    </Dialog>
  )
}