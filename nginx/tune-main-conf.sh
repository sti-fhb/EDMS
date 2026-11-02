#!/bin/sh
# ============================================================
# 調整 nginx 主設定的連線格位（#833 B3），於映像建置時執行一次。
#
# 用法：sh tune-main-conf.sh /etc/nginx/nginx.conf
#
# 為什麼就地改而不整檔替換：映像跟著 `nginx:alpine` 浮動版號走（Dockerfile 以 `apk upgrade` 取安全更新），
# 整檔替換會讓官方預設檔日後的變動（pid 路徑等）靜默地沒跟上。這裡只動三行，**比對不到預期的原始樣式
# 就讓建置失敗**——官方改了格式時變成 CD 紅燈，而不是悄悄套用錯的設定。
#
# 改了什麼（數值關係見 nginx/rate-limit.conf 的下載上限說明）：
# - worker_processes auto → 2：auto 看的是**主機**核心數，不是容器的 `cpus: 0.5` 配額；多開 worker 只會互搶。
#   固定值也讓總格位可預測（4096 × 2）
# - worker_connections 1024 → 4096：每條下載佔 2 格（客戶端、後端各一），格位用完時新連線一律進不來、整站打不開
# - worker_rlimit_nofile 10240：每條連線一個描述子，另加 log 等；以非 root 執行只能調到容器的 hard limit 為止
#   （Docker 常見 hard 524288，足夠）。調不上去時 nginx 只記一筆 alert 照常啟動，部署後要確認，見 PR 說明
#
# 順帶確認（不改）：keepalive_timeout 65。front-proxy（TBMS repo 的 edge/conf）的上游 keepalive 依賴
# 「下游大於 60 秒」，官方預設改掉時要一併檢視那邊，所以這裡也當成建置前提。
#
# `backend/tests/unit/test_nginx_connection_limits.py` 以官方原檔的副本執行本腳本。
# ============================================================
set -eu

conf="$1"

expect() {
    grep -qx "$1" "$conf" || { echo "tune-main-conf: 找不到預期的原始設定「$1」，官方預設檔可能已改版，請對照後更新本腳本" >&2; exit 1; }
}

expect 'worker_processes  auto;'
expect '    worker_connections  1024;'
expect '    keepalive_timeout  65;'
expect 'events {'
if grep -q '^worker_rlimit_nofile' "$conf"; then
    echo "tune-main-conf: 已有 worker_rlimit_nofile，官方預設檔可能已改版" >&2
    exit 1
fi

# 只用 POSIX 的 sed 取代與 awk：映像內是 busybox，不依賴 GNU 擴充（如取代字串裡的 \n）
sed -i \
    -e 's/^worker_processes  auto;$/worker_processes  2;/' \
    -e 's/^    worker_connections  1024;$/    worker_connections  4096;/' \
    "$conf"
tmp="$(mktemp)"
awk '/^events \{$/ { print "worker_rlimit_nofile 10240;"; print "" } { print }' "$conf" > "$tmp"
cat "$tmp" > "$conf"
rm -f "$tmp"

grep -qx 'worker_processes  2;' "$conf"
grep -qx '    worker_connections  4096;' "$conf"
grep -qx 'worker_rlimit_nofile 10240;' "$conf"
