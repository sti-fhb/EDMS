#!/bin/sh
set -e

# Migration 由部署腳本獨立執行（docker compose run --rm），不在 entrypoint 跑，
# 避免多副本同時啟動時的 race condition。

# ⚠️ 以下三項為 client IP 判定的安全前提，依 docs/ref/deployment-client-ip.md
#    「必要的 uvicorn 設定」節，**不得移除**：
#
# --no-proxy-headers
#   uvicorn 的 proxy_headers 預設為**開啟**，ProxyHeadersMiddleware 會依「信任 IP
#   清單從右掃描」直接覆寫 scope["client"]——本應用視為不可偽造的連線對端會變成
#   XFF 推導值。client IP 一律只由應用層的 TRUSTED_PROXY_COUNT 判定，保持單一事實來源。
#
# --workers 1
#   限流計數狀態存在行程記憶體內（app/core/rate_limit.py）。多 worker 時每個 worker
#   各有一份計數，實際門檻被稀釋為 N 倍。要橫向擴充須先把限流狀態外置。
#
# FORWARDED_ALLOW_IPS=（空值）
#   CLI 未給 --forwarded-allow-ips 時 uvicorn 會讀此環境變數。**絕不可設為 * 或內網
#   CIDR**：設 * 時無條件採信 XFF；設 CIDR 時攻擊者只要在 XFF 尾端補一個該網段的 IP，
#   即可讓 uvicorn 掃到自填段落並覆寫 request.client。此處明示為空＝全不信任。
export FORWARDED_ALLOW_IPS=

# --no-access-log：uvicorn 的 access log 之 request line 含 query string，
# 存取記錄改由 nginx 負責（已設為不記 query string，見 nginx/log-format.conf）。
exec uv run uvicorn main:app \
  --host 0.0.0.0 --port 8000 \
  --workers 1 \
  --no-proxy-headers \
  --no-access-log
