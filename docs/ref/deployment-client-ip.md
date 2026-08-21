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

`backend/.env` 之 `TRUSTED_PROXY_COUNT`（允許 0~8）：

> **語意**：請求到達應用前，會在 XFF **追加段落**的信任節點數 N。
> N 個節點各追加一段，其中**最左那段（即右數第 N 段）才是真實 client**；
> 更左邊的段落全部是用戶端自帶、不可信。故 N=1 取最右段、N=2 跳過最內層那段。

`DEBUG=false`（production）時**必須明示設定**，未設定則啟動即擋
（`app/core/config.py` 之 `_validate_trusted_proxy_count_explicit`）。原因見下方「設定過小」。

判定規則（`resolve_client_ip`）：

| 情況 | 結果 |
|------|------|
| `TRUSTED_PROXY_COUNT=0` | 忽略 XFF，用連線對端 IP |
| 無 XFF header | 用連線對端 IP |
| XFF 段數 **<** N | 用連線對端 IP（fail-safe） |
| 右數第 N 段非合法 IP、或為 scoped IPv6（`fe80::1%eth0`） | 用連線對端 IP（fail-safe） |
| 其餘 | 右數第 N 段（正規化：IPv6 縮寫與大小寫、IPv4-mapped 還原為 IPv4、去除 port） |

### ⚠️ N 必須精確等於實際追加段數——設過大**不是** fail-safe

這是本機制最容易致命的誤解：

- **設過小**：內層代理的 IP 被當成 client → 全體使用者共用一個限流桶
  （登入門檻變成「整個組織每分鐘 N 次」，早上一波登入就集體 429）、稽核 `SOURCE_IP`
  全為代理 IP 而失去意義。**是靜默塌縮，不會有錯誤訊息。**
- **設過大**：**偽造成立、不是退回連線對端**。段數由攻擊者可控——他只要自行前置
  段落把總段數墊到 N 以上，右數第 N 段就落在他填的值上：

  ```
  實際只有 1 台代理追加，卻設 TRUSTED_PROXY_COUNT=2：
    攻擊者送 X-Forwarded-For: 9.9.9.9
    → 抵達應用時為 "9.9.9.9, <代理追加的真實 client>"（2 段）
    → 右數第 2 段 = 9.9.9.9 = 攻擊者自填值被採信（等同原漏洞復活）
  ```

  「固定段數不看內容、只看位置，攻擊者前置多少段都無效」這個保證，**只在 N 精確
  等於實際追加段數時成立**。此界線已由測試
  `test_count_larger_than_actual_chain_is_forgeable` 釘住。

實務含意：**變更部署拓樸（加/拿掉 CDN、Tunnel、額外一層代理）時必須同步改這個值**，
且不可抱著「設大一點比較安全」的心態。驗證方式見文末檢查清單。

## 必要的 uvicorn 設定：關閉 proxy-headers

⚠️ **uvicorn 的 `--proxy-headers` 預設為開啟**（`uvicorn/config.py` 之 `proxy_headers=True`），
`fastapi dev` / `fastapi run`（`fastapi_cli`）亦同。開啟時 `ProxyHeadersMiddleware` 會在
請求進入應用前，依「信任 IP 清單從右掃描」的規則**直接覆寫 `scope["client"]`**——
亦即本應用視為不可偽造的連線對端會變成 XFF 推導值。

```bash
# 正式環境（反向代理後方）
uv run uvicorn main:app --host 127.0.0.1 --port 8001 --workers 1 --no-proxy-headers
```

三個必須知道的細節：

1. **該中間件只在「連線對端本身列於信任清單」時才生效**，預設清單為 `127.0.0.1`。
   在「nginx 容器 → backend 容器」的拓樸下，對端是容器 IP、不在清單內 → 中間件實際
   不生效。看到「client IP 全是 nginx 容器 IP」時，**正確做法是設
   `TRUSTED_PROXY_COUNT`，不是去放寬 uvicorn 的信任清單**。
2. **`--forwarded-allow-ips` 也可由環境變數 `FORWARDED_ALLOW_IPS` 指定**
   （CLI 未給時 uvicorn 讀該 env）。**絕不可設為 `*` 或內網 CIDR**：設 `*` 時
   uvicorn 無條件採信 XFF；設 CIDR 時攻擊者只要在自己的 XFF 尾端補一個該網段的 IP，
   即可讓 uvicorn 掃到他自填的段落並覆寫 `request.client`——此時應用端即使
   `TRUSTED_PROXY_COUNT=0`（無條件信任對端）也一併失守。
3. 啟動旗標與環境變數應固定在**受版控的部署產物**（compose / entrypoint / systemd unit）
   內，而非靠人記得手打。本 repo 目前尚無 compose / Dockerfile，建檔時須一併帶入
   `--no-proxy-headers`、`--workers 1` 與 `FORWARDED_ALLOW_IPS=`（空值＝全不信任）。

> client IP 判定只由應用層 `TRUSTED_PROXY_COUNT` 負責，保持**單一事實來源**。
> 不採用 uvicorn 的清單式機制作為替代方案——該演算法正是 #23 要修掉的形狀
> （見下方「為何不用信任 IP 清單」）。

### 為何不用信任 IP 清單

