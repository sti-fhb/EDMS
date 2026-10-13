# 正式 DB 對外維護連線（SSL + client 憑證）

> ☁️ **本檔只適用 GCP 線上環境（bms-prod-02）。** 院內封閉網路由 TBMS repo 的交付包管理
> （`scripts/onprem-packaging/`，預設只綁 `127.0.0.1`、走 SSH 通道），與本檔無關。
>
> 做法比照 TBMS repo 的 `docs/infra/db-external-access.md`，差異見文末「與 TBMS 的差異」。

正式 PostgreSQL（`edms-db`）原本只在 docker 內部網路、不對外。本文件說明如何**安全開放 5433** 供 pgAdmin / DBeaver 等 client 維護：

- **主機側用 5433**：容器內仍是 5432，但主機的 5432 已被 `tbms-db` 佔用
- **連線一律走 SSL + client 憑證**：白名單 IP 必須持有簽發的 client 憑證（金鑰）＋密碼才連得上
- **內部溝通不變**：`edms-backend` 仍透過 `edms-net` 內部網路、用密碼連 `edms-db`
- **雙重把關**：GCP firewall 限定來源白名單 IP；PostgreSQL `pg_hba.conf` 對外強制 `hostssl ... clientcert=verify-full`

> ⚠️ 這是把**正式 DB 暴露到公網**的設定。
>
> 🔴 **本 repo 為 public**：憑證私鑰（`server.key`、`client.key`、`root.key`）、白名單 IP、VM 公網 IP **一律不得寫進 repo**（含本文件、issue、PR 描述）。它們只存在於 VM 與維護者本機。

## 架構

| 連線來源 | 路徑 | pg_hba 規則 | 認證 |
|---|---|---|---|
| `pg_dump`（`db-backup.sh`）、`pg_isready` | 容器內 unix socket | `local ... trust` | — |
| `edms-backend`、migration | docker `edms-net` | `host ... scram-sha-256` | 密碼 |
| 維護者 pgAdmin | 公網 → GCP firewall → VM:5433 → 容器:5432 | `hostssl ... scram-sha-256 clientcert=verify-full` | 密碼 + client 憑證 |
| 其他 | — | `reject` | 拒絕 |

## 設定檔涉及範圍

| 項目 | 位置 | 進 git? |
|---|---|---|
| prod override（ports / ssl command / mount） | [docker-compose.prod.yml](../../docker-compose.prod.yml) | ✅ |
| 部署前檢查憑證與 pg_hba 是否備妥 | [scripts/vm-deploy.sh](../../scripts/vm-deploy.sh) | ✅ |
| 憑證（CA / server / client） | VM `/opt/edms/postgres/certs/` | ❌ |
| `pg_hba.conf` | VM `/opt/edms/postgres/pg_hba.conf` | ❌（含白名單 IP） |
| GCP firewall（tcp:5433，白名單來源） | GCP | —（已開通） |

---

## 部署流程（務必照順序）

> 🚨 **必須先完成步驟 1～2，再 merge。** EDMS 是 pull-based 部署——merge 後 `edms-deploy.timer` 最慢 5 分鐘內就會自動部署，沒有「merge 了但還沒部署」的緩衝。
>
> 前置未備妥時，`vm-deploy.sh` 會在動到任何容器前中止（現行服務不受影響），並於 `/opt/edms/deploy.log` 每 5 分鐘記一次「缺少 …」，直到補齊為止。

以下全部在 **bms-prod-02** 上執行，**需要 `sudo`**（docker 指令亦然）。

### 步驟 1：建立目錄與憑證

```bash
sudo mkdir -p /opt/edms/postgres/certs
cd /opt/edms/postgres/certs
```

**取得對外位址**：與 TBMS 同一台 VM、同一個公網位址，直接從 TBMS 的 server 憑證讀出，確保兩邊一致（verify-full 會比對 SAN，務必正確）：

```bash
sudo openssl x509 -in /opt/tbms/postgres/certs/server.crt -noout -ext subjectAltName
# 輸出形如 IP Address:x.x.x.x 或 DNS:xxx

DB_HOST="<上面讀出的 IP 或網域>"
SAN_TYPE="IP"        # 上面是 DNS: 就改成 DNS
```

**1-1. 自簽 CA（根憑證，10 年）**——刻意**不沿用 TBMS 的 CA**，理由見文末

