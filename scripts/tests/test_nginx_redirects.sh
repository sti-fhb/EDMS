#!/usr/bin/env bash
# edms-nginx 的轉址行為測試。需 docker；無 docker 時 SKIP。
#
# 本層的轉址一律送根相對的 Location（/assets/、/api/x/），由 front-proxy 補回 /edms 前綴：
#   - 目錄補尾斜線（try_files $uri $uri/）：absolute_redirect off
#   - 後端轉址（FastAPI 預設 redirect_slashes）：proxy_redirect http://edms-backend/ /
# 以假後端模擬後者：回 307 http://edms-backend$uri/（後端收到的 Host 固定為 edms-backend）。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
NGINX="$REPO/nginx"

fail=0
check() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

if ! docker info >/dev/null 2>&1 || ! command -v curl >/dev/null; then
  echo "SKIP (docker or curl not available)"; exit 0
fi
export MSYS_NO_PATHCONV=1
winpath() { if command -v cygpath >/dev/null; then cygpath -m "$1"; else echo "$1"; fi; }

TMP="$(mktemp -d)" && [ -n "$TMP" ] || { echo "mktemp failed"; exit 1; }
NET="edms-redirect-test-$$"
CIDS=()
cleanup() { for c in "${CIDS[@]}"; do docker rm -f "$c" >/dev/null 2>&1; done; docker network rm "$NET" >/dev/null 2>&1; rm -rf "$TMP"; }
trap cleanup EXIT
docker network create "$NET" >/dev/null

# 假後端（別名 edms-backend:8000）
cat > "$TMP/stub-backend.conf" <<'CONF'
server { listen 8000; location / { return 307 http://edms-backend$uri/$is_args$args; } }
CONF
CIDS+=("$(docker run -d --network "$NET" --network-alias edms-backend \
  -v "$(winpath "$TMP/stub-backend.conf"):/etc/nginx/conf.d/default.conf:ro" nginx:alpine)")

# 前端產物：一個 index.html（含 CSP nonce 佔位）與一個實體目錄 assets/
mkdir -p "$TMP/html/assets"
printf '<!doctype html><meta name="csp-nonce" content="__CSP_NONCE__" />\n' > "$TMP/html/index.html"
printf 'x' > "$TMP/html/assets/app.js"

# 與 nginx/Dockerfile 相同的檔案配置
cid="$(docker run -d --network "$NET" -p 127.0.0.1::80 \
  -v "$(winpath "$NGINX/rate-limit.conf"):/etc/nginx/conf.d/00-rate-limit.conf:ro" \
  -v "$(winpath "$NGINX/log-format.conf"):/etc/nginx/conf.d/00-log-format.conf:ro" \
  -v "$(winpath "$NGINX/nginx.conf"):/etc/nginx/conf.d/default.conf:ro" \
  -v "$(winpath "$NGINX/security-headers.conf"):/etc/nginx/security-headers.conf:ro" \
  -v "$(winpath "$NGINX/api-proxy.conf"):/etc/nginx/api-proxy.conf:ro" \
  -v "$(winpath "$NGINX/api-upload.conf"):/etc/nginx/api-upload.conf:ro" \
  -v "$(winpath "$TMP/html"):/usr/share/nginx/html:ro" \
  nginx:alpine)"
CIDS+=("$cid")
PORT="$(docker port "$cid" 80/tcp | head -1 | tr -d '\r' | sed -E 's/.*:([0-9]+)$/\1/')"

# 回應的狀態碼與 Location（去 CR）；其餘參數原樣傳給 curl
resp() { local path="$1"; shift; curl -s -o "$(winpath "$TMP")/body" -D - --max-time 5 "$@" "http://127.0.0.1:$PORT$path" | tr -d '\r'; }
status_of() { resp "$@" | head -1 | awk '{print $2}'; }
location_of() { resp "$@" | grep -i '^Location:' | sed -E 's/^[Ll]ocation:[[:space:]]*//'; }
wait_up() { for _ in $(seq 1 20); do [ "$(status_of /)" = 200 ] && return 0; sleep 0.5; done; return 1; }

echo "== edms-nginx"
check "nginx up" 'wait_up'

echo "== directory without trailing slash"
check "GET /assets is 301" '[ "$(status_of /assets)" = 301 ]'
check "GET /assets redirects to relative /assets/" '[ "$(location_of /assets)" = "/assets/" ]'
check "Location is relative regardless of request Host" '[ "$(location_of /assets -H "Host: other.example")" = "/assets/" ]'

echo "== backend redirect (redirect_slashes)"
check "GET /api/x is 307" '[ "$(status_of /api/x)" = 307 ]'
check "GET /api/x redirects to relative /api/x/" '[ "$(location_of /api/x)" = "/api/x/" ]'
check "query string kept" '[ "$(location_of "/api/x?q=1")" = "/api/x/?q=1" ]'
check "Location uses relative path for backend redirect" '! resp /api/x | grep -qi "edms-backend"'

echo "== unaffected"
check "SPA root still 200" '[ "$(status_of /)" = 200 ]'
check "static file still 200" '[ "$(status_of /assets/app.js)" = 200 ]'

[ "$fail" = 0 ] && echo "PASS" || echo "FAILED"
exit "$fail"
