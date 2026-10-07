import AddIcon from "@mui/icons-material/Add"
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Checkbox from "@mui/material/Checkbox"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogActions from "@mui/material/DialogActions"
import DialogContent from "@mui/material/DialogContent"
import DialogTitle from "@mui/material/DialogTitle"
import Divider from "@mui/material/Divider"
import FormControlLabel from "@mui/material/FormControlLabel"
import IconButton from "@mui/material/IconButton"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
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
import { useMemo, useState } from "react"
import type { ReactNode } from "react"

import { MODULE_LABELS, MODULE_ROLES, groupDimensionLabel, pairHint, rolesApi, sortModulesForTabs } from "./rolesService"
import { decodeAudiencePair, encodeAudiencePair } from "./rolesService"
import type { AssignmentRow, GroupOption } from "./rolesService"
import { Pagination } from "../../components/Pagination"
import { FilterCard } from "../../components/FilterCard"
import { ScreenHeader } from "../../components/ScreenHeader"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { isAccountUsable, isDisabled, isLocked } from "../users/accountStatus"
import { toApiError } from "../../services/http"
import { formatDateTime } from "../../utils/date"

/**
 * 權限管理（dp-roles，US7）：ET / DM 共用之角色 / 群組指派入口。
 * DP 為轉接層——僅顯示當前使用者「可管理的模組」頁籤（後端 is_module_admin 過濾），
 * 每列角色核取 + 群組多選兩維度獨立、即時生效；核心寫入與自我保護在各模組 provider。
 */
export function RolesPage() {
  const { data: rawModules, isPending } = useQuery({ queryKey: ["roles", "modules"], queryFn: rolesApi.modules })
  const [selected, setSelected] = useState<string | null>(null)
  // 後端回的是 registry 註冊順序，顯示順序由前端決定（#310）；排序須在衍生 active 之前，
  // 否則預設選中的仍是排序前的第一個。
  const modules = useMemo(() => (rawModules ? sortModulesForTabs(rawModules) : undefined), [rawModules])
  // 於 render 期衍生 active（避免 effect 內 setState）：使用者選過用其值，否則預設第一個
  const active = selected ?? (modules && modules.length > 0 ? modules[0] : null)

  if (isPending) return null
  if (!modules || modules.length === 0) {
    return (
      <Box>
        <ScreenHeader code="DP02" />
        <Alert severity="info">您目前無可管理的模組權限。</Alert>
      </Box>
    )
  }

  return (
    <Box>
      <ScreenHeader code="DP02" />
      {active && (
        <AssignmentsTab
          module={active}
          tabs={
            <Tabs value={active} onChange={(_, v) => setSelected(v)}>
              {modules.map((m) => (
                <Tab key={m} value={m} label={MODULE_LABELS[m] ?? m} />
              ))}
            </Tabs>
          }
        />
      )}
    </Box>
  )
}

/**
 * 單一模組之權限指派表（查使用者 + 角色核取 + 群組多選）。
 * `tabs`（模組頁籤）由父層傳入，與關鍵字查詢放在同一張白底卡（比照 DP01 使用者管理）。
 */
