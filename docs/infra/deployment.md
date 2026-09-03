# EDMS 部署說明

> **狀態：設定已備妥，尚未實際部署。** 上線前須完成 §2 的前置條件。
>
> EDMS 與 TBMS **共用 bms-prod-02 這台 VM**。整體共存架構（分流方式、資源配額、隔離原則）由 TBMS repo 的 `docs/infra/edms-coexistence-plan.md` 定義，本檔只描述 EDMS 這一側該怎麼做。兩者衝突時**以該檔為準**。

---

## 0. 兩條決定架構的前提

### 0.1 EDMS 是次級系統

TBMS（血庫）為主系統。**任何取捨一律以「不讓 EDMS 拉低 TBMS 的可用性與安全性」為準。** 實務影響：EDMS 的資源上限設得比 TBMS 低、文件儲存與 log 須有上限、**front-proxy 由 TBMS repo 管理，EDMS 不得定義或重啟它**。

### 0.2 EDMS 是 public repository

這一條決定了整個 CI/CD 架構：

**① 不使用 self-hosted runner。** GitHub 明確建議 public repo 不要用 self-hosted runner——任何人都能開 fork PR，而 PR 觸發的 workflow 會在 runner 上執行任意程式碼。那台 runner 所在的 bms-prod-02 同時跑著血庫系統。

**② 不授予 GitHub workflow 任何 bms-prod-02 的存取權。** 部署必然需要 docker 權限，而 **docker group 等同 root**——可掛載主機檔案系統、讀取 `/opt/tbms/.env.prod`、連上 `tbms-db`。讓 public repo 的 CD 身分取得主系統正式機的 root 等級存取，違反 §0.1。

因此採 **pull-based 部署**：GitHub 只 build 與 push 映像，由 VM 主動拉取。GitHub 側的最大爆炸半徑收斂為「能推一個映像到 `edms-image`」。

---

## 1. 架構

```mermaid
flowchart TD
    GH["GitHub Actions（public repo）<br/>build + 封閉網路驗證 + push"]
    AR["Artifact Registry<br/>edms-image<br/>:latest + :short-sha"]

    subgraph VM2["bms-prod-02"]
        T["edms-deploy.timer<br/>每 5 分鐘檢查"]
        D["vm-deploy.sh<br/>pull → 備份 → migration → up -d"]
        subgraph ENET["edms-proxy-net + edms-net"]
            EN["edms-nginx"]
            EB["edms-backend"]
            ED[("edms-db")]
        end
        PX["front-proxy<br/>由 TBMS repo 管理"]
    end

    GH -->|"WIF 認證，push"| AR
    T --> D
    D -->|"pull"| AR
    D --> EN
    EN --> EB --> ED
    PX -->|"Host: edms.tbsf.tw"| EN
```

**GitHub 與 VM 之間沒有任何連線**——兩側都只碰 Artifact Registry。

### 部署觸發邏輯

`vm-deploy.sh` 每 5 分鐘：

1. `git fetch origin main`，取最新 commit short SHA
2. **確認 AR 已有對應的 `:<sha>` 映像**——沒有代表 CI 還在跑或已失敗，本輪跳過。這一步保證「只部署有對應映像的 commit」，不會拉到與程式碼不一致的半成品
3. 與 `/opt/edms/deployed.sha` 比對，相同即結束（不寫 log）
4. checkout 該 commit → pull → 起 DB → **備份** → migration → `up -d` → 內部 health check → 記錄已部署 SHA

任一步失敗即中止並保留現狀，下一輪重試。

映像以 **commit short SHA** 部署（`EDMS_IMAGE_TAG`），不是 `:latest`——immutable 且可回滾。

---

## 1.1 執行位置速查

本檔的指令散落在三種主機上，執行前先確認自己在哪一台：

| 章節 | 在哪執行 | sudo |
|------|---------|------|
| §2.1～§2.3（GCP 設定） | **開發者自己的電腦或 Cloud Shell**——見 [edms-gcp-setup.md](edms-gcp-setup.md)，該檔有完整指令 | 不用 |
| §2.4（VM 前置） | **bms-prod-02** | 要 |
| §2.5 的「本機開發起手」 | **開發者自己的電腦** | 不用 |
| §3（觀察與排查） | **bms-prod-02** | 唯讀不用，操作容器要 |
| §4.1（client IP 驗收） | **bms-prod-02** | 要 |
| §5 的 psql 維護 | **bms-prod-02** | 要 |

> 本檔所稱「本機」一律指**開發者自己的電腦**，不是 bms-prod-02。

