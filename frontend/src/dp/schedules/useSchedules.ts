import { useQuery } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import { QUERY_KEYS } from "../../constants/queryKeys"
import { usePagedQuery } from "../../hooks/usePagedQuery"
import { schedulesApi } from "./schedulesService"

const DEFAULT_LIMIT = 20

/** 排程總覽頁狀態：job 清單（非分頁）+ 展開某 job 之執行歷程（後端分頁）。 */
export function useSchedules() {
  const { data: jobs, isPending: jobsLoading } = useQuery({
    queryKey: QUERY_KEYS.schedule.list(),
    queryFn: schedulesApi.list,
  })

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
  }
}
