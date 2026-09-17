# ET 模組初始化與上線步驟

> 本文為**模組初始化層**：ET 在一個已經跑得起來的 EDMS 上要額外做什麼。
> 基礎設施層（GCP / WIF / VM / SMTP / CD）見 [`deployment.md`](deployment.md) 與 [`edms-gcp-setup.md`](edms-gcp-setup.md)。
>
> 對應 `docs/specs/et/tasks.md` T124、`docs/specs/et/issues.md` Issue #14 AC 10。

---

## 這份文件要解決什麼

ET 幾乎所有初始化都由 migration 完成，**唯二需要人做決定的是兩個 `.env` 值**。但其中一個
（`ET_BOOTSTRAP_ADMIN_EMAIL`）漏設**不會讓任何東西失敗**——migration 照跑、服務照起、
API 照回 200，只是**沒有任何人能成為 ET 管理者，而且沒有辦法事後補救**（見下方「死結」）。

所以本文的重點不是步驟清單，是**哪幾步漏了不會有人發現**。

---

## 一、前提

| 項目 | 說明 |
|---|---|
| 平台 DP 已初始化 | ET 的參數與通知範本都種進 DP 的共用表（`DP_PARAM_M/D`、`DP_NOTIFY_TEMPLATE`），排程也註冊在 `DP_SCHEDULE`。DP 的表不存在則 ET 的 migration 會失敗 |
| 至少一個 `DP_USER` 帳號存在 | 首位 ET 管理者是**依 Email 查既有帳號**再授權，**不會建帳號** |
| DM 模組已初始化 | ET 教材引用 DM 文件；`DM_CATEGORY` 需有 `TRAINING` 分類（由 DM 的 seed migration 種入）|

---

## 二、`.env` 設定（唯二需要人決定的）

```bash
# 1. 首位 ET 管理者的 Email——必須是**已存在於 DP_USER** 的帳號
ET_BOOTSTRAP_ADMIN_EMAIL=admin@your-org.gov.tw

# 2. 影片落盤根——production 必須是絕對路徑（Windows 另需磁碟機）
ET_VIDEO_STORAGE_ROOT=/srv/edms/et_videos
```

### ⚠️ `ET_BOOTSTRAP_ADMIN_EMAIL` 漏設是一個**無聲**的死結

`dp/roles/service._require_manageable()` 呼叫 `module_admin_gate.is_module_admin("ET", ...)`，
而該閘是 **fail-closed**：

```
ET_USER_ROLE 初始為空
  → 沒有人是 ET 管理者
  → 任何人呼叫「指派 ET 角色」皆被 403 DP_ROLE_001 擋下
  → 沒有人能授予第一個 ET 管理者角色
```

`20260820_1730_d5f9a2b8e614` 這支 migration 就是用來解開它的。但它在**未設定或查無帳號時
只記 log、不讓 migration 失敗**（刻意如此——CI 與新環境無此設定仍須能升級）。

於是漏設的症狀是：**一切正常，只是 ET 的權限管理永遠打不開**。而此時已無法從 UI 補救，
只能重跑 migration 或直接對 DB 下 SQL。

**部署後務必驗證**（見第六節第 1 項）。

### ⚠️ `ET_VIDEO_STORAGE_ROOT` 用相對路徑會在 production 擋下啟動

這是刻意的護欄（#233）：相對路徑依 **process 的工作目錄**解析，同一份設定從不同目錄啟動
即得到不同的 root，且不會有任何錯誤訊息——`FILE_PATH` 改存相對路徑之後，root 一錯就是
**全部影片一起讀不到**，而圍籬擋在存在性檢查之前，回的是 404 不是 500。

---

## 三、Migration 做了什麼（不需要人工介入，但要知道）

依序執行，全部**冪等**（重跑不重複、不覆寫管理者後續的編輯）：

| Migration | 內容 |
|---|---|
| `9aa92b82d0a0` | 建立 ET 全部資料表 |
| `b3d7e2c9f451` | **`ET_TAG` 5 筆內建標籤**，含「全體」（`IS_ALL=true`，全系統僅此 1 筆）|
| `c4e8f1a6d372` | **ET 參數與通知範本**種入 DP 共用表 |
| `d5f9a2b8e614` | **首位 ET 管理者** + **存量帳號回填學員角色** |
| `c7d4a1e93b52` | **SCHET002** handler 接線 + `IX_ET_ATTEMPT_IN_PROGRESS` 部分索引 |
| `d5a81f37c6b2` | **SCHET001** handler 接線；並**移除** `DP_PARAM.ET_WEEKLY_STAT_DAY_TIME` |

### 3.1 `ET_TAG`：5 筆內建標籤

`全體`（`IS_ALL=true`）、`護理師`、`行政人員`、`軍人`、`醫檢師`。