---

## 2. 前置條件

> §2.1～§2.3 需要 `blood-system-dev` 的專案管理權限，EDMS 開發者沒有。
> **完整可執行指令另見 [edms-gcp-setup.md](edms-gcp-setup.md)**，可直接交給維運人員代為執行。

### 2.1 GitHub 側：Workload Identity Federation

**不得使用 service account 金鑰**——public repo 內不能有任何長期憑證。

需設定 WIF 並在 repo variables 填入：

| Variable | 內容 |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<num>/locations/global/workloadIdentityPools/<pool>/providers/<provider>` |
| `GCP_BUILD_SERVICE_ACCOUNT` | 專用於 build/push 的 SA email |

> 🔴 **WIF 的 attribute condition 必須綁到 repo + ref**：
> `assertion.repository == 'sti-fhb/EDMS' && assertion.ref == 'refs/heads/main'`
> 只綁 repo 不夠——那會讓任何分支（含 fork PR 產生的 ref）的 workflow 都能取得該身分。

該 SA **只需** `roles/artifactregistry.writer`，且**只對 `edms-image` 這個 repository**。不得授予 compute、storage 或 TBMS 相關資源的任何權限。

### 2.2 Artifact Registry

新開 repo `edms-image`（`asia-east1`），並**於建立當天設定 cleanup policy**（刪除無 tag 且超過 30 天的映像）。TBMS 曾因未設而累積 1,456 個無 tag 映像、約 8.8 GB。

### 2.3 GCS 備份 bucket

`scripts/db-backup.sh` 需要 `EDMS_BACKUP_BUCKET`（於 `/opt/edms/.env.prod` 設定），VM Service Account 需具寫入權限。

建議 lifecycle：`daily/` 31 天、`pre-migrate/` 31 天、`monthly/` 365 天，並設 30 天 retention 鎖。

> **未設定時部署會直接失敗，這是刻意的**——備份是執行 migration 的前提。

### 2.4 VM 前置（bms-prod-02）

在 bms-prod-02 上執行，**需要 `sudo`**（`/opt` 寫入與 docker 操作皆然；一般帳號未在 `docker` 群組內）。與 §2.1～§2.3 的 GCP 設定互相獨立，兩邊可平行進行。

```bash
sudo mkdir -p /opt/edms/data/postgres
sudo git clone https://github.com/sti-fhb/EDMS.git /opt/edms/repo   # public，免認證

# 機密設定，不進 git
sudo touch /opt/edms/.env.prod && sudo chmod 600 /opt/edms/.env.prod

# proxy 網路（external：兩套系統的 compose 都不建它，
# 任一方的部署都不該因對方未部署而失敗）
sudo docker network create --driver bridge --subnet 172.28.241.0/24 edms-proxy-net

# 部署排程
sudo cp /opt/edms/repo/deploy/edms-deploy.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edms-deploy.timer
```

`.env.prod` 必須包含（金鑰**不得與 TBMS 共用**——EDMS 認證獨立）：

```
POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
DATABASE_URL=postgresql+asyncpg://edms:...@edms-db:5432/edms
JWT_SECRET_KEY=<各環境獨立產生>
ENCRYPTION_KEY=<各環境獨立產生，Base64、解碼後 32 bytes>
EDMS_BACKUP_BUCKET=gs://...
```

### 2.5 環境變數檔一覽

| 檔案 | 用途 | 進 git？ |
|------|------|---------|
| `.env.example` | 範本，列出 docker compose 需要的所有變數 | ✅ |
| `.env.local` | **本機開發**用，由 `docker-compose.override.yml` 引用。從 `.env.example` 複製後填值 | ❌ |
| `/opt/edms/.env.prod` | **正式環境**，放在 VM 上。`vm-deploy.sh` 部署時複製進 `/opt/edms/repo/.env.prod` | ❌ |
| `backend/.env.example`、`frontend/.env.example` | 供「不透過 docker」直接跑起服務時使用 | ✅ |

本機開發起手（在**開發者自己的電腦**上，不是 bms-prod-02）：

```bash
cp .env.example .env.local     # 填入本機用的值
docker compose up -d           # 自動套用 docker-compose.override.yml
```

> ⚠️ 本 repo 為 **public**。`.gitignore` 已擋住 `.env` 與 `.env.*`（範本除外），但**填了實際值的檔案一律不得進版控**——一旦被追蹤即等同公開。

### 2.6 Cloudflare

`edms.tbsf.tw` 的 public hostname 指向 `http://10.140.0.3:80`（與 TBMS 同一目的地，由 front-proxy 依 Host 分流）。此項已完成。

