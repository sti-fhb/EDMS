import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

import { templatesApi } from "./templatesService"
import type { TemplateUpdatePayload } from "./templatesService"
import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"

const _SAVED_MSG = "範本已更新"

/** 通知範本維護頁狀態與操作（查詢 / 編輯儲存〔含樂觀鎖衝突處理〕/ 啟停）。 */
export function useTemplates() {
  const { message } = useNotification()
  const qc = useQueryClient()

  const { data, isPending } = useQuery({
    queryKey: QUERY_KEYS.templates.list(),
    queryFn: templatesApi.list,
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: QUERY_KEYS.templates.list() })
  }, [qc])

  /** 儲存範本編輯；版本衝突（409 DP_MAIL_004）→ 提示重新載入並重取最新版本。回傳是否成功。 */
  const saveTemplate = useCallback(
    async (module: string, code: string, payload: TemplateUpdatePayload): Promise<boolean> => {
      try {
        await templatesApi.update(module, code, payload)
        message.success(_SAVED_MSG)
        invalidate()
        return true
      } catch (err) {
        const apiErr = toApiError(err)
        message.error(apiErr.errorMessage)
        // 版本衝突 → 重載清單取最新版本，讓使用者以新版重新編輯
        if (apiErr.errorCode === "DP_MAIL_004") invalidate()
        return false
      }
    },
    [message, invalidate],
  )

  return {
    templates: data ?? [],
    loading: isPending,
    saveTemplate,
  }
}