「全體」是特殊標籤——代表所有具「學員」角色的使用者，**不需逐人貼標**（`IS_ALL` 不看
使用者有沒有實際掛上它），且**不可停用、不可改名**（伺服器端於 SRVET004 轉接層拒絕，
`ET_TAG_001`）。全系統僅此 1 筆 `IS_ALL=true`。

其餘 4 筆為**範例值**，管理者可於 DP 後台停用 / 改名 / 新增。seed 以 `TAG_NAME` 判重，
重跑不會覆寫管理者的編輯。

### 3.2 ET 系統參數（`DP_PARAM`，前綴 `ET_`）——**目前 5 項**

| 參數 | 用途 |
|---|---|
| `ET_INVITATION_CODE_LENGTH` | 邀請碼長度 |
| `ET_URGENT_REMIND_DAYS` | 截止前幾天寄加急提醒（預設 3）|
| `ET_VIDEO_ALLOWED_FORMATS` | 影片允許副檔名 |
| `ET_VIDEO_MAX_SIZE_MB` | 影片單檔上限 |
| `ET_VIDEO_PLAYBACK_MAX_RATE` | 播放倍速上限 |

> ⚠️ **原本是 6 項。** `ET_WEEKLY_STAT_DAY_TIME` 已於 ET-16（`d5a81f37c6b2`）**移除**——
> 排程時間由 `DP_SCHEDULE.CRON_EXPR` 控制，而規格三處曾寫「時間由該參數控制」，
> 兩個事實來源並存會讓人改了參數卻沒有任何效果。舊 migration（`c4e8f1a6d372`）的
> docstring 仍寫「6 項」，那是**當時**的事實，不要據以驗收。

### 3.3 通知範本（`DP_NOTIFY_TEMPLATE`，`MODULE=ET`）——7 類

`COURSE_INVITE`、`COURSE_INVITE_DIGEST`、`COURSE_UPDATE`、`URGENT_REMIND`、
`WEEKLY_REMIND`、`WEEKLY_REPORT`、`APPROVAL_PASSED`

- `CHANNEL` 一律 **`EMAIL`**。ET 規格未定義站內訊息。
  ⚠️ **必須使用平台正規詞彙**（`EMAIL` / `MSG` / `BOTH`）——自創值會讓平台 `send_email`
  **靜默不寄信**（不拋例外、`queued_count=0`）
- `IS_SYSTEM=false`：7 類皆可由 ET 管理者於 DP 後台編輯主旨 / 內文並啟停
- 密碼重設 / 帳號驗證屬平台系統信（`MODULE=DP`），**不在此清單**、ET 不維護

> ⚠️ **範本的 `params` key 必須逐字對齊內文的佔位符**。不一致時平台的 `_SafeFormatter`
> 會拋 `KeyError` → 該封信 `STATUS='FAILED'`、`queued_count=0`、**不拋例外**。
> 症狀是「信沒到」而不是「系統壞了」。

### 3.4 存量帳號回填學員角色

`grant_default_student_role` 只在**帳號啟用當下**觸發，ET 上線前的既有帳號不會回頭補——
它們的 `ET_USER_ROLE` 是空的，一進 ET 就被 `ET_AUTH_001` 擋下。

- 帳號狀態（停用 / 鎖定）**不納入判斷**——角色指派與帳號狀態是兩件事
- 已軟刪除的帳號（`DP_USER.DELETED=1`）**排除**

---

## 四、排程（`DP_SCHEDULE`）

| Job | `CRON_EXPR` | 台北時間 | Handler | 做什麼 |
|---|---|---|---|---|
| **SCHET001** | `0 10 * * 0` | 每週一 18:00 | `app.et.schedules.handlers.weekly_job` | 週統計快照 + 週報（管理者）+ 未完課提醒（學員）|
| **SCHET002** | `0 8 * * *` | 每日 16:00 | `app.et.schedules.handlers.daily_job` | 到期自動關閉 + 結清逾期未提交的作答 + 截止前加急提醒 |

### ⚠️ `CRON_EXPR` 是 **UTC**

`CronTrigger.from_crontab(cron_expr, timezone="UTC")`。`0 8 * * *` 是台北 **16:00**，
不是早上八點。排定「上班時間寄信」時請自行換算。

### ⚠️ day-of-week 是 **週一為 0**，不是標準 crontab 的週日為 0

APScheduler 把 cron 的 dow 欄位直接塞進它自己的 `day_of_week`（`0=Monday`），**不做**
標準 crontab（`0=Sunday`）的轉換：

| dow | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| 實際 | 週一 | 週二 | 週三 | 週四 | 週五 | 週六 | 週日 |

旁證：`7` 會被直接拒絕（`the last value (7) is higher than the maximum value (6)`），
而標準 crontab 接受 7 為週日。

SCHET001 與 SCHDM001 原本都寫 `0 10 * * 1`，實際跑在**週二**，已於 #332
（`c8b4e2f1d97a`）更正為 `0 10 * * 0`。釘住這條語意的測試在
`backend/tests/unit/dp/test_dp_schedule_cron_weekday.py`。

