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
  const { message, confirm } = useNotification()
  const queryClient = useQueryClient()
  const { formVisible, editingRecord, saving, setSaving, openEdit, closeForm } = useCrudForm<ScheduleRow>()

  const { data: jobs, isPending: jobsLoading } = useQuery({
    queryKey: QUERY_KEYS.schedule.list(),
    queryFn: schedulesApi.list,
  })

  /** 先跳二次確認（#112）：cron / 啟停變更會即時套到運行中的引擎，確認後才送出。 */
  const handleSave = useCallback(
    async (jobId: string, payload: ScheduleUpdatePayload) => {
      confirm({
        title: "儲存排程變更",
        content: `確定儲存「${jobId}」的變更？cron 與啟停將即時套用至排程引擎。`,
        okText: "確定儲存",
        onOk: async () => {
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
      })
    },
    [message, closeForm, queryClient, setSaving, confirm],
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