function AssignmentsTab({ module, tabs }: { module: string; tabs: ReactNode }) {
  const qc = useQueryClient()
  const { message } = useNotification()
  const [keyword, setKeyword] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<AssignmentRow | null>(null)
  // 群組維度的稱呼隨模組不同（DM 可見對象 / ET 受訓單位標籤），欄位標題與編輯視窗共用同一個值
  const dimensionLabel = groupDimensionLabel(module)

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
      // 角色異動可能改變「當前使用者自己」的模組權限（如把自己加/移 DM 角色）→ 讓側欄重抓，
      // 功能群組與逐項閘即時顯示/隱藏，不必重登或硬重整（皆由側欄常駐觀察）。
      // ⚠️ 側欄的可見性來自**四個獨立 query**，少 invalidate 任一個，該項就要等切頁才更新：
      //   module-summary → 模組群組 + 系統管理者後台群組（is_admin）
      //   dm/admin-access → 已廢止 / 變更歷程 / KPI
      //   dm/reviewer-access → 簽核中心
      //   dm-personal/access → 個人專區
      qc.invalidateQueries({ queryKey: QUERY_KEYS.moduleSummary.get() })
      qc.invalidateQueries({ queryKey: ["dm", "admin-access"] })
      qc.invalidateQueries({ queryKey: ["dm", "reviewer-access"] })
      qc.invalidateQueries({ queryKey: ["dm-personal", "access"] })
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

  // 版面比照 DP01 使用者管理：頁籤 + 關鍵字查詢同一張白底卡、表格一張白底卡
  return (
    <>
      <FilterCard>
        {tabs}
        <Divider sx={{ mb: 2 }} />
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
      </FilterCard>

      {/* 固定表格版面：欄寬由表頭決定、不隨儲存格內容（可見對象標籤數）變動，避免加標籤時其他欄位位移 */}
      <Paper variant="outlined">
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
              <TableCell sx={{ width: "26%" }}>{dimensionLabel}</TableCell>
              <TableCell sx={{ width: "16%" }}>最後異動</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => {
              // 停用 / 鎖定中的帳號登不進系統 → 整列唯讀，兩維度皆不可操作（加權與降權都不行，SA 裁示）。
              // 需要降權時的路徑是：先於使用者管理頁啟用帳號 → 撤權 → 再停用。
              // 後端 assign 另以 DP_ROLE_004 硬擋——本判定只是體驗，非權限邊界。
              const editable = isAccountUsable(row)
              return (
                <TableRow key={row.user_id} sx={editable ? undefined : { opacity: 0.5 }}>
                  <TableCell>{row.email}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <span>{row.user_name}</span>
                      {/* 兩種狀態都用預設灰：本頁的語意是「此列不可操作」，非警示 */}
                      {isDisabled(row) && <Chip size="small" label="已停用" />}
                      {isLocked(row) && (
                        <Chip size="small" label="已鎖定" title={`鎖定至 ${formatDateTime(row.locked_until)}`} />
                      )}
                    </Stack>
                  </TableCell>
                  {roleDefs.map((r) => (
                    <TableCell key={r.code} align="center">
                      <Checkbox
                        size="small"
                        checked={row.roles.includes(r.code)}
                        // 帳號不可用 → 整列唯讀；否則只在「正對本列做角色操作」時 disable
                        //（存可見對象 source==="group" 不影響角色 checkbox，不閃）
                        disabled={
                          !editable ||
                          (assignMut.isPending &&
                            assignMut.variables?.userId === row.user_id &&
                            assignMut.variables?.source === "role")
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
                          <Chip key={g} size="small" label={groupLabel(g, groupOptions)} />
                        ))
                      )}
                      {/* 不可用帳號：保留 disabled 鈕而非隱藏，維持固定表格版面（tableLayout: fixed）不位移 */}
                      <Button size="small" disabled={!editable} onClick={() => setEditing(row)}>
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
              )
            })}
          </TableBody>
        </Table>
      </Paper>

      {data && (
        <Pagination page={data.meta.page} total={data.meta.total} pageSize={data.meta.limit} onPageChange={setPage} />
      )}

      {editing && (
        <GroupEditDialog
          row={editing}
          options={groupOptions ?? []}
          dimensionLabel={dimensionLabel}
          hintText={pairHint(module)}
          onClose={() => setEditing(null)}
          onSave={(groups) => {
            assignMut.mutate({ userId: editing.user_id, roles: editing.roles, groups, source: "group" })
            setEditing(null)
          }}
        />
      )}
    </>
  )
}

/** 模組是否以 (單位, 職位) 配對表達群組——由 provider 自報的 `kind` 判定，DP 不硬編碼模組語彙。 */
function isPairedModule(options: GroupOption[]): boolean {
  return options.some((o) => o.kind === "UNIT")
}

/**
 * 群組值 → 畫面標籤。
 *
 * 配對模組（DM）顯示「單位 + 職位」；**單位未指定者顯示灰字提示**而非留白——空白無從區分
 * 「尚未設定」與「設定為不限」，而前者會讓該使用者安靜地看不到一整批有單位限制的文件（#437）。
 */
function groupLabel(value: string, options: GroupOption[] | undefined): string {
  const opts = options ?? []
  if (!isPairedModule(opts)) return opts.find((o) => o.code === value)?.name ?? value
  const [unitCode, roleCode] = decodeAudiencePair(value)
  const roleName = opts.find((o) => o.code === roleCode)?.name ?? roleCode
  if (!unitCode) return `（單位未指定）+ ${roleName}`
  return `${opts.find((o) => o.code === unitCode)?.name ?? unitCode} + ${roleName}`
}

