import TuneIcon from "@mui/icons-material/Tune"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import Typography from "@mui/material/Typography"
import { useMemo, useState } from "react"

import { ParamCard } from "./ParamCard"
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
 * 版面因「頁籤 + 分組卡片」異於標準 CRUD 列表，故不套 CrudPageLayout，改採一致的標題列 + Tabs。
 */
export function ParamsPage() {
  const { masters, loading, saveValue, toggleItem, addItem } = useParams()
  const [scope, setScope] = useState<Scope>("platform")

  // 僅顯示「有資料」的頁籤（模組級無管理者權限時後端不回該前綴 → 不顯示該頁籤）
  const visibleTabs = useMemo(() => SCOPE_TABS.filter((t) => masters.some((m) => m.scope === t.scope)), [masters])
  const activeScope = visibleTabs.some((t) => t.scope === scope) ? scope : (visibleTabs[0]?.scope ?? "platform")
  const shown = masters.filter((m) => m.scope === activeScope)

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <TuneIcon color="primary" />
        <Typography variant="h5" component="h1">
          系統參數與清單維護
        </Typography>
      </Stack>

      {loading ? (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      ) : visibleTabs.length === 0 ? (
        <Alert severity="info">目前沒有可維護的參數。</Alert>
      ) : (
        <>
          <Tabs
            value={activeScope}
            onChange={(_e, v: Scope) => setScope(v)}
            sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
          >
            {visibleTabs.map((t) => (
              <Tab key={t.scope} value={t.scope} label={t.label} />
            ))}
          </Tabs>

          {activeScope === "platform" && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              平台級參數變更將影響全平台（ET 與 DM），儲存前會再次確認。
            </Alert>
          )}

          {shown.map((m) => (
            <ParamCard key={m.param_id} master={m} onSaveValue={saveValue} onToggle={toggleItem} onAdd={addItem} />
          ))}
        </>
      )}
    </Box>
  )
}
