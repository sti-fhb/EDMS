# EDMS 部署說明

> **狀態：設定已備妥，尚未實際部署。** 上線前須先完成 §1 的四項前置條件。
>
> EDMS 與 TBMS **共用 bms-prod-02 這台 VM**。整體共存架構（分流方式、資源配額、隔離原則）由 TBMS repo 的 `docs/infra/edms-coexistence-plan.md` 定義，本檔只描述 EDMS 這一側該怎麼做。兩者衝突時**以該檔為準**。

---

## 0. 前提：EDMS 是次級系統

TBMS（血庫）為主系統、EDMS 為次級系統。**任何取捨一律以「不讓 EDMS 拉低 TBMS 的可用性」為準。** 實務上的影響：

- EDMS 與 TBMS 的 CD 共用同一個 `cd` runner，會**序列化排隊**。TBMS 的緊急修復優先——必要時 EDMS 的 job 會被手動取消
- EDMS 的資源上限設得比 TBMS 低（見共存規劃 §6.3）
- 文件儲存與 log 須有上限，不得吃爆磁碟連累 TBMS
- **front-proxy 由 TBMS repo 管理**，EDMS 不得定義或重啟它

---

## 1. 上線前的四項前置條件

### 1.1 self-hosted runner（最硬的卡點）

CD 必須在 bms-prod-02 本機執行（直接操作該機的 docker），**GitHub-hosted runner 做不到**——那台 VM 的 SSH 限辦公室 IP，也沒有可用憑證。

本 repo 的 `ci.yml` 目前跑 `ubuntu-latest`（這是刻意的，見 §4），但 `cd.yml` 需要 `runs-on: [self-hosted, cd]`。

**待確認**：該 runner 是 org-level 還是 repo-level 綁在 TBMS？

- org-level → 直接可用
- repo-level → 需改註冊為 org-level，或在同機為本 repo 另註冊一個 runner

### 1.2 Artifact Registry

需新開 repo `edms-image`（`asia-east1`），並**於建立當天設定 cleanup policy**：

```bash
gcloud artifacts repositories set-cleanup-policies edms-image \
  --location=asia-east1 --policy=policy.json --no-dry-run
```

`policy.json` 內容為「刪除無 tag 且超過 30 天的映像」。TBMS 曾因未設而累積 1,456 個無 tag 映像、約 8.8 GB。

### 1.3 GCS 備份 bucket

`scripts/db-backup.sh` 需要環境變數 `EDMS_BACKUP_BUCKET`（於 `/opt/edms/.env.prod` 設定），且 VM Service Account 需具該 bucket 寫入權限。

建議的 lifecycle：`daily/` 31 天、`pre-migrate/` 31 天、`monthly/` 365 天，並設 30 天 retention 鎖（防 VM 遭入侵時備份被一併銷毀）。

> **未設定時 CD 會直接失敗，這是刻意的**——備份是執行 migration 的前提，沒有可還原的快照就不動 schema。

### 1.4 主機前置（bms-prod-02）

```bash
sudo mkdir -p /opt/edms/data/postgres
# .env.prod 由維運人員自行建立，不進 git
sudo touch /opt/edms/.env.prod && sudo chmod 600 /opt/edms/.env.prod

# proxy 網路（若 TBMS 側尚未建立）
sudo docker network create --driver bridge --subnet 172.28.241.0/24 edms-proxy-net
```

`edms-proxy-net` 為 **external**：兩套系統的 compose 都不負責建立它，任一方的部署都不該因對方未部署而失敗。

`.env.prod` 必須包含（金鑰**不得與 TBMS 共用**——EDMS 認證獨立）：

```
POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
DATABASE_URL=postgresql+asyncpg://edms:...@edms-db:5432/edms
JWT_SECRET_KEY=<各環境獨立產生>
ENCRYPTION_KEY=<各環境獨立產生，Base64、解碼後 32 bytes>
EDMS_BACKUP_BUCKET=gs://...
```

---

## 2. 架構

