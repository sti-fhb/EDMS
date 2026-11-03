# Query string 帶個資的端點清單

> **這份文件要回答的問題**：哪些 API 會把可識別個人的值放進網址？各自被誰記下來？
> 還缺什麼事實才能決定要不要改？
>
> 建立於 #391（來自 #385 的 Security Review）。**本文件是決策輸入，不是規範**——
> 它存在的目的是讓日後評估日誌保存政策的人不必重新盤點一次。

as-of **2026-11-03**（初版 2026-09-23；依 #391 SA 裁示更新）。端點清單以 `grep -rn "Query(" backend/app --include=*.py` 掃出後逐支判讀。

## 一、完整清單

判準是**參數的值是否可識別到特定的人**，不是參數名稱。

| 端點 | 參數 | 值的性質 | 狀態 |
|---|---|---|---|
| `POST /api/et/approvals/search` | `user_name` | ✅ **必定是姓名**——這個參數沒有別的用法 | ✅ **已改走 body**（#391 / PR #422）|
| `GET /api/dp/users` | `q` | ⚠️ **姓名或 Email**——`dp/users/repository.py` 以 `ilike` 同時打 `USER_NAME` 與 `EMAIL` 兩欄 | 維持現況（#391 裁示）|
| `GET /api/dp/users/invites` | `q` | ⚠️ 同上。邀請名單的查詢實務上多半打 Email | 維持現況（#391 裁示）|
| `GET /api/dp/audit/logs` | `operator` | ⚠️ 操作者 `USER_ID`／姓名／Email 模糊比對，實務上多半輸入姓名（見 `dp/audit/repository.py`）| 維持現況（#391 裁示）|
| `GET /api/dp/audit/logs/export` | `operator` | ⚠️ 同上（稽核 CSV 匯出；2026-11-03 補列）| 維持現況（#391 裁示）|
| `GET /api/dm/library/documents` | `author` | ⚠️ 文件作者 | 維持現況（#391 裁示）|
| `GET /api/dm/**` 的 `keyword` / `query` | — | ❌ 文件名稱／內容關鍵字，非個資 | ➖ 不適用 |
| `GET /api/dp/roles` 的 `keyword` | — | ❌ 角色名稱 | ➖ 不適用 |
| `GET /api/et/courses` 的 `q` | — | ❌ 課程名稱 | ➖ 不適用 |
| `GET /api/dp/audit/logs` 的 `func_name` / `module` / `action_type` | — | ❌ 列舉值或功能代碼 | ➖ 不適用 |

⚠️ **「必定」與「可能」的差別是本清單的重點**。`et/approvals` 那一支的參數語意**就是**一個人的姓名，沒有其他用法；其餘五支是「使用者輸入的關鍵字**可能**是個資」。#391 處理了前者；後者經 SA 裁示維持現況，理由見第三節。

⚠️ 新增查詢端點時請回到本表判讀一次。判準不是「參數叫什麼」，是「值可不可能識別到人」。

## 二、既有防護擋得住什麼、擋不住什麼

| 記錄點 | 狀態 | 說明 |
|---|---|---|
| EDMS nginx **access log** | ✅ **已處理** | `nginx/log-format.conf` 以 `$request_uri` 去除 `?` 之後的部分。⚠️ 刻意不用 `$uri`——後者是解碼後的值，`%0A` 會還原成真實換行而構成 log injection |
| uvicorn **access log** | ✅ **已處理** | `--no-access-log` |
| EDMS nginx **`error_log`** | 🔴 **擋不住** | 記錄完整 request（含 query string），而 **nginx 的 error log 格式不可自訂**。壓抑之需把層級提到 `crit`，代價是失去後端中斷的可觀測性，故不採 |
| **Cloudflare 請求日誌** | 🔴 **擋不住，且不在 EDMS 手上** | 經 Cloudflare Tunnel 對外的環境，Cloudflare 端記錄含 query string 的完整 URI。front-proxy／Tunnel 由 TBMS 管理（`deployment.md` §0.1：EDMS 不得定義或重啟它）。**僅 GCP 測試環境經過；院內正式機不經 Cloudflare**（#391 裁示）|
| **瀏覽器歷史 / `Referer`** | 🔴 **擋不住** | 使用者端的紀錄，伺服器無從干預 |

