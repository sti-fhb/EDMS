import EmailIcon from "@mui/icons-material/Email"
import Button from "@mui/material/Button"
import Stack from "@mui/material/Stack"
import Tab from "@mui/material/Tab"
import Tabs from "@mui/material/Tabs"
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
  const { templates, loading, refresh, formVisible, editingRecord, saving, openEdit, closeForm, toggleEnabled, saveContent } =
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
      // 只顯示中文名稱；範本代碼為技術識別碼，不對維護者呈現（#112）
      { key: "name", title: "範本名稱", dataIndex: "template_name" },
      {
        key: "channel",
        title: "管道",
        width: 220,
        // #307：唯讀。管道與「實際怎麼送 / 怎麼呈現」的對應寫在程式裡、非資料驅動——改成
        // 系統內部會讓通知靜默消失（不寄信，也不會因此多出畫面呈現），改成 Email 則會把為
        // 站內訊息佇列準備的內容當信寄出。仍顯示現值：管理者需能回答「這則通知走 Email 還是
        // 靠畫面呈現」。後端另以 DP_MAIL_009 擋（權限邊界在後端，此處只是不給入口）。
        render: (_v, r) => <span>{CHANNELS.find((c) => c.value === r.channel)?.label ?? r.channel}</span>,
      },
      {
        key: "actions",
        title: "操作",
        width: 150,
        render: (_v, r) => (
          <Stack direction="row" spacing={1} justifyContent="flex-end">
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
    [toggleEnabled, openEdit],
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
        visibleTabs.length > 0 && (
          <Tabs value={activeModule} onChange={(_e, v: string) => handleTabChange(v)}>
            {visibleTabs.map((t) => (
              <Tab key={t.module} value={t.module} label={t.label} />
            ))}
          </Tabs>
        )
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
