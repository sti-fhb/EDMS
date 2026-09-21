import type { CourseListParams } from "../et/courses/schemas"

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
  etCourses: {
    capabilities: () => ["et", "courses", "capabilities"] as const,
    list: (params: CourseListParams) => ["et", "courses", "list", params] as const,
    filterTags: () => ["et", "courses", "filter-tags"] as const,
    detail: (courseId: number) => ["et", "courses", courseId] as const,
    tags: (courseId?: number) => ["et", "tags", courseId ?? null] as const,
    material: (materialId: number) => ["et", "materials", materialId] as const,
    quiz: (quizId: number) => ["et", "quizzes", quizId] as const,
    survey: (courseId: number) => ["et", "courses", courseId, "survey"] as const,
    surveyTemplates: () => ["et", "survey-templates"] as const,
    dmDocuments: () => ["et", "dm-documents"] as const,
  },
  etMyCourses: {
    list: () => ["et", "my-courses"] as const,
  },
  /** ET03 學員學習狀況追蹤（US9 / #322）——三個區塊各自的 key，切課程時一起失效。 */
  etStudents: {
    /** 整個課程的追蹤資料前綴——切換課程或寫入後以此一次失效三個區塊。 */
    all: (courseId: number) => ["et", "tracking", courseId] as const,
    list: (courseId: number, params: Record<string, unknown>) =>
      ["et", "tracking", courseId, "students", params] as const,
    attemptOverview: (courseId: number) => ["et", "tracking", courseId, "attempt-overview"] as const,
    attemptDetail: (attemptId: number) => ["et", "tracking", "attempts", attemptId] as const,
    surveyResult: (courseId: number) => ["et", "tracking", courseId, "survey-result"] as const,
  },
  /** ET10 核可查詢（US17 / #385）。兩視角分開——它們的參數與回應欄位都不同。 */
  etApprovals: {
    search: (params: Record<string, unknown>) => ["et", "approvals", "search", params] as const,
    mine: (page: number) => ["et", "approvals", "mine", page] as const,
  },
  etLearn: {
    structure: (courseId: number) => ["et", "learn", courseId] as const,
    material: (materialId: number) => ["et", "learn", "materials", materialId] as const,
  },
  etQuiz: {
    intro: (quizId: number) => ["et", "quizzes", quizId, "intro"] as const,
    attempt: (attemptId: number) => ["et", "attempts", attemptId] as const,
    result: (attemptId: number) => ["et", "attempts", attemptId, "result"] as const,
    history: (quizId: number) => ["et", "quizzes", quizId, "attempts"] as const,
  },
  etSurvey: {
    form: (courseId: number) => ["et", "survey", "form", courseId] as const,
  },
  moduleSummary: {
    get: () => ["module-summary"] as const,
  },
} as const