---

## 3. 觀察與排查

以下指令**在 bms-prod-02 上執行**。唯讀查詢不需 `sudo`（該機帳號在 `adm` 群組，讀得到 journal）；操作容器與觸發部署則需要。

```bash
systemctl status edms-deploy.timer          # 排程是否啟用
systemctl list-timers edms-deploy.timer     # 下次觸發時間
tail -50 /opt/edms/deploy.log               # 部署紀錄（無變動時不寫）
cat /opt/edms/deployed.sha                  # 目前部署的 commit
journalctl -u edms-deploy.service -n 50     # 執行失敗的細節

sudo docker compose -f /opt/edms/repo/docker-compose.yml \
     -f /opt/edms/repo/docker-compose.prod.yml ps
```

手動立即部署（不等排程）：

```bash
sudo systemctl start edms-deploy.service
```

---

## 4. 兩個容易靜默失敗的設定

### 4.1 `set_real_ip_from` 必須與 proxy 網段一致

`nginx/nginx.conf` 的 `set_real_ip_from 172.28.241.0/24` 必須與 `edms-proxy-net` 的實際網段相同。

**不一致時不會有任何錯誤訊息**：服務照跑、網站照開，但 access log 的 client IP 會變成 proxy 的容器位址（稽核追不到人），且 `rate-limit.conf` 的 `limit_req_zone $binary_remote_addr` 會把全站算成同一個來源、共用整個額度。

**上線後必須實地確認**（在 **bms-prod-02** 上執行）：

```bash
sudo docker logs edms-nginx --tail 20
```

access log 第一欄應為**真實外部 IP**，不是 `172.28.241.x`。

### 4.2 容器內打自己一律用 `127.0.0.1`

`edms-nginx` 以非 root 的 `USER nginx` 執行，官方 entrypoint 的 `10-listen-on-ipv6-by-default.sh` 因此改不動 root 擁有的 `default.conf`，容器內**只監聽 IPv4**。BusyBox wget 解析 `localhost` 會先試 `::1` 而得到 Connection refused。

TBMS 曾因此誤報部署失敗（服務其實正常），詳見其 `docs/infra/vm-ops-pitfalls.md` §6。凡是「從容器內部打自己」的檢查——health check、compose 的 `healthcheck:`、監控腳本、cron——**一律用 `127.0.0.1`**。

---

## 5. Port 配置

| 環境 | EDMS | TBMS |
|---|---|---|
| 正式 | 三容器**皆不映射** | proxy `80`、`tbms-db` `5432` |
| 本機 | nginx `8090`、db `5441` | nginx `80`、db `5440` |

正式環境 EDMS 的 DB 無外部通道，維護須**登入 bms-prod-02** 後用 `sudo docker exec -it edms-db psql -U edms edms`。日後若需外部連線須用 **5433**（5432 已被 `tbms-db` 佔）。

⚠️ 兩套系統沿用同一組 `DP_` 表名（`DP_USER`、`DP_SESSION`、`DP_AUDIT_LOG`），**連錯資料庫不會報錯**——表存在、欄位對得上、查得出資料，只是查到另一套系統的。動 `UPDATE` / `DELETE` 前先 `SELECT current_database();`。

---

## 6. 上傳上限

`nginx/nginx.conf` 的 `/api/` 設 `client_max_body_size 100m`。這是**實際生效的上限**——front-proxy 那層放行 620m，瓶頸在這裡。

須依實際需求調整（DM 受控文件、ET 教材含影音），並與 app 端自身的上限一致，否則超量請求會由 nginx 自產 HTML 413 而非結構化錯誤碼。

---

## 7. 交付院內封閉網路

EDMS 與 TBMS 同樣要交付院內封閉網路，故受三道約束：

1. **映像執行期不得依賴對外連線**——`backend/Dockerfile` 的 `ENV UV_NO_SYNC=1`，CI 每次以 `docker run --network none` 實測
2. **前端資源全數自帶**——不得引用任何外部 CDN 的字型、圖示、JS
3. **交付方式**為離線包 `docker load` 或院內私有 registry

院內的分流架構**尚未定義**（院內沒有 Cloudflare Tunnel，GCP 的做法搬不過去），見共存規劃 §3。院內亦無 GitHub Actions，屆時部署方式需另行設計——本檔的 pull-based 機制依賴 Artifact Registry，院內不適用。