### 沒有手動重跑的端點

要提前觸發只能改 `CRON_EXPR`（`apply_job_change` 會**立即生效**，不需重啟）。
**改完務必改回去**——SCHET001 是每週一次，設錯的話下次發現要等一週。

---

## 五、DM 整合

| 項目 | 說明 |
|---|---|
| 分類碼 | ET 教材只引用 `DM_CATEGORY` 的 **`TRAINING`** 分類（非 `TRAINING_MATERIAL`）|
| 取用方式 | 經 `app/services` 的 `DmDocumentService`（SRVDM001），ET **不直接讀 DM 的表** |
| 版本 | `ET_MATERIAL_DOC` **只存 `DOC_ID`**，引用恆指向當前發布版 |
| 廢止 | 引用已廢止文件的課程**不可發布**（`OBSOLETE_DOC`）；已發布課程不受事後廢止影響，學員端顯示廢止標籤但**仍可閱讀**廢止前最後一版 |
| 取檔 | ET 學員取教材檔**不寫 `DM_DOC_READ`**（契約 D-2）——故 ET 的閱讀**不會**計入 DM 的閱讀率 KPI |

---

## 六、部署後驗證清單

前三項**漏了不會有任何錯誤訊息**，務必實際確認。

1. **首位 ET 管理者存在**
   ```sql
   SELECT * FROM "ET_USER_ROLE" WHERE "ROLE" = 'ADMIN' AND "DELETED" = 0;
   ```
   空的 → `ET_BOOTSTRAP_ADMIN_EMAIL` 漏設或查無該帳號。**此時無法從 UI 補救。**

2. **ET 參數 5 項、通知範本 7 類都在**
   ```sql
   SELECT "PARAM_ID" FROM "DP_PARAM_M" WHERE "PARAM_ID" LIKE 'ET\_%';
   SELECT "TEMPLATE_CODE", "CHANNEL", "IS_ACTIVE" FROM "DP_NOTIFY_TEMPLATE" WHERE "MODULE" = 'ET';
   ```
   `CHANNEL` 必須全部是 `EMAIL`。

3. **兩支排程已註冊且啟用**
   DP 後台 → 排程管理，確認 SCHET001 / SCHET002 **都在、都啟用、都有「下次執行時間」**。
   下次執行時間為空 = 該 job 是停用的。

4. **存量帳號都有學員角色**
   ```sql
   SELECT COUNT(*) FROM "DP_USER" u
   WHERE u."DELETED" = 0
     AND NOT EXISTS (SELECT 1 FROM "ET_USER_ROLE" r
                     WHERE r."USER_ID" = u."USER_ID" AND r."ROLE" = 'STUDENT' AND r."DELETED" = 0);
   ```
   應為 0。

5. **影片落盤根可寫**，且與 `.env` 一致（見第二節的護欄說明）。

---

## 七、production 啟動護欄（設錯就起不來）

`DEBUG=false` 時 `Settings` 有**五道**啟動檢核。它們散在五個 `model_validator` 裡，
光讀欄位定義看不出來——以下為完整清單（由 `tests/unit/test_security_invariants.py::TestProductionStartupGuards` 釘住）：

| 設定 | 要求 | 漏了會怎樣 |
|---|---|---|
| `JWT_SECRET_KEY` | 長度足夠（依演算法）| 簽章可被離線暴力破解 |
| `FRONTEND_BASE_URL` | 非空、不得指向 localhost / 127.0.0.1 | 信件連結組成空網域或指向開發機，使用者點不到 |
| `TRUSTED_PROXY_COUNT` | 必須**明示**設定（直接對外設 0）| 限流與稽核的來源 IP 可被偽造 |
| `DM_FILE_STORAGE_ROOT` / `ET_VIDEO_STORAGE_ROOT` | 絕對路徑（Windows 另需磁碟機）| 換啟動位置即全部檔案讀不到，回 404 不是 500 |
| `MAIL_STARTTLS` / `MAIL_SSL_TLS` | 已設 `MAIL_SERVER` 時至少一為 true，且不可同時 true | 明文 SMTP：帳密與信件內容明文上線 |

### ⚠️ `DEBUG=true` 會一次繞過全部五道

這是唯一能讓上述任一項設錯而仍然啟動的方式。**正式環境的 `DEBUG` 必須是 `false`**，
且這一項本身沒有護欄擋（護欄就是靠它判斷的）。

---

## 相關文件

- [`deployment.md`](deployment.md)、[`edms-gcp-setup.md`](edms-gcp-setup.md)（基礎設施層）
- `docs/specs/et/data-model.md` §系統參數、§受訓單位標籤
- `docs/specs/et/contracts/srv-et-dp-module-callbacks.md`（四個聚合閘）
- `docs/specs/et/contracts/ext-et-email-server.md`（通知範本）
- `backend/tests/unit/test_security_invariants.py`（production 護欄的測試）
