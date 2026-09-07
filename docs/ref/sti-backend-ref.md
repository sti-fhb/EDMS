# 後端共用模組補充參考

> 本檔補充 `.claude/rules/sti-backend-modules.md`，記錄 BaseModel 變體用法、刪除策略例外表清單、AuditLogService 用法等隨開發逐步落地的細節。

## BaseModel 用法

各 BaseModel 變體的欄位組成見 `backend/app/core/base_model.py` 與 `sti-backend-modules.md` 的對照表。原則：

- `BaseModel`：一般業務表（含 `DELETED`），新表預設。
- `BaseModelHardDelete`：硬刪除例外表（**無 `DELETED`**）——刪除即下線、不保留歷史。
- `BaseModelNoDelete`：可更新但永不刪除的 outbox / log 表（如 `DP_EMAIL_LOG`）。
- `AuditLogBaseModel`：append-only 記錄表（僅 `CREATED_*`）。

> **`RES_ID` 已自標準欄位移除**（2026-08-13，#158），`BaseModelNoResId` 亦一併刪除（移除 `RES_ID` 後與 `BaseModel` 等價）。該欄源自主系統 TBMS 之「來源功能 ID」（外鍵指向功能選單表 `DP_MENU`），EDMS 不設 `DP_MENU`（無全域 RBAC / 功能選單），來源功能改記於 `DP_AUDIT_LOG.FUNC_NAME`（語意碼 `DP-USERS` / `DM-CATALOG` 等）。**新表不得加回 `RES_ID`**；需要自己的對外識別碼時以業務語意命名（如 `DP_PENDING_REGISTRATION.INVITE_ID`）。

## 刪除策略例外表清單

> 預設一律**軟刪除**（`DELETED = 1`、查詢加 `WHERE DELETED = 0`）。以下為**例外**表，新增例外時於本清單登記並說明理由。

### 硬刪除例外表（`BaseModelHardDelete`，無 `DELETED`）

| Table | 模組 | 理由 |
|-------|------|------|
| `DP_PENDING_REGISTRATION` | DP | 待驗證的自助註冊（US2 #56，方案 B）。屬**暫存性**資料：驗證通過即消費（搬入 `DP_USER` 後刪列）、逾期未驗證由排程清理；一 Email 一筆（`UNIQUE(EMAIL)`），重新註冊 / 重寄以硬刪 + 重建覆蓋。若改軟刪除，`UNIQUE(EMAIL)` 需改為部分索引（`WHERE DELETED = 0`）徒增複雜度，且已消費 / 逾期的待驗證列無保留價值，故採硬刪除。 |

**批次硬刪除（#226）**：本表是專案第一支**排程級批次硬刪除**——`UsersService.purge_expired_pending`（SCHDP001 第三批次）以單一 `DELETE` 清掉**逾期滿 1 天**的列。三項須併記的決定：

| 決定 | 理由 |
|------|------|
| 只清 `KIND=SELF_REGISTER`，**不碰 `ADMIN_INVITE`** | 逾期邀請仍是 UI 物件：「待啟用邀請」頁籤沒有效期條件，逾期者會顯示「已逾期」並可按「重寄邀請」（`spec_us4.md` AC10）。清掉會讓邀請靜默消失、`resend_invite` / `cancel_invite` 回 404、邀請的稽核鏈以無終結事件收尾。邀請由管理者以「取消邀請」主動收掉。 |
| 保留 1 天而非立即刪 | 逾期列本身已無用（token 不可用、#212 後也不含密碼），留一天讓**當天**的客服問題還查得到「這個 Email 前一天有人送過註冊」。以常數而非 `DP_PARAM`——無證據需要調整。**這不是證據保留期**（發起者追溯只記應用層 log，見 #225）。 |
| **不逐列寫稽核** | 本表**匿名可寫**（自助註冊為公開端點、30 次/分/IP），逐列寫稽核等於讓任何人往 append-only、鏈式雜湊的 `DP_AUDIT_LOG` 灌列。被清的列早已逾期、無業務意義；需要留痕的是「有人覆蓋了**別人**的列」，那由 `register_service` 與 `UsersService.create_user` 各自記一筆 `DELETE` 稽核。刪除筆數由 handler 記入 log。 |

### 保留 `DELETED` 但特定路徑硬刪除