```bash
sudo openssl req -new -x509 -days 3650 -nodes \
  -out root.crt -keyout root.key \
  -subj "/CN=EDMS-DB-CA"
```

**1-2. server 私鑰 + CSR + 簽發（825 天）**

```bash
sudo openssl req -new -nodes -out server.csr -keyout server.key \
  -subj "/CN=${DB_HOST}"

printf "subjectAltName=%s:%s\n" "${SAN_TYPE}" "${DB_HOST}" | sudo tee /tmp/edms-san.ext >/dev/null

sudo openssl x509 -req -in server.csr -days 825 \
  -CA root.crt -CAkey root.key -CAcreateserial \
  -extfile /tmp/edms-san.ext \
  -out server.crt
```

**1-3. client 私鑰 + CSR + 簽發**（CN **必須**等於要登入的 PG 帳號，即 `.env.prod` 的 `POSTGRES_USER`，預設 `edms`）

```bash
sudo openssl req -new -nodes -out client.csr -keyout client.key \
  -subj "/CN=edms"

sudo openssl x509 -req -in client.csr -days 825 \
  -CA root.crt -CAkey root.key -CAcreateserial \
  -out client.crt
```

**1-4. 權限**（`postgres:17` 容器內 `postgres` 為 uid 999；server.key 不能 group/world 可讀）

```bash
sudo chown 999:999 server.key
sudo chmod 600 server.key root.key client.key
sudo chmod 644 server.crt root.crt client.crt
sudo rm -f server.csr client.csr /tmp/edms-san.ext
```

**1-5. 驗證憑證鏈**

```bash
sudo openssl verify -CAfile root.crt server.crt client.crt   # 兩行皆應為 OK
sudo openssl x509 -in server.crt -noout -ext subjectAltName   # 應與 TBMS 那張相同
```

### 步驟 2：建立 `pg_hba.conf`

**2-1. 確認 `edms-net` 網段**——`edms-backend` 靠這條規則連 DB，填錯會讓整套 EDMS 連不上資料庫：

```bash
sudo docker network inspect edms_edms-net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
```

結果落在 `172.16.0.0/12`（`172.16.x.x`～`172.31.x.x`）內就用下方範本；若是 `192.168.x.x` 等其他網段，把範本的 `172.16.0.0/12` 改成實際網段。

**2-2. 取得白名單 IP**：須與 GCP firewall 5433 規則的來源一致。若與 TBMS 5432 那組相同，可直接列出沿用：

```bash
sudo grep -E '^hostssl .*clientcert=verify-full' /opt/tbms/postgres/pg_hba.conf
```

**2-3. 寫檔**

```bash
sudo nano /opt/edms/postgres/pg_hba.conf
```

```
# TYPE   DATABASE  USER  ADDRESS              METHOD
# --- 容器內初始化 / pg_isready / pg_dump（unix socket）---
local    all       all                        trust

# --- 容器內 loopback ---
host     all       all   127.0.0.1/32         scram-sha-256
host     all       all   ::1/128              scram-sha-256

# --- Docker 內部網路（edms-backend、migration）：維持密碼 ---
host     all       all   172.16.0.0/12        scram-sha-256

# --- 對外維護（白名單 IP）：強制 SSL + client 憑證 + 密碼 ---
# 每個白名單 IP 一行，貼上 2-2 的輸出
hostssl  all       all   <白名單 IP>/32       scram-sha-256 clientcert=verify-full

# --- 其餘一律拒絕 ---
host     all       all   0.0.0.0/0            reject
hostssl  all       all   0.0.0.0/0            reject
```

```bash
sudo chmod 644 /opt/edms/postgres/pg_hba.conf
```

> ⚠️ `local ... trust` 不可拿掉：`vm-deploy.sh` 的 `pg_isready` 與 `db-backup.sh` 的 `pg_dump` 都走 unix socket，拿掉會讓部署卡在「DB 未就緒」或備份失敗。

### 步驟 3：GCP firewall

已開通 tcp:5433（白名單來源）。容器尚未 publish 5433 前，外部連到的是沒人監聽的 port，不影響現況。

### 步驟 4：merge，等待自動部署

merge 後最慢 5 分鐘內 `vm-deploy.sh` 會以新的 compose 重建 `edms-db`。觀察：

```bash
tail -f /opt/edms/deploy.log
```

### 步驟 5：驗證

