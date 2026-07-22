/** 所有 TanStack Query 的 query key 統一管理。新增模組時於此補對應群組。 */
export const QUERY_KEYS = {
  auth: {
    moduleSummary: () => ["auth", "module-summary"] as const,
  },
  users: {
    list: (params: Record<string, unknown>) => ["users", "list", params] as const,
  },
} as const