> 上述前三條在 `nginx/log-format.conf` 的檔頭註記已寫明。本文件不重複它的內容，只把
> 「哪些端點受影響」這一半補上——那是該註記沒有、也不該有的資訊。

⛔ **不要憑 access log 已處理就宣稱「PII 不進 log」。** 那句話在本系統是錯的。

## 三、裁示：維持現況（#391，2026-11-03）

第一節標「維持現況」的五支**不改走 POST body**。原本待釐清的「Cloudflare 端日誌保存期與存取權限」已不影響決定，視為已釐清：

- 院內正式機自行終結 HTTPS，**不經 Cloudflare**；只有 GCP 經 Cloudflare，而 GCP 是測試環境，沒有真實個資
- 正式環境剩下的記錄點是院內主機的 nginx `error_log`（只在後端錯誤時記錄，由院方管理）與操作者自己的瀏覽器歷史
- 五支端點皆限管理者或編輯者使用，風險可接受

🔴 **須重新評估的條件**：院內正式機日後改經 Cloudflare，或改經其他會留存完整網址的代理時，本裁示的前提即不成立，須回到本文件重新判斷。屆時**不需要重新盤點端點**——第一節就是那份盤點；改法見第四節。

## 四、決定要改時怎麼改（ET 的前例）

PR #422 的作法可直接沿用：

1. 新增一個 request model（欄位與驗證規則從原 `Query(...)` 原封搬過來）
2. 端點改 `POST /{resource}/search`，收 body
3. 前端 service 由 `http.get(url, { params })` 改為 `http.post(url, body)`
4. 加**兩道紅線測試**（見下）

### ⭐ 成本比想像的低：前端快取 key 不用動

`usePagedQuery(queryKey, queryFn)` 的 **queryKey 是獨立參數**，fetcher 只是
`() => Promise<PagedResult<T>>`。改請求方式**完全不影響快取 key**
（#422 的 `TeacherApprovalQuery.tsx` 一行未改可為證）。

> #391 的 issue body 原本寫「前端要改快取 key 的組法」——那個估計是錯的，已於 #422 更正。

### 🔴 兩道紅線測試不可省

改完之後，「把值放回網址」是一個**功能完全正常、畫面沒有任何差異**的回歸——
所有既有測試都會照樣通過。#422 實測：在 router 補一個「相容用」的 `Query(...)` 退路後，
**28 條功能測試全綠，只有紅線那條紅**。

| 測試 | 擋什麼 |
|---|---|
| 後端：帶 query string、不帶 body → 預期 422 | 有人補 `Query(...)` 退路 |
| 前端：斷言 request body 有該值、且 **URL 不含原文與 URL-encoded 形式** | 有人把 service 改回 `http.get(url, { params })` |

⚠️ 前端那條**必須連 encoded 形式一起斷言**——`encodeURIComponent("林佳蓉")` 之後是一串
看不出來的百分號序列，只比對原文會漏掉。

### ⚠️ 兩個會被 reviewer 問的設計點

- **這是不寫入的 POST**：專案規則要求「寫入型 API 一律注入 `OperatorInfo`」，此類端點
  **刻意不注入**、也不寫稽核——用 POST 的唯一理由是本文件所述的日誌問題，語意仍是讀取。
  請寫進 docstring，否則會被依規則字面判為缺漏。
- **路徑用 `/{resource}/search`**，不要用 `POST /{resource}`——後者在語意上是「建立」，
  同一個名詞上兩個 POST 表示相反的事會造成誤讀。

## 相關

- `nginx/log-format.conf`（access log 去尾的作法與其取捨）
- #391（本清單的來源）、#385（Security Review 發現點）、PR #422（ET 那一支的實作）
