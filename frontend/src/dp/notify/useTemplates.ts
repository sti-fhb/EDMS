import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

import { templatesApi } from "./templatesService"
import type { Channel, Template, TemplateUpdatePayload } from "./templatesService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { useCrudForm } from "../../hooks/useCrudForm"
import { toApiError } from "../../services/http"

const _SAVED_MSG = "範本已更新"

/** 通知範本維護頁狀態與操作（查詢 / 行內改管道啟停 / 編輯主旨內文；含樂觀鎖衝突處理）。 */
export function useTemplates() {
  const { message } = useNotification()
  const qc = useQueryClient()
  const { formVisible, editingRecord, saving, setSaving, openEdit, closeForm } = useCrudForm<Template>()

  const { data, isPending } = useQuery({
    queryKey: QUERY_KEYS.templates.list(),
    queryFn: templatesApi.list,
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: QUERY_KEYS.templates.list() })
  }, [qc])

  /** 統一儲存：以範本現值 + patch 組完整 payload（含 version 樂觀鎖）送出。衝突（409）提示並重載。 */
  const save = useCallback(
    async (t: Template, patch: Partial<TemplateUpdatePayload>): Promise<boolean> => {
      const payload: TemplateUpdatePayload = {
        subject: t.subject,
        body: t.body,
        channel: t.channel,
        is_enabled: t.is_enabled,
        version: t.version,
        ...patch,
      }
      try {
        await templatesApi.update(t.module, t.template_code, payload)
        message.success(_SAVED_MSG)
        invalidate()
        return true
      } catch (err) {
        const apiErr = toApiError(err)
        message.error(apiErr.errorMessage)
        if (apiErr.errorCode === "DP_MAIL_004") invalidate() // 版本衝突 → 重載取最新版本
        return false
      }
    },
    [message, invalidate],
  )

  /** 行內改管道（即時儲存）。 */
  const changeChannel = useCallback((t: Template, channel: Channel) => save(t, { channel }), [save])

  /** 行內啟用 / 停用（即時儲存；系統信由後端擋 + 前端 disable）。 */
  const toggleEnabled = useCallback((t: Template) => save(t, { is_enabled: !t.is_enabled }), [save])

  /** 編輯表單儲存（主旨 / 內文）；成功後收起表單。 */
  const saveContent = useCallback(
    async (t: Template, content: { subject: string; body: string }) => {
      setSaving(true)
      try {
        if (await save(t, content)) closeForm()
      } finally {
        setSaving(false)
      }
    },
    [save, setSaving, closeForm],
  )

  return {
    templates: data ?? [],
    loading: isPending,
    refresh: invalidate,
    formVisible,
    editingRecord,
    saving,
    openEdit,
    closeForm,
    changeChannel,
    toggleEnabled,
    saveContent,
  }
}
