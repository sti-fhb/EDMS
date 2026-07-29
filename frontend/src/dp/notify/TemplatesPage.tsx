import EmailIcon from "@mui/icons-material/Email"
import Alert from "@mui/material/Alert"
import Button from "@mui/material/Button"
import MenuItem from "@mui/material/MenuItem"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
import TextField from "@mui/material/TextField"
import { useMemo, useState } from "react"

import { TemplateForm } from "./TemplateForm"
import type { Channel, Template } from "./templatesService"
import { useTemplates } from "./useTemplates"
import { AppTable } from "../../components/AppTable"
import type { AppColumn } from "../../components/AppTable"
import { CrudActions } from "../../components/CrudActions"
import { CrudPageLayout } from "../../components/CrudPageLayout"

const MODULE_TABS: { module: string; label: string }[] = [
  { module: "DP", label: "系統信（共用）" },
  { module: "ET", label: "教育訓練（ET）" },
  { module: "DM", label: "文件管理（DM）" },
]

const CHANNELS: { value: Channel; label: string }[] = [
  { value: "EMAIL", label: "Email" },
  { value: "MSG", label: "系統內部" },
  { value: "BOTH", label: "系統內部+email" },
]

/**
 * 通知範本維護頁（US9 / dp-templates）。
 *
 * 依 MODULE 分頁籤（後端過濾，無管理者權限之模組無資料而不顯示頁籤；DP 系統信共用恆見）。
 * 條列範本：管道下拉、啟用/停用 行內即時儲存；「編輯」展開表單改主旨 / 內文。
 * 系統信可編主旨 / 內文但不可停用、不可移除 Email 通道；儲存採 VERSION 樂觀鎖，衝突時提示重載。
 */
export function TemplatesPage() {
  const { templates, loading, refresh, formVisible, editingRecord, saving, openEdit, closeForm, changeChannel, toggleEnabled, saveContent } =
    useTemplates()
  const [module, setModule] = useState("DP")

  const visibleTabs = useMemo(
    () => MODULE_TABS.filter((t) => templates.some((tpl) => tpl.module === t.module)),
    [templates],
  )
  const activeModule = visibleTabs.some((t) => t.module === module) ? module : (visibleTabs[0]?.module ?? "DP")
  const shown = templates.filter((t) => t.module === activeModule)

  const columns = useMemo<AppColumn<Template>[]>(
    () => [
      {
        key: "name",
        title: "範本名稱",
        render: (_v, r) => (
          <Stack direction="row" alignItems="center" spacing={1}>
            <span style={{ fontFamily: "monospace" }}>{r.template_code}</span>
            <span>{r.template_name}</span>
          </Stack>
        ),
      },
      {
        key: "channel",
        title: "管道",
        width: 220,
        render: (_v, r) => (
          <TextField
            select
            size="small"
            value={r.channel}
            onChange={(e) => changeChannel(r, e.target.value as Channel)}
            sx={{ width: 190 }}
          >
            {/* 系統信須保留 Email 通道（不可改為僅系統內部、否則等同停用），排除「系統內部」選項 */}
            {CHANNELS.filter((c) => !(r.is_system && c.value === "MSG")).map((c) => (
              <MenuItem key={c.value} value={c.value}>
                {c.label}
              </MenuItem>
            ))}
          </TextField>
        ),
      },
      {
        key: "actions",
        title: "操作",
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-start">
            {r.is_enabled ? (
              <Button
                size="small"
                color="warning"
                onClick={() => toggleEnabled(r)}
                disabled={r.is_system}
                title={r.is_system ? "系統信不可停用" : undefined}
              >
                停用
              </Button>
            ) : (
              <Button size="small" color="success" onClick={() => toggleEnabled(r)}>
                啟用
              </Button>
            )}
            <Button size="small" onClick={() => openEdit(r)}>
              編輯
            </Button>
          </Stack>
        ),
      },
    ],
    [changeChannel, toggleEnabled, openEdit],
  )

  const handleTabChange = (v: string) => {
    closeForm()
    setModule(v)
  }

  return (
    <CrudPageLayout
      icon={<EmailIcon color="primary" />}
      title="通知範本維護"
      actions={<CrudActions onRefresh={refresh} />}
      filterContent={
        <>
          <Alert severity="info" sx={{ mb: 2 }}>
            通知範本按 MODULE 過濾；DP 系統信兩管理者皆可編主旨 / 內文，但不可停用 / 刪除。事件固定，無新增 / 刪除範本。
          </Alert>
          {visibleTabs.length > 0 && (
            <Tabs value={activeModule} onChange={(_e, v: string) => handleTabChange(v)}>
              {visibleTabs.map((t) => (
                <Tab key={t.module} value={t.module} label={t.label} />
              ))}
            </Tabs>
          )}
        </>
      }
      table={
        <AppTable
          columns={columns}
          data={shown}
          rowKey="template_code"
          loading={loading}
          emptyText="目前沒有可維護的通知範本"
        />
      }
      form={
        formVisible &&
        editingRecord && (
          <TemplateForm
            key={`${editingRecord.module}.${editingRecord.template_code}.${editingRecord.version}`}
            editingRecord={editingRecord}
            saving={saving}
            onSave={(content) => saveContent(editingRecord, content)}
            onCancel={closeForm}
          />
        )
      }
    />
  )
}
