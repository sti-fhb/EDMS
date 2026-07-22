# 後端共用模組補充參考

> 本檔補充 `.claude/rules/sti-backend-modules.md`，記錄 BaseModel 變體用法、刪除策略例外表清單、AuditLogService 用法等隨開發逐步落地的細節。

## BaseModel 用法

各 BaseModel 變體的欄位組成見 `backend/app/core/base_model.py` 與 `sti-backend-modules.md` 的對照表。原則：

- `BaseModel`：一般業務表（含 `RES_ID` + `DELETED`），新表預設。
- `BaseModelNoResId`：`RES_ID` 已被業務欄位佔用。
- `BaseModelHardDelete`：硬刪除例外表（含 `RES_ID`，**無 `DELETED`**）——刪除即下線、不保留歷史。
- `BaseModelNoDelete`：可更新但永不刪除的 outbox / log 表（如 `DP_EMAIL_LOG`）。
- `AuditLogBaseModel`：append-only 記錄表（僅 `CREATED_*`）。

## 刪除策略例外表清單

> 預設一律**軟刪除**（`DELETED = 1`、查詢加 `WHERE DELETED = 0`）。以下為**例外**表，新增例外時於本清單登記並說明理由。

### 硬刪除例外表（`BaseModelHardDelete`，無 `DELETED`）

| Table | 模組 | 理由 |
|-------|------|------|
| `DP_PENDING_REGISTRATION` | DP | 待驗證的自助註冊（US2 #56，方案 B）。屬**暫存性**資料：驗證通過即消費（搬入 `DP_USER` 後刪列）、逾期未驗證由排程清理；一 Email 一筆（`UNIQUE(EMAIL)`），重新註冊 / 重寄以硬刪 + 重建覆蓋。若改軟刪除，`UNIQUE(EMAIL)` 需改為部分索引（`WHERE DELETED = 0`）徒增複雜度，且已消費 / 逾期的待驗證列（含密碼雜湊）無保留價值，故採硬刪除。 |

### 無 `DELETED` 但非硬刪除（`BaseModelNoDelete` / `AuditLogBaseModel`）

| Table | 基底 | 說明 |
|-------|------|------|
| `DP_EMAIL_LOG` | `BaseModelNoDelete` | 寄件 outbox，新增後只更新狀態、永不刪除。 |
| `DP_AUDIT_LOG` / `DP_PWD_HIST` / `DP_SCHEDULE_LOG` | `AuditLogBaseModel` | append-only 記錄表。 |

## AuditLogService 用法

跨模組經 `app.services.AuditLogService` 呼叫；`log_action(db, module, func_name, action_type, result, operator_id, target_id=, description=, source_ip=)`。`action_type` 用 `DP_PARAM.ACTION_TYPE` 代碼（LOGIN/LOGOUT/CREATE/UPDATE/DELETE）；停用啟用、鎖定解鎖、密碼重置等以 `func_name` + `description` 細分。自助註冊 / 驗證等無登入操作者之情境，`operator_id` 填該帳號本人 USER_ID（見 spec_us2 Clarifications）。
