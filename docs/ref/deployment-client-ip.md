# 部署層設定：client IP 可信度（速率限制與稽核日誌的前提）

> 來源：Issue #23（#16 T015 Security Review HIGH-1，CWE-348 / CWE-290 / OWASP A04）。
> 對應程式碼：`backend/app/core/client_ip.py`、`backend/main.py` 之 `client_ip_middleware`。

## 為什麼這件事屬於部署層

應用判定出的 client IP 同時餵給兩個安全控制：

| 消費者 | 用途 | 被偽造的後果 |
|--------|------|-------------|
| `rate_limit_by_ip`（`app/core/rate_limit.py`） | 限流的 IP 維度 | 每個請求換一個偽造 IP → 每次都是新桶 → **IP 維度限流失效，密碼噴灑不受保護** |
| `AuditLogService.log_action` 的 `source_ip` | 稽核軌跡 | 來源可偽造 → **污染稽核、可嫁禍他人** |

`X-Forwarded-For`（以下簡稱 XFF）最左段是「用戶端自稱」的來源，任何人都能填。
應用層因此採 **safe-by-default**：`TRUSTED_PROXY_COUNT=0`（預設）時完全忽略 XFF、
只用連線對端 IP。要正確取得真實 client IP，**必須由部署層提供保證**——本文件即該保證的規格。

## 應用層設定：`TRUSTED_PROXY_COUNT`

`backend/.env` 之 `TRUSTED_PROXY_COUNT`（預設 `0`，允許 0~8）：

> **語意**：請求到達應用前，會在 XFF **追加段落**的信任節點數 N。
> N 個節點各追加一段，其中**最左那段（即右數第 N 段）才是真實 client**；
> 更左邊的段落全部是用戶端自帶、不可信。故 N=1 取最右段、N=2 跳過最內層那段。

判定規則（`resolve_client_ip`）：

| 情況 | 結果 |
|------|------|
| `TRUSTED_PROXY_COUNT=0` | 忽略 XFF，用連線對端 IP |
| 無 XFF header | 用連線對端 IP |
| XFF 段數 < N（設定錯誤或請求繞過代理） | 用連線對端 IP（fail-safe） |
| 右數第 N 段非合法 IP | 用連線對端 IP（fail-safe） |
| 其餘 | 右數第 N 段（正規化後） |

**fail-safe 的取捨**：無法可靠判定時退回連線對端，代價是整組代理後方共用一個限流桶
（較嚴、可能誤擋），但不會讓偽造值打散限流或污染稽核。**寧可誤擋，不可放行。**

**為何用「固定段數」而非「信任 IP 清單」**：清單式（掃到第一個不在清單內的段落）
可被攻擊者操弄——只要在 XFF 塞入清單內的 IP（如 `127.0.0.1`）即可墊高跳過的段數，
最終取到攻擊者自填的值。固定段數不看內容、只看位置，攻擊者前置多少段都無效。

## 必要的 uvicorn 設定：關閉 `--proxy-headers`

⚠️ **uvicorn 的 `--proxy-headers` 預設為開啟**，且 `--forwarded-allow-ips` 預設 `127.0.0.1`。
開啟時 `ProxyHeadersMiddleware` 會在請求進入應用前，依「信任 IP 清單從右掃描」的規則
**直接覆寫 `scope["client"]`**——亦即本應用視為不可偽造的連線對端會變成 XFF 推導值，
且該推導採上述可被操弄的清單式演算法。

```bash
# 正式環境（反向代理後方）
uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers
```

> 一律 `--no-proxy-headers`，client IP 判定只由應用層 `TRUSTED_PROXY_COUNT` 負責，
> 保持**單一事實來源**。若確定要改用 uvicorn 的機制，則必須同時設
> `TRUSTED_PROXY_COUNT=0`，兩者不可並用。

## 必要的反向代理設定

### 情境 A：nginx 直接對外（無上游 CDN / Tunnel）

nginx **覆寫**（非 append）用戶端送來的 XFF，使其恆為單一段：

```nginx
location /api/ {
    proxy_pass http://edms-backend:8001;
    proxy_set_header X-Forwarded-For $remote_addr;   # 覆寫：丟棄用戶端自帶的 XFF
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}
```

對應 `TRUSTED_PROXY_COUNT=1`。此設定最強：偽造段在 nginx 就被丟棄，不會抵達應用。

> ⚠️ **不要**用 `$proxy_add_x_forwarded_for`（append 語意），否則用戶端自帶的段落會被保留。
> 本應用的固定段數判定仍擋得住，但少一層縱深防禦。

### 情境 B：Cloudflare Tunnel → nginx（README 架構總覽之部署形態）

上游 CF 會把真實 client IP 設入 XFF，此時 nginx **不可**用 `$remote_addr` 覆寫
（會把真實 client 蓋成 cloudflared 的 IP、永久遺失），必須 append：

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

抵達應用的 XFF 形如 `<用戶端自帶（不可信）>, <真實 client（CF 設）>, <cloudflared>`，
追加者為 CF 與 nginx 兩個節點 → 對應 `TRUSTED_PROXY_COUNT=2`。

> 進一步強化方向（本 issue 未實作）：改讀 CF 專用 header `CF-Connecting-IP`，
> 並在網路層確保只有 tunnel 能連到 nginx。若日後採用，需同步調整 `resolve_client_ip`
> 的來源，並把 `TRUSTED_PROXY_COUNT` 設為 0 避免兩套機制並用。

## 兩個容易忽略的前提

### 1. 應用連接埠不可從不信任網路直達

`TRUSTED_PROXY_COUNT` 是**固定值**：同一部署下，所有請求的 XFF 追加段數必須一致。
若應用同時可被「經代理」與「直連」兩種路徑存取，段數會浮動，直連請求的判定會退回
連線對端（fail-safe，不致誤信偽造值，但限流會被合併計算）。

作法：應用只綁 `127.0.0.1` 或容器內網、對外只開放代理的連接埠。

### 2. 單一 process 是限流正確性的前提

`SlidingWindowRateLimiter` 的計數狀態存在**行程記憶體內**（`app/core/rate_limit.py`）。
以多 worker 啟動時，每個 worker 各有一份計數 → 實際門檻被稀釋為 N 倍
（例：門檻 10 次/分、4 workers → 攻擊者實際可打 40 次/分）。

正式環境一律 `--workers 1`。日後要橫向擴充，須先把限流狀態外置（Redis 等）。

## 部署檢查清單

- [ ] `backend/.env` 之 `TRUSTED_PROXY_COUNT` 與實際代理鏈段數一致（情境 A：1／情境 B：2）
- [ ] uvicorn 以 `--no-proxy-headers` 啟動
- [ ] uvicorn 以 `--workers 1` 啟動
- [ ] 反向代理依情境 A／B 設定 `X-Forwarded-For`
- [ ] 應用連接埠未對不信任網路開放（只綁 127.0.0.1 / 容器內網）
- [ ] 驗證：帶 `X-Forwarded-For: 9.9.9.9` 打一次登入失敗，`DP_AUDIT_LOG.SOURCE_IP`
      應為真實來源、**不是** `9.9.9.9`
