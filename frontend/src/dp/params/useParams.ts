import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { paramsApi } from "./paramsService"
import type { DetailCreatePayload, DetailUpdatePayload, ParamMaster } from "./paramsService"

const _SAVED_MSG = "已儲存並即時生效"
const _PLATFORM_WARN = "此為平台級參數，變更將影響全平台（ET 與 DM）。確定儲存？"

/** 系統參數維護頁狀態與操作（查詢 / 改值改名 / 清單項新增啟停）。 */
export function useParams() {
  const { message, confirm } = useNotification()
  const qc = useQueryClient()

  const { data, isPending } = useQuery({
    queryKey: QUERY_KEYS.params.list(),
    queryFn: paramsApi.list,
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: QUERY_KEYS.params.list() })
  }, [qc])

  /** 更新明細（改值 / 改名 / 說明）；平台級先跳影響全平台警告（PARAMS-005）後才送出。
   * onCancel：平台級警告被取消時回呼（供頁面還原未儲存的欄位）。 */
  const saveDetail = useCallback(
    async (master: ParamMaster, paramKey: string, payload: DetailUpdatePayload, onCancel?: () => void) => {
      const doSave = async () => {
        try {
          await paramsApi.updateDetail(master.param_id, paramKey, payload)
          message.success(_SAVED_MSG)
          invalidate()
        } catch (err) {
          message.error(toApiError(err).errorMessage)
          throw err // rethrow：讓 confirm 對話框保留供重試
        }
      }
      if (master.scope === "platform") {
        confirm({ title: "變更平台級參數", content: _PLATFORM_WARN, okText: "確定儲存", onOk: doSave, onCancel })
      } else {
        await doSave()
      }
    },
    [message, confirm, invalidate],
  )

  /** 啟用 / 停用清單項（不走警告，直接生效）。 */
  const toggleItem = useCallback(
    async (master: ParamMaster, paramKey: string, isEnabled: boolean) => {
      try {
        await paramsApi.updateDetail(master.param_id, paramKey, { is_enabled: isEnabled })
        message.success(_SAVED_MSG)
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      }
    },
    [message, invalidate],
  )

  /** 新增清單項（僅 LIST 型、非鎖定）。 */
  const addItem = useCallback(
    async (master: ParamMaster, payload: DetailCreatePayload) => {
      try {
        await paramsApi.createDetail(master.param_id, payload)
        message.success(_SAVED_MSG)
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
        throw err
      }
    },
    [message, invalidate],
  )

  return {
    masters: data ?? [],
    loading: isPending,
    saveDetail,
    toggleItem,
    addItem,
  }
}