import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { toApiError } from "../../services/http"
import { controlledApi } from "./paramsService"
import type { ControlledSection } from "./paramsService"

const _SAVED_MSG = "已儲存並即時生效"

/** 受影響數提示用「至少」：在途草稿之版本層標籤快照未計入（#388），此數字為下限。 */
function affectedText(docs: number | null, viewers: number | null): string | null {
  if (docs === null && viewers === null) return null
  return `已停用，至少影響 ${docs ?? 0} 份文件、${viewers ?? 0} 位閱覽者`
}

/**
 * 模組受控清單維護（#182）。與 `useParams`（DP_PARAM）分開：兩者資料源與鎖定語意不同，
 * 合成單一 hook 會讓每個操作都要先判斷「這是哪一種」。頁面同時使用兩者、在呈現層合併。
 */
export function useControlled() {
  const { message, confirm } = useNotification()
  const qc = useQueryClient()

  const { data, isPending } = useQuery({
    queryKey: QUERY_KEYS.params.controlled(),
    queryFn: controlledApi.list,
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: QUERY_KEYS.params.controlled() })
  }, [qc])

  /** 新增受控項；`requires_code=false` 之分區由後端／模組決定代碼，前端不送。 */
  const addControlled = useCallback(
    async (section: ControlledSection, name: string, code?: string) => {
      try {
        // 有子分組者（DM 標籤）之 code 即所屬標籤組，由分區帶入而非使用者輸入
        const payload = code ? { code, name } : section.group_code ? { code: section.group_code, name } : { name }
        await controlledApi.create(section.module, section.kind, payload)
        message.success(_SAVED_MSG)
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
        throw err
      }
    },
    [message, invalidate],
  )

  const renameControlled = useCallback(
    async (section: ControlledSection, code: string, name: string) => {
      try {
        await controlledApi.rename(section.module, section.kind, code, name)
        message.success(_SAVED_MSG)
        invalidate()
      } catch (err) {
        message.error(toApiError(err).errorMessage)
        throw err
      }
    },
    [message, invalidate],
  )

  /** 啟停受控項；停用可見對象時後端回受影響數，據此提示（下限，故用「至少」）。 */
  const toggleControlled = useCallback(
    async (section: ControlledSection, code: string, enabled: boolean) => {
      const apply = async () => {
        try {
          const result = await controlledApi.setEnabled(section.module, section.kind, code, enabled)
          message.success(enabled ? _SAVED_MSG : (affectedText(result.affected_docs, result.affected_viewers) ?? _SAVED_MSG))
          invalidate()
        } catch (err) {
          message.error(toApiError(err).errorMessage)
        }
      }
      if (!enabled) {
        confirm({
          title: "停用項目",
          content: "停用後不可再用於新資料，既有引用保留不受影響。確定停用？",
          okText: "確定停用",
          onOk: apply,
        })
        return
      }
      await apply()
    },
    [message, confirm, invalidate],
  )

  return {
    sections: data ?? [],
    loading: isPending,
    addControlled,
    renameControlled,
    toggleControlled,
  }
}
