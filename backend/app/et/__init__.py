"""教育訓練文件管理模組（ET）。

與平台 DP 共用 `DP_USER`（僅以 USER_ID 邏輯引用、不自建帳號表），參數 / 通知範本 /
發信 / 排程一律經平台集中設施（`app/services` 之 ParamService / NotifyService /
AuditLogService）。跨模組邊界見 `.claude/rules/sti-backend-boundaries.md`。
"""