```mermaid
flowchart TD
    U["瀏覽器<br/>edms.tbsf.tw"]

    subgraph VM1["bms-prod-01"]
        CF["cloudflared"]
    end

    subgraph VM2["bms-prod-02"]
        PX["front-proxy<br/>由 TBMS repo 管理"]
        subgraph ENET["edms-proxy-net + edms-net"]
            EN["edms-nginx<br/>不映射 host port"]
            EB["edms-backend<br/>:8000 不映射"]
            ED[("edms-db<br/>postgres:17")]
        end
    end

    U --> CF
    CF -->|"http://10.140.0.3:80"| PX
    PX -->|"Host: edms.tbsf.tw"| EN
    EN --> EB --> ED
```

三個容器都**不映射 host port**，對外只有 front-proxy 的 80。

| 環境 | 套用的檔案 | 對外 |
|------|-----------|------|
| 本機 | `docker-compose.yml` + `docker-compose.override.yml` | `edms-nginx` → `8090`、`edms-db` → `5441`（避開 TBMS 本機的 80／5440） |
| 正式 | `docker-compose.yml` + `docker-compose.prod.yml` | 皆不映射，經 front-proxy |

---

## 3. 兩個容易靜默失敗的設定

### 3.1 `set_real_ip_from` 必須與 proxy 網段一致

`nginx/nginx.conf` 的 `set_real_ip_from 172.28.241.0/24` 必須與 `edms-proxy-net` 的實際網段相同。

**不一致時不會有任何錯誤訊息**：服務照跑、網站照開，但 access log 的 client IP 會變成 proxy 的容器位址（稽核追不到人），且 `rate-limit.conf` 的 `limit_req_zone $binary_remote_addr` 會把全站算成同一個來源、共用整個額度。

**上線後必須實地確認**：

```bash
sudo docker logs edms-nginx --tail 20
```

access log 第一欄應為**真實外部 IP**，不是 `172.28.241.x`。

### 3.2 容器內打自己一律用 `127.0.0.1`

`edms-nginx` 以非 root 的 `USER nginx` 執行，官方 entrypoint 的 `10-listen-on-ipv6-by-default.sh` 因此改不動 root 擁有的 `default.conf`，容器內**只監聽 IPv4**。BusyBox wget 解析 `localhost` 會先試 `::1` 而得到 Connection refused。

TBMS 曾因此誤報部署失敗（服務其實正常），詳見其 `docs/infra/vm-ops-pitfalls.md` §6。凡是「從容器內部打自己」的檢查——CD health check、compose 的 `healthcheck:`、監控腳本、cron——**一律用 `127.0.0.1`**。

---

## 4. 為什麼 CI 不搬到 self-hosted

TBMS 的 CI 跑在 bms-prod-01，而那台**併發度是 1**（刻意收回的：同機兩個重量 job 會讓 load average 衝到 8.8、frontend job 拖到 32 分鐘，還會產生難歸因的偶發失敗）。

EDMS 的 CI 若也搬過去，兩個 repo 的 PR 會互相排隊，**TBMS 的 PR 要等 EDMS 的測試跑完**——違反 §0。

因此 `ci.yml` 維持 `ubuntu-latest`，代價是消耗 GitHub Actions 分鐘數。**只有 `cd.yml` 用 self-hosted**，因為它別無選擇。

---

## 5. 上傳上限

`nginx/nginx.conf` 的 `/api/` 設 `client_max_body_size 100m`。這是**實際生效的上限**——front-proxy 那層放行 620m，瓶頸在這裡。

須依 EDMS 實際需求調整（DM 受控文件、ET 教材含影音），並與 app 端自身的上限一致，否則超量請求會由 nginx 自產 HTML 413 而非結構化錯誤碼。

---

## 6. 交付院內封閉網路

EDMS 與 TBMS 同樣要交付院內封閉網路，故受三道約束：

1. **映像執行期不得依賴對外連線**——`backend/Dockerfile` 的 `ENV UV_NO_SYNC=1`，CD 每次以 `docker run --network none` 實測
2. **前端資源全數自帶**——不得引用任何外部 CDN 的字型、圖示、JS
3. **交付方式**為離線包 `docker load` 或院內私有 registry

院內的分流架構**尚未定義**（院內沒有 Cloudflare Tunnel，GCP 的做法搬不過去），見共存規劃 §3。
