import TuneIcon from "@mui/icons-material/Tune"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import { useMemo, useState } from "react"

import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudPageLayout } from "../../components/CrudPageLayout"
import { useCrudForm } from "../../hooks/useCrudForm"
import { ParamEditPanel } from "./ParamEditPanel"
import type { ParamRow } from "./ParamEditPanel"
import { useParams } from "./useParams"
import type { ParamMaster } from "./paramsService"

type Scope = ParamMaster["scope"]

const SCOPE_TABS: { scope: Scope; label: string }[] = [
  { scope: "platform", label: "平台（共用）" },
  { scope: "ET", label: "教育訓練（ET）" },
  { scope: "DM", label: "文件管理（DM）" },
]

/**
 * 系統參數與清單維護頁（US5 / dp-params）。
 *
 * 依操作者身分分平台 / ET / DM 頁籤（後端前綴過濾，無權者該前綴無資料而不顯示頁籤）。
 * 條列式：VALUE 型每個明細各一列、LIST 型整組一列；右側「編輯」展開編輯面板（#99 對齊使用者管理）。
 */
export function ParamsPage() {
  const { masters, loading, saveDetail, toggleItem, addItem } = useParams()
  const [scope, setScope] = useState<Scope>("platform")
  const { formVisible, editingRecord, openEdit, closeForm } = useCrudForm<ParamRow>()

  // 僅顯示「有資料」的頁籤（模組級無管理者權限時後端不回該前綴 → 不顯示該頁籤）
  const visibleTabs = useMemo(() => SCOPE_TABS.filter((t) => masters.some((m) => m.scope === t.scope)), [masters])
  const activeScope = visibleTabs.some((t) => t.scope === scope) ? scope : (visibleTabs[0]?.scope ?? "platform")
  const shown = useMemo(() => masters.filter((m) => m.scope === activeScope), [masters, activeScope])

  // 條列：VALUE 型每明細一列；LIST 型整組一列（展開管理項目）
  const rows = useMemo<ParamRow[]>(
    () =>
      shown.flatMap((m): ParamRow[] =>
        m.param_type === "LIST"
          ? [{ rowKey: m.param_id, kind: "list", master: m }]
          : m.details.map((d) => ({ rowKey: `${m.param_id}:${d.param_key}`, kind: "value", master: m, detail: d })),
      ),
    [shown],
  )

  // 由最新 masters 重新推導編輯中的列，避免 LIST 新增 / 啟停後 editingRecord 快照過期
  const liveRow = useMemo<ParamRow | null>(() => {
    if (!editingRecord) return null
    const m = masters.find((mm) => mm.param_id === editingRecord.master.param_id)
    if (!m) return null
    if (editingRecord.kind === "list") return { rowKey: m.param_id, kind: "list", master: m }
    const d = m.details.find((dd) => dd.param_key === editingRecord.detail.param_key)
    return d ? { rowKey: `${m.param_id}:${d.param_key}`, kind: "value", master: m, detail: d } : null
  }, [editingRecord, masters])

  const columns = useMemo<AppColumn<ParamRow>[]>(
    () => [
      {
        key: "code",
        title: "參數代碼",
        render: (_v, r) => (
          <span style={{ fontFamily: "monospace" }}>{r.kind === "value" ? r.detail.param_key : r.master.param_id}</span>
        ),
      },
      { key: "name", title: "中文名稱", render: (_v, r) => (r.kind === "value" ? r.detail.param_name : r.master.param_name) },
      {
        key: "value",
        title: "參數值",
        render: (_v, r) => (r.kind === "value" ? (r.detail.param_value ?? "—") : `${r.master.details.length} 項`),
      },
      {
        key: "desc",
        title: "說明",
        render: (_v, r) => (r.kind === "value" ? (r.detail.description ?? "—") : (r.master.description ?? "—")),
      },
      {
        key: "actions",
        title: "操作",
        align: "right",
        render: (_v, r) => (
          <Button size="small" onClick={() => openEdit(r)}>
            編輯
          </Button>
        ),
      },
    ],
    [openEdit],
  )

  return (
    <CrudPageLayout
      icon={<TuneIcon color="primary" />}
      title="系統參數與清單維護"
      filterContent={
        !loading &&
        visibleTabs.length > 0 && (
          <>
            <Tabs
              value={activeScope}
              onChange={(_e, v: Scope) => {
                setScope(v)
                closeForm()
              }}
              sx={{ mb: activeScope === "platform" ? 2 : 0, borderBottom: 1, borderColor: "divider" }}
            >
              {visibleTabs.map((t) => (
                <Tab key={t.scope} value={t.scope} label={t.label} />
              ))}
            </Tabs>
            {activeScope === "platform" && (
              <Alert severity="warning">平台級參數變更將影響全平台（ET 與 DM），儲存前會再次確認。</Alert>
            )}
          </>
        )
      }
      table={
        loading ? (
          <Stack alignItems="center" sx={{ py: 6 }}>
            <CircularProgress aria-label="載入中" />
          </Stack>
        ) : visibleTabs.length === 0 ? (
          <Alert severity="info" sx={{ m: 2 }}>
            目前沒有可維護的參數。
          </Alert>
        ) : (
          <AppTable columns={columns} data={rows} rowKey="rowKey" emptyText="目前沒有可維護的參數" />
        )
      }
      form={
        formVisible &&
        liveRow && (
          <ParamEditPanel
            key={liveRow.rowKey}
            row={liveRow}
            onSaveDetail={saveDetail}
            onToggle={toggleItem}
            onAdd={addItem}
            onClose={closeForm}
          />
        )
      }
    />
  )
}
