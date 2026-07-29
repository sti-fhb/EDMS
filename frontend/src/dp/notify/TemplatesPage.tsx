import EmailIcon from "@mui/icons-material/Email"
import Alert from "@mui/material/Alert"
import Box from "@mui/material/Box"
import CircularProgress from "@mui/material/CircularProgress"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import Typography from "@mui/material/Typography"
import { useMemo, useState } from "react"

import { TemplateCard } from "./TemplateCard"
import { useTemplates } from "./useTemplates"

const MODULE_TABS: { module: string; label: string }[] = [
  { module: "DP", label: "系統信（共用）" },
  { module: "ET", label: "教育訓練（ET）" },
  { module: "DM", label: "文件管理（DM）" },
]

/**
 * 通知範本維護頁（US9 / dp-templates）。
 *
 * 依 MODULE 分頁籤（後端過濾，無管理者權限之模組無資料而不顯示頁籤；DP 系統信共用恆見）。
 * 系統信可編主旨 / 內文但不可停用；儲存採 VERSION 樂觀鎖，衝突時提示重載並取最新版本。
 */
export function TemplatesPage() {
  const { templates, loading, saveTemplate } = useTemplates()
  const [module, setModule] = useState("DP")

  const visibleTabs = useMemo(
    () => MODULE_TABS.filter((t) => templates.some((tpl) => tpl.module === t.module)),
    [templates],
  )
  const activeModule = visibleTabs.some((t) => t.module === module) ? module : (visibleTabs[0]?.module ?? "DP")
  const shown = templates.filter((t) => t.module === activeModule)

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <EmailIcon color="primary" />
        <Typography variant="h5" component="h1">
          通知範本維護
        </Typography>
      </Stack>

      <Alert severity="info" sx={{ mb: 2 }}>
        通知範本統一存 DP_NOTIFY_TEMPLATE，按 MODULE 過濾；DP 系統信兩管理者皆可編主旨 / 內文，但不可停用 / 刪除。事件固定，無新增 / 刪除範本。
      </Alert>

      {loading ? (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress />
        </Stack>
      ) : visibleTabs.length === 0 ? (
        <Alert severity="info">目前沒有可維護的通知範本。</Alert>
      ) : (
        <>
          <Tabs
            value={activeModule}
            onChange={(_e, v: string) => setModule(v)}
            sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
          >
            {visibleTabs.map((t) => (
              <Tab key={t.module} value={t.module} label={t.label} />
            ))}
          </Tabs>

          {shown.map((t) => (
            <TemplateCard key={`${t.module}.${t.template_code}.${t.version}`} template={t} onSave={saveTemplate} />
          ))}
        </>
      )}
    </Box>
  )
}