```bash
# ssl 已開、port 已 publish
sudo docker exec edms-db psql -U edms -d edms -c "SHOW ssl;"        # 應為 on
sudo docker exec edms-db psql -U edms -d edms -c "SHOW hba_file;"   # 應為 /etc/postgres/pg_hba.conf
sudo docker ps --filter name=edms-db                                # 應看到 0.0.0.0:5433->5432

# backend 仍正常（內部連線未受影響）
sudo docker logs --tail 30 edms-backend
curl -s -o /dev/null -w "%{http_code}\n" https://bms.tbsf.tw/edms/   # 應為 200
```

把 `client.crt`、`client.key`、`root.crt` 交給維護者（私鑰請走安全管道，勿進 git / 聊天室 / issue）。檔案為 root 所有，先複製到自己的家目錄再下載：

```bash
# bms-prod-02 上
mkdir -p ~/edms-certs
sudo cp /opt/edms/postgres/certs/{client.crt,client.key,root.crt} ~/edms-certs/
sudo chown "$(id -u):$(id -g)" ~/edms-certs/*
chmod 600 ~/edms-certs/client.key

# 下載到本機後，刪除 VM 家目錄的副本
rm -rf ~/edms-certs
```

---

## pgAdmin / DBeaver 連線設定

| 欄位 | 值 |
|---|---|
| Host | VM 公網 IP 或網域（須與 server 憑證 SAN 一致，同 TBMS） |
| Port | **`5433`** |
| Maintenance DB | `edms` |
| Username | `edms` |
| Password | `/opt/edms/.env.prod` 的 `POSTGRES_PASSWORD` |
| SSL mode | **verify-full** |
| Client certificate | `client.crt` |
| Client key | `client.key` |
| Root certificate | `root.crt`（**EDMS 的**，不是 TBMS 那張） |

> ⚠️ 兩套系統沿用同一組 `DP_` 表名，**連錯資料庫不會報錯**。pgAdmin 裡請把兩個連線取明顯不同的名稱（建議連線顏色也區分），動 `UPDATE` / `DELETE` 前先 `SELECT current_database();`。

---

## 回滾（關閉對外連線）

1. **關 firewall**（最快、最先做）：請有 GCP 權限的維運人員刪除 tcp:5433 那條規則
2. **撤回 compose**：revert `docker-compose.prod.yml` 的變更並 merge，`vm-deploy.sh` 會自動部署回「只走內部網路」的狀態（`vm-deploy.sh` 的前置檢查可一併 revert，或保留——檔案留在 VM 上無害）
3. 確認：`sudo docker ps --filter name=edms-db` 不再有 `0.0.0.0:5433->5432`

---

## 注意事項與常見坑

- **憑證過期**：server/client 憑證 825 天，到期前需重簽（重跑 1-2、1-3），之後 `sudo docker restart edms-db` 讓 server 憑證生效。**與 TBMS 的到期日不同**，兩者各自記到行事曆
- **server.key 權限**：`edms-db` 啟動報 `private key file ... has group or world access`，確認 `chown 999:999 server.key && chmod 600 server.key`
- **SAN 不符**：pgAdmin 報憑證驗證失敗，多半是連線 host 與 server 憑證 SAN 不一致（IP vs 網域）
- **改 pg_hba 不必重啟**：`sudo docker exec edms-db psql -U edms -d edms -c "SELECT pg_reload_conf();"` 即可生效
- **部署一直中止**：`deploy.log` 出現「缺少 /opt/edms/postgres/…」即步驟 1～2 未完成或檔案為空

## 與 TBMS 的差異

| 項目 | TBMS | EDMS | 理由 |
|---|---|---|---|
| 主機 port | 5432 | **5433** | 同一台 VM，5432 已被 `tbms-db` 佔 |
| CA | `TBMS-DB-CA` | **`EDMS-DB-CA`（獨立）** | 共用 CA 時，只要帳號名稱相同，一張 client 憑證就能通過兩邊的驗證；分開後各自換發、撤銷互不牽動。EDMS 為次級系統，其憑證外洩不應波及血庫 |
| 白名單 IP、對外位址 | 寫在文件內 | **只在 VM 上** | 本 repo 為 public |
| 部署觸發 | merge → CD 立即部署 | merge → timer 5 分鐘內拉取 | pull-based，見 [deployment.md](deployment.md) §0.2 |
| 前置未備妥時 | CD 部署失敗、`tbms-db` 停擺 | `vm-deploy.sh` 事先中止，現行服務不動 | 新增的前置檢查 |
