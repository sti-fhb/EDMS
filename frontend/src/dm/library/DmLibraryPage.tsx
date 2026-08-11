import Alert from "@mui/material/Alert"
import Autocomplete from "@mui/material/Autocomplete"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { DM_CATEGORIES, EMPTY_LIBRARY_FILTERS, MANUAL_CATEGORY } from "./schemas"
import type { ControlledOption, LibraryFilters } from "./schemas"
import { useFuncOptions, useLibraryCapabilities, useLibrarySearch, useRetrievalTags } from "./useLibrary"
import { Pagination } from "../../components/Pagination"

const PAGE_SIZE = 20
// 檢索標籤組代碼 → 分組標題（Autocomplete groupBy）
const TAG_GROUP_LABELS: Record<string, string> = { MODULE: "適用模組", NATURE: "文件性質", LEGAL: "法規關聯" }

/**
 * 文件庫與檢索（US3 / DM01）：多條件搜尋已發布目前版本（含廢止待簽核）→ 點列進詳細頁。
 * 分類選「系統操作手冊」時額外顯示 func_name 下拉；閱覽者結果由後端套標籤式可見性；
 * 具編輯者角色者見「新增文件」入口。檢索標籤僅列檢索組（不含可見對象）。
 */
export function DmLibraryPage() {
  const navigate = useNavigate()
  const [draft, setDraft] = useState<LibraryFilters>(EMPTY_LIBRARY_FILTERS)
  const [selectedTags, setSelectedTags] = useState<ControlledOption[]>([])
  const [applied, setApplied] = useState<LibraryFilters>(EMPTY_LIBRARY_FILTERS)
  const [page, setPage] = useState(1)

  const { data: capabilities } = useLibraryCapabilities()
  const { data: tagOptions } = useRetrievalTags()
  const { data: funcOptions } = useFuncOptions(draft.category === MANUAL_CATEGORY)
  const { data } = useLibrarySearch({ ...applied, page, limit: PAGE_SIZE })

  const setField = (key: keyof LibraryFilters, value: string) => setDraft((prev) => ({ ...prev, [key]: value }))

  const onCategoryChange = (value: string) => {
    // 切離「系統操作手冊」時清掉 func 條件，避免殘留過濾
    setDraft((prev) => ({ ...prev, category: value, funcCode: value === MANUAL_CATEGORY ? prev.funcCode : "" }))
  }

  const onSearch = () => {
    setApplied({ ...draft, tagIds: selectedTags.map((t) => Number(t.code)) })
    setPage(1)
  }

  const rows = data?.data ?? []

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        文件庫
      </Typography>

      {/* 搜尋列 */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr 1fr" }, gap: 1.5 }}>
          <TextField
            size="small"
            label="關鍵字（文件名 / 摘要）"
            value={draft.keyword}
            onChange={(e) => setField("keyword", e.target.value)}
          />
          <TextField
            size="small"
            select
            label="分類"
            value={draft.category}
            onChange={(e) => onCategoryChange(e.target.value)}
          >
            <MenuItem value="">全部</MenuItem>
            {DM_CATEGORIES.map((c) => (
              <MenuItem key={c.code} value={c.code}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            size="small"
            label="作者（姓名）"
            value={draft.author}
            onChange={(e) => setField("author", e.target.value)}
          />
        </Box>

        <Box sx={{ mt: 1.5 }}>
          <Autocomplete
            multiple
            size="small"
            options={tagOptions ?? []}
            value={selectedTags}
            onChange={(_, v) => setSelectedTags(v)}
            getOptionLabel={(o) => o.name}
            isOptionEqualToValue={(a, b) => a.code === b.code}
            groupBy={(o) => TAG_GROUP_LABELS[o.group_code ?? ""] ?? "標籤"}
            renderInput={(params) => <TextField {...params} label="檢索標籤（多選 AND）" />}
          />
        </Box>

        {/* 關聯作業項目（func_name）：僅「系統操作手冊」分類顯示 */}
        {draft.category === MANUAL_CATEGORY && (
          <Box sx={{ mt: 1.5 }}>
            <TextField
              size="small"
              select
              fullWidth
              label="關聯作業項目（func_name）"
              value={draft.funcCode}
              onChange={(e) => setField("funcCode", e.target.value)}
            >
              <MenuItem value="">全部</MenuItem>
              {(funcOptions ?? []).map((f) => (
                <MenuItem key={f.code} value={f.code}>
                  {f.code} — {f.name}
                </MenuItem>
              ))}
            </TextField>
          </Box>
        )}

        <Box sx={{ display: "flex", gap: 1.5, mt: 1.5, alignItems: "center", flexWrap: "wrap" }}>
          <TextField
            size="small"
            type="date"
            label="發布日期 起"
            slotProps={{ inputLabel: { shrink: true } }}
            value={draft.dateFrom}
            onChange={(e) => setField("dateFrom", e.target.value)}
          />
          <TextField
            size="small"
            type="date"
            label="發布日期 迄"
            slotProps={{ inputLabel: { shrink: true } }}
            value={draft.dateTo}
            onChange={(e) => setField("dateTo", e.target.value)}
          />
          <Button variant="contained" onClick={onSearch}>
            搜尋
          </Button>
        </Box>
        {draft.category !== MANUAL_CATEGORY && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            提示：選擇分類「系統操作手冊」以依作業項目（func_name）檢索。
          </Typography>
        )}
      </Paper>

      {/* 結果 */}
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="subtitle2">搜尋結果{data ? `（共 ${data.meta.total} 筆）` : ""}</Typography>
          {capabilities?.can_create && (
            // 新增文件入口：僅編輯者可見（後端 can_create）；US5 提供新增模式路由
            <Button size="small" variant="outlined" onClick={() => navigate("/dm/documents/new")}>
              新增文件
            </Button>
          )}
        </Box>

        {rows.length === 0 ? (
          <Alert severity="info">查無符合條件之文件。</Alert>
        ) : (
          <>
            <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ width: "34%" }}>文件名稱</TableCell>
                  <TableCell sx={{ width: "14%" }}>分類</TableCell>
                  <TableCell sx={{ width: "12%" }}>發布日期</TableCell>
                  <TableCell sx={{ width: "12%" }}>作者</TableCell>
                  <TableCell sx={{ width: "28%" }}>標籤</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.doc_id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(`/dm/documents/${row.doc_id}`)}
                  >
                    <TableCell>
                      {row.doc_name}
                      {row.func_code && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                          {row.func_code} — {row.func_name}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip size="small" label={row.category_name} />
                    </TableCell>
                    <TableCell>{row.published_date?.slice(0, 10) ?? "—"}</TableCell>
                    <TableCell>{row.author_name ?? row.author_id}</TableCell>
                    <TableCell>
                      {/* 標籤：灰色文字頓號分隔（非彩色 pill，FR-003）；僅檢索標籤 */}
                      <Typography variant="caption" color="text.secondary">
                        {row.tags.length > 0 ? row.tags.join("、") : "—"}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data && (
              <Box sx={{ mt: 2 }}>
                <Pagination
                  page={data.meta.page}
                  total={data.meta.total}
                  pageSize={data.meta.limit}
                  onPageChange={setPage}
                />
              </Box>
            )}
          </>
        )}
      </Paper>
    </Box>
  )
}