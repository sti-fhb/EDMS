import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown"
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import IconButton from "@mui/material/IconButton"
import LinearProgress from "@mui/material/LinearProgress"
import MenuItem from "@mui/material/MenuItem"
import Paper from "@mui/material/Paper"
import Table from "@mui/material/Table"
import TableBody from "@mui/material/TableBody"
import TableCell from "@mui/material/TableCell"
import TableHead from "@mui/material/TableHead"
import TableRow from "@mui/material/TableRow"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { Fragment, useEffect, useState } from "react"

import { downloadKpiCsv } from "./kpiService"
import { EMPTY_KPI_FILTERS } from "./schemas"
import type { KpiDocItem, KpiFilters, KpiTrainingDoc } from "./schemas"
import { useKpiSearch } from "./useKpi"
import { useDmAdminAccess } from "../access/useDmAdminAccess"
import { useCategoryOptions } from "../library/useLibrary"
import { Pagination } from "../../components/Pagination"
import { ScreenHeader } from "../../components/ScreenHeader"
import { useNotification } from "../../contexts/NotificationContext"

const PAGE_SIZE = 20

/** 閱讀率顯示（0~1 → 百分比字串；null＝應看=0）。 */
function ratePct(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`
}

/** 閱讀率欄：null（無對應閱覽者）給文字、其餘給進度條。文件列與分組列共用。 */
function RateCell({ rate }: { rate: number | null }) {
  if (rate === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        —（無對應閱覽者）
      </Typography>
    )
  }
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <LinearProgress variant="determinate" value={rate * 100} sx={{ flexGrow: 1, height: 8, borderRadius: 1 }} />
      <Typography variant="caption" sx={{ minWidth: 44, textAlign: "right" }}>
        {ratePct(rate)}
      </Typography>
    </Box>
  )
}

/**
 * 展開後的逐可見對象組明細（#567 A）。
 *
 * 末列的說明**只在分組加總真的大於文件總計時出現**。各組獨立計算完成度、身兼多組者每組
 * 分母都含他，而文件總計去重——這兩個數字對不起來時必須解釋，否則看的人會判定成算錯；
 * 但身兼多組是少數例外，**無條件顯示反而讓常態多出一句說明一件沒發生的事**，而且會印出
 * 「加總（2）可能大於本文件應看（2）」這種自我矛盾的句子（裁示 2026-10-08）。
 */
function AudienceGroupRows({ doc }: { doc: KpiDocItem }) {
  const groupSum = doc.groups.reduce((n, g) => n + g.should_see, 0)
  // 只在**真的對不起來時**才解釋。原本無條件顯示，於是絕大多數情況下出現「加總（2）可能
  // 大於本文件應看（2）」這種自己打臉的句子——兩個數字相同卻說「可能大於」，讀者只會更困惑。
  // 身兼多組是少數例外（裁示 2026-10-08），常態不該為例外付出版面與雜訊。
  const hasOverlap = groupSum > doc.should_see
  // 在 JS 組好單一字串，不在 JSX 跨行插值：後者會切成多個 text node，使 getByText
  // 永遠找不到它——而「找不到」在否定式斷言下是恆真的，守門會靜默失效。
  const overlapNote =
    `分組「應看」加總為 ${groupSum}，大於本文件應看 ${doc.should_see}：` +
    `有人同時符合多組，各組分母都計入他，文件總計則已去重。`
  return (
    <>
      {doc.groups.map((g, idx) => (
        // key 不用 label：標籤名由 DP 後台自由輸入、無字元限制，職位叫「松山．護理師」時
        // 會與單位「松山」＋職位「護理師」的組名逐字相同而撞 key。本清單由後端依組名排序、
        // 不可拖拉也不會插入，故索引是穩定鍵。
        <TableRow key={`${doc.doc_id}-${idx}`} sx={{ backgroundColor: "action.hover" }}>
          <TableCell />
          <TableCell colSpan={3} sx={{ pl: 3 }}>
            <Typography variant="body2">{g.label}</Typography>
          </TableCell>
          <TableCell align="right">{g.should_see}</TableCell>
          <TableCell align="right">{g.seen}</TableCell>
          <TableCell align="right">{g.unseen}</TableCell>
          <TableCell>
            <RateCell rate={g.rate} />
          </TableCell>
        </TableRow>
      ))}
      {hasOverlap && (
        <TableRow sx={{ backgroundColor: "action.hover" }}>
          <TableCell />
          <TableCell colSpan={7} sx={{ pl: 3, pt: 0 }}>
            <Typography variant="caption" color="text.secondary">
              {overlapNote}
            </Typography>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

/**
 * 訓練教材區（#567 B）——**刻意不顯示任何閱讀統計**。
 *
 * ET 代學員取檔不寫 `DM_DOC_READ`（後端 `app/et/common/dm_client.py` D-2），於此計算閱讀率
 * 會固定低報：一份全班都在 ET 讀完的教材在這裡仍是 0%。說明文字要留在畫面上，否則下一個人
 * 會以為是漏做而把統計補回來。
 */
function TrainingSection({ docs, total }: { docs: KpiTrainingDoc[]; total: number }) {
  if (total === 0) return null
  return (
    <Paper sx={{ p: 2, mt: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        訓練教材（共 {total} 份）
      </Typography>
      <Alert severity="info" sx={{ mb: 1.5 }}>
        本類文件之閱讀由教育訓練模組追蹤——學員於教育訓練閱讀教材時不寫入 DM 閱讀統計，於此計算閱讀率會固定低報，故不呈現。
      </Alert>
      <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: "60%" }}>文件</TableCell>
            <TableCell sx={{ width: "25%" }}>分類</TableCell>
            <TableCell sx={{ width: "15%" }}>目前版本</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {docs.map((d) => (
            <TableRow key={d.doc_id}>
              <TableCell>
                {d.doc_name}
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                  {d.doc_id}
                </Typography>
              </TableCell>
              <TableCell>{d.category_name ?? "訓練教材"}</TableCell>
              <TableCell>{d.current_version_no ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {docs.length < total && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          僅顯示前 {docs.length} 份，請以關鍵字縮小範圍（本區僅訓練教材一種分類，改分類無法縮小）。
        </Typography>
      )}
    </Paper>
  )
}

/**
 * 閱讀統計 KPI（US13 / DM06，管理者）：逐文件應看/已看/未看/閱讀率，依關鍵字（文件名）/ 分類**即時**
 * 查詢；頂部統計卡（整體平均閱讀率 / 閱讀率<50% 文件數）；可匯出 CSV。入口與後端皆限 DM_ADMIN。
 */
export function DmKpiPage() {
  const { message } = useNotification()
  const [filters, setFilters] = useState<KpiFilters>(EMPTY_KPI_FILTERS)
  const [applied, setApplied] = useState<KpiFilters>(EMPTY_KPI_FILTERS)
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)
  // 展開中的文件（逐可見對象組明細）。收合時版面與加此功能之前完全相同。
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())

  const toggleExpanded = (docId: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (!next.delete(docId)) next.add(docId)
      return next
    })

  // 先以 admin-access 判權限：非管理者不渲染查詢 UI、清單查詢僅在具管理者權限時才發（避免先閃搜尋列再跳無權限）。
  const { data: access, isPending: accessPending, isError: accessError } = useDmAdminAccess()
  const canAccess = access?.can_access ?? false
  const { data: categoryOptions } = useCategoryOptions(canAccess)
  const denied = accessError || access?.can_access === false
  const { data, isPending, isError } = useKpiSearch({ ...applied, page, limit: PAGE_SIZE }, { enabled: canAccess })

  // 即時篩選：任一條件異動即防抖套用查詢並回第一頁，無「查詢」按鈕
  useEffect(() => {
    const timer = setTimeout(() => {
      setApplied(filters)
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [filters])

  const setField = (key: keyof KpiFilters, value: string) => setFilters((prev) => ({ ...prev, [key]: value }))

  const onExport = async () => {
    setExporting(true)
    try {
      await downloadKpiCsv(applied)
    } catch {
      message.error("匯出失敗，請稍後再試")
    } finally {
      setExporting(false)
    }
  }

  const rows = data?.data ?? []
  const summary = data?.summary
  const trainingDocs = data?.training_docs ?? []
  const trainingTotal = data?.training_total ?? 0
  // 命中的全是訓練教材（主區空、下區有資料）→ 統計卡與文件統計整組不顯示。
  // 此時統計必然是空的：訓練教材依設計不進統計母體（#567 B），再顯示「— ／共 0 份可計算文件」
  // 與「查無符合條件之文件統計」只是噪音，還會讓人以為查詢壞了。
  // 用資料推導而非比對 category === "TRAINING"：不必在前端複製後端的分類常數，
  // 且關鍵字剛好只命中教材時同樣適用。
  const onlyTraining = (data?.meta.total ?? 0) === 0 && trainingTotal > 0

  // 無權限（非管理者 / 非 DM 角色）：僅顯示標題 + 錯誤訊息，不渲染查詢 UI（DM-MSG-DM06-002）
  if (denied) {
    return (
      <Box>
        <ScreenHeader code="DM06" />
        <Alert severity="error">您無權限存取此頁面</Alert>
      </Box>
    )
  }

  // 權限確認中：僅顯示標題 + spinner，不先閃查詢 UI
  if (accessPending) {
    return (
      <Box>
        <ScreenHeader code="DM06" />
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      </Box>
    )
  }

  return (
    <Box>
      <ScreenHeader code="DM06" />

      {/* 統計卡 + 文件統計：命中的全是訓練教材時整組不顯示（見 onlyTraining） */}
      {!onlyTraining && (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2, mb: 2 }}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="caption" color="text.secondary">
              整體平均閱讀率
            </Typography>
            <Typography variant="h4">{summary ? ratePct(summary.overall_rate) : "—"}</Typography>
          </Paper>
          <Paper sx={{ p: 2 }}>
            <Typography variant="caption" color="text.secondary">
              閱讀率低於 50% 之文件數
            </Typography>
            <Box sx={{ display: "flex", alignItems: "baseline", gap: 1 }}>
              <Typography variant="h4">{summary?.below_50_count ?? 0}</Typography>
              {/* 分母用 rated_docs 而非 total_docs：分子只計可算閱讀率者（排除應看=0），
                  兩者並列時母體必須相同，否則讀者會以為是「10 份裡有 2 份不及格」（#567 C）。*/}
              <Typography variant="body2" color="text.secondary">
                ／ 共 {summary?.rated_docs ?? 0} 份可計算文件
              </Typography>
            </Box>
          </Paper>
        </Box>
      )}

      {/* 搜尋列（即時篩選，無查詢按鈕）*/}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" }, gap: 1.5 }}>
          <TextField
            size="small"
            label="關鍵字（文件名）"
            value={filters.keyword}
            onChange={(e) => setField("keyword", e.target.value)}
          />
          <TextField
            size="small"
            select
            label="分類"
            value={filters.category}
            onChange={(e) => setField("category", e.target.value)}
          >
            <MenuItem value="">全部</MenuItem>
            {(categoryOptions ?? []).map((c) => (
              <MenuItem key={c.code} value={c.code}>
                {c.name}
              </MenuItem>
            ))}
          </TextField>
        </Box>
      </Paper>

      {/* 結果 */}
      {!onlyTraining && (
        <Paper sx={{ p: 2 }}>
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
            <Typography variant="subtitle2">文件統計{data ? `（共 ${data.meta.total} 筆）` : ""}</Typography>
            <Button
              size="small"
              variant="outlined"
              disabled={exporting || (data?.meta.total ?? 0) === 0}
              onClick={onExport}
            >
              匯出 CSV
            </Button>
          </Box>

          {isPending ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
              <CircularProgress size={28} />
            </Box>
          ) : isError ? (
            <Alert severity="error">載入失敗，請稍後再試。</Alert>
          ) : rows.length === 0 ? (
            <Alert severity="info">查無符合條件之文件統計</Alert>
          ) : (
            <>
              <Table size="small" sx={{ tableLayout: "fixed", width: "100%" }}>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: "4%" }} />
                    <TableCell sx={{ width: "28%" }}>文件</TableCell>
                    <TableCell sx={{ width: "11%" }}>分類</TableCell>
                    <TableCell sx={{ width: "9%" }}>目前版本</TableCell>
                    <TableCell sx={{ width: "8%" }} align="right">
                      應看
                    </TableCell>
                    <TableCell sx={{ width: "8%" }} align="right">
                      已看
                    </TableCell>
                    <TableCell sx={{ width: "8%" }} align="right">
                      未看
                    </TableCell>
                    <TableCell sx={{ width: "24%" }}>閱讀率</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => {
                    const isOpen = expanded.has(row.doc_id)
                    return (
                      <Fragment key={row.doc_id}>
                        <TableRow>
                          <TableCell sx={{ pr: 0 }}>
                            {row.groups.length > 0 && (
                              <IconButton
                                size="small"
                                aria-label={isOpen ? `收合 ${row.doc_name} 的可見對象` : `展開 ${row.doc_name} 的可見對象`}
                                onClick={() => toggleExpanded(row.doc_id)}
                              >
                                {isOpen ? (
                                  <KeyboardArrowDownIcon fontSize="small" />
                                ) : (
                                  <KeyboardArrowRightIcon fontSize="small" />
                                )}
                              </IconButton>
                            )}
                          </TableCell>
                          <TableCell>
                            {row.doc_name}
                            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                              {row.doc_id}
                            </Typography>
                          </TableCell>
                          <TableCell>{row.category_name ?? row.category_code}</TableCell>
                          <TableCell>{row.current_version_no ?? "—"}</TableCell>
                          <TableCell align="right">{row.should_see}</TableCell>
                          <TableCell align="right">{row.seen}</TableCell>
                          <TableCell align="right">{row.unseen}</TableCell>
                          <TableCell>
                            <RateCell rate={row.rate} />
                          </TableCell>
                        </TableRow>
                        {isOpen && <AudienceGroupRows doc={row} />}
                      </Fragment>
                    )
                  })}
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
      )}

      {/* 訓練教材另成一區：不計閱讀率，理由見 TrainingSection docstring */}
      <TrainingSection docs={trainingDocs} total={trainingTotal} />
    </Box>
  )
}
