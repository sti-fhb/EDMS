/** 所有 TanStack Query 的 query key 統一管理。新增模組時於此補對應群組。 */
export const QUERY_KEYS = {
  users: {
    list: (params: Record<string, unknown>) => ["users", "list", params] as const,
    invites: (params: Record<string, unknown>) => ["users", "invites", params] as const,
  },
  params: {
    list: () => ["params", "list"] as const,
  },
  templates: {
    list: () => ["templates", "list"] as const,
  },
  audit: {
    list: (params: Record<string, unknown>) => ["audit", "list", params] as const,
  },
  schedule: {
    list: () => ["schedule", "list"] as const,
    logs: (params: Record<string, unknown>) => ["schedule", "logs", params] as const,
  },
} as const