| Table | 模組 | 硬刪除路徑 | 理由 |
|-------|------|-----------|------|
| `ET_PROGRESS_INTERVAL` | ET | `progress/repository.replace_intervals`（normalize 與累計列數超限時的就地壓縮）| 本表以「每段播放一列」記錄影片觀看區段，覆蓋率一律取**區段聯集**後計算。壓縮所刪除的是「**同一批資料的未壓縮表述**」——`[0,60]` 與 `[30,90]` 換成 `[0,90]`，資訊完全等價，不是使用者資料的作廢。留著軟刪除列會讓每次覆蓋率計算都要過濾一堆歷史雜訊（該路徑在每次暫停 / 跳轉都會執行），而那些列不帶任何 `DELETED=1` 才有的資訊。<br>本表其餘查詢仍照常過濾 `DELETED = 0`，故保留 `BaseModel` 而非改用 `BaseModelHardDelete`。<br>⚠️ **刪除範圍限定在 SELECT 快照讀到的 `INTERVAL_ID`**，不可用 `(USER_ID, VIDEO_ID)` 全量刪——後者會讓併發寫入的區段被掃掉而永久遺失（表現為學員的覆蓋率倒退、已完成的項目變回未完成）。 |

### 無 `DELETED` 但非硬刪除（`BaseModelNoDelete` / `AuditLogBaseModel`）

| Table | 基底 | 說明 |
|-------|------|------|
| `DP_EMAIL_LOG` | `BaseModelNoDelete` | 寄件 outbox，新增後只更新狀態、永不刪除。 |
| `DP_AUDIT_LOG` / `DP_PWD_HIST` / `DP_SCHEDULE_LOG` | `AuditLogBaseModel` | append-only 記錄表。 |

## AuditLogService 用法

### 明示不寫稽核的例外

| 位置 | 略過的範圍 | 理由 |
|------|-----------|------|
| `et/enrollment/service.py` | `ET_ENROLL_001`（邀請碼查無）**失敗路徑** | 該路徑是枚舉攻擊的主要面，逐次寫入會在被攻擊時灌爆稽核表。加入課程**成功**時仍照常寫稽核。 |
| `et/progress/router.py` 三個端點 | **成功寫入路徑本身** | `log_action` 以**單一固定 key** 的 `pg_advisory_xact_lock` 序列化稽核鏈，且持有至整個外層交易結束。掛在全站頻率最高的端點（每次暫停 / 跳轉 / 切換項目各一次）上，會讓**所有模組**的稽核寫入排隊等同一把鎖。學習軌跡完整保存在三張進度表與 `ET_ENROLLMENT.LAST_ACTIVITY_AT`，追溯需求由那些表滿足。 |

> 上表兩筆**性質不同、不可互相援引**：前者是防枚舉（只略過失敗路徑），後者是高頻遙測（略過成功路徑）。

跨模組經 `app.services.AuditLogService` 呼叫；`log_action(db, module, func_name, action_type, result, operator_id, target_id=, description=, source_ip=)`。`action_type` 用 `DP_PARAM.ACTION_TYPE` 代碼（LOGIN/LOGOUT/CREATE/UPDATE/DELETE）；停用啟用、鎖定解鎖、密碼重置等以 `func_name` + `description` 細分。自助註冊 / 驗證等無登入操作者之情境，`operator_id` 填該帳號本人 USER_ID（見 spec_us2 Clarifications）。

## 稽核鏈完整性（`DP_AUDIT_LOG` ROW_HASH）

`DP_AUDIT_LOG` 為 append-only、每列 `ROW_HASH` 為「本列內容 + 前列 ROW_HASH」之 SHA-256 鏈式雜湊（依 `LOG_ID` 遞增串接，`AuditLogService.log_action` 以 advisory lock 序列化寫入）。完整性由兩層保護：

### 1. 應用層 append-only（已落地）

`AuditLogRepository` 刻意不提供 update / delete；查詢端無寫入端點（改 / 刪一律 405）。

### 2. DB 層 GRANT（部署 / ops 層，非 migration）

應用連線 DB 帳號對本表**僅授予 `INSERT` / `SELECT`**、撤除 `UPDATE` / `DELETE`，使即便應用碼遭繞過亦無法竄改既有稽核（縱深防禦）。隨部署套用，例：

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON "DP_AUDIT_LOG" FROM <app_role>;
GRANT INSERT, SELECT ON "DP_AUDIT_LOG" TO <app_role>;
```

> 不落 Alembic migration：migration 以 schema owner 執行 DDL，GRANT / REVOKE 屬部署環境之角色治理（見 issue #22）。

### 3. 驗鏈工具 `verify_chain`（T052）

`app.dp.audit.verify.verify_chain(db)` 唯讀走訪全表（`LOG_ID` ASC）重算並比對 `ROW_HASH`，回 `ChainVerifyResult`（`status`＝OK｜BROKEN｜EMPTY、`total`、首斷點 `LOG_ID` / `LOG_TIME` / `FUNC_NAME`）。任一列遭竄改（含攻擊者一併改該列自身 hash）都會在該列或下一列現形。

ops 例行稽核 / CI 可直接執行（退出碼 0＝完好、1＝斷鏈）：

```bash
python -m app.dp.audit.verify
```
