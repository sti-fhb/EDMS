# 監控與告警

EDMS 部署在 GCP 的那一套的可用性監控（GCP Cloud Monitoring，專案 `blood-system-dev`）。比照 TBMS 的做法（TBMS repo `docs/infra/monitoring.md`），告警收件人沿用同一組通知管道。

> 本 repo 公開，網域一律寫 `<PUBLIC_HOST>`（與 `deployment.md` 相同）；實際值向維運人員確認、或見 TBMS 的 `monitoring.md`。

> ⚠️ 只涵蓋 GCP。院內環境沒有 GCP，要另外規劃。

## 為什麼要有

服務掛了要有人主動被通知，而不是等使用者回報。EDMS 實際發生過：VM 上的部署因 compose 設定有誤連續失敗一天以上沒人發現（#896，見 `docker-compose.prod.yml` 的 pids 註解）。後端的 event loop watchdog（#905 B16）卡住時會自動重啟，但「重啟後又起不來」也要靠外部監控才看得到。

## Uptime check

| 項目 | 值 |
|---|---|
| 名稱 | `edms-health` |
| 目標 | `https://<PUBLIC_HOST>/edms/health`（Cloudflare → front-proxy 剝掉 `/edms` 前綴 → edms-nginx `location = /health` → 後端，含 DB `SELECT 1`） |
| 頻率／逾時 | 每 1 分鐘、10 秒，從 GCP 多個全球節點發出 |
| 判定 | HTTP 200 **且回應含 `connected`** = 正常；沒回應、503（DB 斷線、連線池滿）或內容不符 = 失敗 |
| 費用 | 在免費額度（每月 100 萬次執行）內 |

為什麼打 `/health` 而不是首頁：首頁是 nginx 的靜態檔，後端全掛也會回 200。`/health` 是唯一能一路驗到 DB 的公開端點，所以它**刻意對外公開**（#905 B15，見 `nginx/nginx.conf`）。

### 建立（需 GCP 專案權限）

⚠️ **一律在 PowerShell 執行**。Git Bash（MSYS）會把 `--path=/edms/health` 自動轉成 Windows 路徑（例如 `/C:/Program Files/Git/edms/health`），探測的就是錯的路徑。TBMS 實際踩過：錯的路徑命中前端的 SPA fallback、拿到首頁的 200——**永遠綠燈、真的掛了也不告警**。

```powershell
gcloud monitoring uptime create edms-health --resource-type=uptime-url `
  "--resource-labels=host=<PUBLIC_HOST>,project_id=blood-system-dev" `
  --protocol=https --port=443 "--path=/edms/health" `
  --period=1 --timeout=10 --status-codes=200 `
  --matcher-content=connected --matcher-type=contains-string `
  --project=blood-system-dev
```

- **一併比對回應內容**（`--matcher-content`）：只看狀態碼的話，路徑一旦落到前端的 SPA fallback（例如日後 front-proxy 的路由改了）也會拿到 200，check 從此**靜默地永遠綠燈**。內容比對讓 check 自己判斷，不靠建立時人工看一次。比對 `connected`（正常時回 `"db":"connected"`，DB 斷線回 `unreachable`，前端首頁沒有這個字）而不是 `"status":"ok"`：Windows PowerShell 5.1 傳參數給外部程式時會吃掉內嵌的雙引號，不含引號的字串最不容易設錯。建立後以下方 describe 確認 `contentMatchers` 的實際值是 `connected`。

- `--resource-labels` 整段要用雙引號包起來：PowerShell 會把逗號當成陣列分隔，gcloud 只收到前半段，回 `INVALID_ARGUMENT: uptime_url check has malformed host`。
- host 一定是 `<PUBLIC_HOST>`、path 一定是 `/edms/health`。host 建立後改不掉（`gcloud monitoring uptime update` 沒有 `--resource-labels`），要改只能重建。

### 驗證（指令成功不代表設定正確）

1. `gcloud monitoring uptime list-configs --project=blood-system-dev` 找到這筆，再 `gcloud monitoring uptime describe <check id> --project=blood-system-dev`，確認 `httpCheck.path` 是 `/edms/health`、`monitoredResource.labels.host` 是 `<PUBLIC_HOST>`。
2. 瀏覽器打 `https://<PUBLIC_HOST>/edms/health`，必須回 `{"status":"ok","app":"EDMS","db":"connected"}`。回的是 HTML 首頁就表示路徑錯了——那種錯誤的 check 會**永遠綠燈**。
3. 等幾分鐘，Console → Monitoring → Uptime checks 裡這筆各節點都出現綠燈。

## 告警政策

建立方式：Console → Monitoring → Alerting → **Create policy**。

| 項目 | 值 |
|---|---|
| 條件 | 指標選 `Uptime check → Check passed`，篩選上面建立的 check；**跨節點聚合**（`check_id` 分組、取失敗的節點數）後**連續失敗 5 分鐘**才觸發。不聚合的話單一節點的網路抖動就會告警 |
| 通知管道 | 選 TBMS 既有的 email channels（同一份收件名單；名單異動到 Console 增刪 channel） |
| 名稱 | `EDMS 網站 uptime 告警（<PUBLIC_HOST>/edms/health）` |
| 恢復 | 異常恢復後告警自動解除 |

⚠️ 收件人名單不寫進本 repo（public）。

> 建立前先以 `gcloud monitoring uptime create --help` 核對旗標（本文件撰寫時未實際執行指令）；若要以檔案定義政策，可參考 TBMS 的 `monitoring.md` 走 REST API 的做法（`gcloud alpha monitoring policies update --policy-from-file` 在 Windows 讀不到檔案）。

### 怎麼確認告警真的會寄

建立後到 Alerting 頁面確認政策是 Enabled、條件綁的是 `edms-health`。要實測的話，挑離峰時段在 VM 上 `sudo docker stop edms-backend` 超過 5 分鐘，確認收到信後 `sudo docker start edms-backend`，恢復後應收到解除通知。

## 建議另加：主機磁碟使用率告警

EDMS 與 TBMS、Docker 共用同一顆磁碟（#905 A1）。uptime check 要等磁碟真的寫滿、服務壞掉才會告警，磁碟告警能提早發現。若 VM 已裝 Ops Agent，在 Alerting 以 `agent.googleapis.com/disk/percent_used` 大於 85% 建立政策；未裝則需先安裝（屬 VM 層設定，與 TBMS 協調）。

## 不會觸發告警的情況

- 1～4 分鐘內恢復的中斷（例如部署換版、watchdog 重啟一次）：條件是連續失敗 5 分鐘。這類要看 `docker inspect -f '{{.RestartCount}}' edms-backend` 與 log（`deployment.md` §3）。
- 後端正常、但某個功能壞了（例如寄信失敗）：`/health` 只驗到 DB 連得上。
