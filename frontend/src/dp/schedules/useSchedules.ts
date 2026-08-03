import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { useNotification } from "../../contexts/NotificationContext"
import { useCrudForm } from "../../hooks/useCrudForm"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { toApiError } from "../../services/http"
import { schedulesApi } from "./schedulesService"
import type { ScheduleRow, ScheduleUpdatePayload } from "./schedulesService"

const DEFAULT_LIMIT = 20

/** 排程總覽頁狀態：job 清單（非分頁）+ 展開某 job 之執行歷程（後端分頁）+ 編輯（name/cron/啟停）。 */
export function useSchedules() {
  const { message } = useNotification()
  const queryClient = useQueryClient()
  const { formVisible, editingRecord, saving, setSaving, openEdit, closeForm } = useCrudForm<ScheduleRow>()

  const { data: jobs, isPending: jobsLoading } = useQuery({
    queryKey: QUERY_KEYS.schedule.list(),
    queryFn: schedulesApi.list,
  })

  const handleSave = useCallback(
    async (jobId: string, payload: ScheduleUpdatePayload) => {
      setSaving(true)
      try {
        await schedulesApi.update(jobId, payload)
        message.success("排程已更新")
        closeForm()
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.schedule.list() })
      } catch (err) {
        message.error(toApiError(err).errorMessage)
      } finally {
        setSaving(false)
      }
    },
    [message, closeForm, queryClient, setSaving],
  )

  // 目前展開檢視歷程的 job（null＝未展開）
  const [selectedJob, setSelectedJob] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const openLogs = useCallback((jobId: string) => {
    setSelectedJob(jobId)
    setPage(1)
  }, [])
  const closeLogs = useCallback(() => setSelectedJob(null), [])

  const { data: logsData, isPending: logsLoading } = usePagedQuery(
    QUERY_KEYS.schedule.logs({ job: selectedJob, page }),
    () => schedulesApi.logs(selectedJob as string, { page, limit: DEFAULT_LIMIT }),
    { enabled: selectedJob !== null },
  )

  return {
    jobs: jobs ?? [],
    jobsLoading,
    selectedJob,
    openLogs,
    closeLogs,
    logs: logsData?.data ?? [],
    logsTotal: logsData?.meta?.total ?? 0,
    logsLoading,
    page,
    setPage,
    limit: DEFAULT_LIMIT,
    // 編輯
    formVisible,
    editingRecord,
    saving,
    openEdit,
    closeForm,
    handleSave,
  }
}