/** 群組指派 dialog（可見對象 / 標籤）。停用 / 鎖定帳號之編輯鈕為 disabled，不會開到本 dialog。 */
function GroupEditDialog({
  row,
  options,
  dimensionLabel,
  hintText,
  onClose,
  onSave,
}: {
  row: AssignmentRow
  options: GroupOption[]
  /** 群組維度之稱呼（DM 可見對象 / ET 受訓對象），由呼叫端依模組傳入。 */
  dimensionLabel: string
  /** 配對模式的說明句（後果隨模組而異，見 `MODULE_PAIR_HINTS`）。 */
  hintText: string
  onClose: () => void
  onSave: (groups: string[]) => void
}) {
  const [selected, setSelected] = useState<string[]>(row.groups)
  // 開啟當下的既有授權：其中「單位未指定」者為導入配對前之過渡狀態，儲存時須原樣保留，
  // 不可與「使用者新加但沒選完」的列一起被丟掉——那會讓既有授權在按下儲存時靜默消失。
  // 用 lazy useState 而非 useRef：下方 `hasIncompleteNewPair` 於 render 期間讀取，
  // 而 render 期間存取 ref 被 react-hooks 規則擋下（CI 的 ESLint 會紅）。
  const [initialGroups] = useState(() => new Set(row.groups))
  const paired = isPairedModule(options)
  const unitOptions = options.filter((o) => o.kind === "UNIT")
  const roleOptions = options.filter((o) => o.kind !== "UNIT")

  const toggle = (code: string) =>
    setSelected((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]))

  // 配對模式：一列一組，兩欄以下拉選；一律建新陣列，不就地修改。
  const addPair = () => setSelected((prev) => [...prev, encodeAudiencePair("", "")])
  const updatePair = (idx: number, unitCode: string, roleCode: string) =>
    setSelected((prev) => prev.map((v, i) => (i === idx ? encodeAudiencePair(unitCode, roleCode) : v)))
  const removePair = (idx: number) => setSelected((prev) => prev.filter((_, i) => i !== idx))
  /**
   * 送出前濾掉不完整的**新增**列。
   *
   * 兩種「不完整」要分開處理：使用者新加卻沒選完的列不送出（半組配對在後端不生效，送出只會
   * 讓「已指派」多一筆看似有效的資料）；而既有的「單位未指定」列必須原樣保留——那是導入配對前
   * 的授權，UI 不該在使用者只是改別列時把它清掉。
   */
  const completePairs = () =>
    selected.filter((v) => {
      const [unitCode, roleCode] = decodeAudiencePair(v)
      return roleCode !== "" && (unitCode !== "" || initialGroups.has(v))
    })
  const hasIncompleteNewPair = selected.some((v) => {
    const [unitCode, roleCode] = decodeAudiencePair(v)
    return (roleCode === "" || unitCode === "") && !initialGroups.has(v)
  })

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>編輯{dimensionLabel}</DialogTitle>
      <DialogContent>
        {options.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            尚無可選群組。
          </Typography>
        ) : paired ? (
          <Stack spacing={1} sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {hintText}
            </Typography>
            {selected.map((value, idx) => {
              const [unitCode, roleCode] = decodeAudiencePair(value)
              return (
                <Stack key={`${value}-${idx}`} direction="row" spacing={1} alignItems="center">
                  <TextField
                    select
                    size="small"
                    label="單位"
                    sx={{ flex: 1 }}
                    value={unitCode}
                    onChange={(e) => updatePair(idx, e.target.value, roleCode)}
                  >
                    {unitOptions.map((o) => (
                      <MenuItem key={o.code} value={o.code}>
                        {o.name}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label="職位"
                    sx={{ flex: 1 }}
                    value={roleCode}
                    onChange={(e) => updatePair(idx, unitCode, e.target.value)}
                  >
                    {roleOptions.map((o) => (
                      <MenuItem key={o.code} value={o.code}>
                        {o.name}
                      </MenuItem>
                    ))}
                  </TextField>
                  <IconButton size="small" aria-label={`移除第 ${idx + 1} 組`} onClick={() => removePair(idx)}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
              )
            })}
            <Box>
              <Button size="small" startIcon={<AddIcon />} onClick={addPair}>
                新增{dimensionLabel}
              </Button>
            </Box>
            {hasIncompleteNewPair && (
              <Typography variant="caption" color="warning.main">
                有未選完的列（單位與職位皆須選取），儲存時將略過。
              </Typography>
            )}
          </Stack>
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
        <Button variant="contained" onClick={() => onSave(paired ? completePairs() : selected)}>
          儲存
        </Button>
      </DialogActions>
    </Dialog>
  )
}