清單式（掃到第一個不在清單內的段落就當 client）可被攻擊者操弄：只要在 XFF 塞入
清單內的 IP（如 `127.0.0.1`），即可墊高被跳過的段數，最終取到攻擊者自填的值。
固定段數不看內容、只看位置（前提是 N 正確，見上）。

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

> ⚠️ **不要**用 `$proxy_add_x_forwarded_for`（append 語意），否則用戶端自帶的段落會被保留，
> 少一層縱深防禦（此時安全性完全依賴 N 正確）。

### 情境 B：Cloudflare Tunnel → nginx（README 架構總覽之部署形態）

上游 CF 會把真實 client IP 設入 XFF，此時 nginx **不可**用 `$remote_addr` 覆寫
（會把真實 client 蓋成 cloudflared 的 IP、永久遺失），必須 append：

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

抵達應用的 XFF 形如 `<用戶端自帶（不可信）>, <真實 client（CF 設）>, <cloudflared>`，
追加者為 CF 與 nginx 兩個節點 → 對應 `TRUSTED_PROXY_COUNT=2`。

⚠️ **情境 B 有一個必須由網路層補上的前提**：nginx 的連接埠**不可**從不信任網路直達。
若攻擊者能繞過 CF 直連 nginx 並自送 `X-Forwarded-For: 9.9.9.9`，nginx append 後恰為 2 段
→ 右數第 2 段 = `9.9.9.9` 被採信。EDMS 為內部平台、使用者本身就在 LAN 上，此前提
**不會自動成立**，必須明確設定（只允許 cloudflared 連 nginx）。

> 強化方向（本 issue 未實作，建議另案）：改讀 CF 專用 header `CF-Connecting-IP`
> 並驗證連線對端屬於 cloudflared，可去掉「段數正確」與「不可繞過」兩個脆弱前提。
> 若日後採用，需同步把 `TRUSTED_PROXY_COUNT` 設為 0 以免兩套機制並用。

## 三個容易忽略的前提

### 1. 應用連接埠不可從不信任網路直達

`TRUSTED_PROXY_COUNT` 是**固定值**：同一部署下，所有請求的 XFF 追加段數必須一致。
若應用同時可被「經代理」與「直連」兩種路徑存取，段數會浮動——**且如上所述，
段數浮動可能導向偽造成立而非 fail-safe**（例如直連時只需自備 N 段）。

作法：應用只綁 `127.0.0.1` 或容器內網、對外只開放代理的連接埠；情境 B 另須確保
nginx 也不可被繞過（見上）。

### 2. 單一 process 是限流正確性的前提

`SlidingWindowRateLimiter` 的計數狀態存在**行程記憶體內**（`app/core/rate_limit.py`）。
以多 worker 啟動時，每個 worker 各有一份計數 → 實際門檻被稀釋為 N 倍
（例：門檻 10 次/分、4 workers → 攻擊者實際可打 40 次/分）。

正式環境一律 `--workers 1`。日後要橫向擴充，須先把限流狀態外置（Redis 等）。

### 3. 不要用 Unix domain socket 作為代理到應用的通道

UDS（`proxy_pass http://unix:/…`）下 `request.client` 為 `None` → client IP 為 `None`
→ 限流 key 塌縮成單一 `unknown` 桶（全站共用門檻）、稽核 `SOURCE_IP` 全為 NULL。
若確有 UDS 需求，必須搭配 `TRUSTED_PROXY_COUNT >= 1`，使 IP 由 XFF 取得。

## 本機制未涵蓋的範圍

- **IPv6 位址輪替**：限流分桶用完整位址，持有 IPv6 /64 的攻擊者可每個請求換一個
  來源位址，不需偽造任何 header 即可打散限流桶。屬限流分桶粒度議題，另案處理。
- **log 中的個資**：`DP_AUDIT_LOG` 之外，各模組 `logger.exception()` 的遮罩狀況見
  `app/core/log_redaction.py` 的「未涵蓋的既有暴露面」段落。

## 部署檢查清單

- [ ] `backend/.env` 之 `TRUSTED_PROXY_COUNT` **明示設定**且與實際代理鏈段數一致
      （情境 A：1／情境 B：2；應用直接對外：0）
- [ ] uvicorn 以 `--no-proxy-headers --workers 1` 啟動，且旗標固定在受版控的部署產物內
- [ ] `FORWARDED_ALLOW_IPS` 未被設為 `*` 或內網 CIDR
- [ ] 反向代理依情境 A／B 設定 `X-Forwarded-For`
- [ ] 應用連接埠未對不信任網路開放；情境 B 另確認 nginx 不可繞過 CF 直達
- [ ] 未使用 UDS 作為代理通道（或已搭配 `TRUSTED_PROXY_COUNT >= 1`）
- [ ] **驗證「太低」**：帶 `X-Forwarded-For: 9.9.9.9` 打一次登入失敗，
      `DP_AUDIT_LOG.SOURCE_IP` 應為真實來源、**不是** `9.9.9.9`
- [ ] **驗證「太高」**：帶 `X-Forwarded-For: 9.9.9.9, 8.8.8.8`（前置 N−1 段偽造）
      重打一次，`SOURCE_IP` 仍應為真實來源；若出現 `9.9.9.9` 或 `8.8.8.8`
      表示 N 設得比實際段數大，**偽造已成立**，必須立即改小
