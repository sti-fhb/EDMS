# ── Stage 1：建置前端靜態檔案 ──────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# pnpm 對齊 repo 根目錄 package.json 的 packageManager 設定。
# 升版時三處要同步：root package.json、本檔、CI 的 pnpm/action-setup。
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate

# 先複製依賴檔案（利用 Docker layer cache）
COPY frontend/package.json frontend/pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

# 複製前端原始碼並建置
COPY frontend/ .

# VITE_ 變數需在 build 時注入（baked into the bundle）
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# 站台掛載路徑。院內封閉網路只給單一 IP、單一 port，EDMS 與 TBMS 靠 URL 路徑
# 前綴區分，交付包的 build 須傳 --build-arg VITE_BASE_PATH=/edms/
# 並同時把 VITE_API_BASE_URL 設為 /edms/api。
# 預設 "/" —— GCP 雲端版行為不變。值必須以斜線結尾。
# ⚠️ 兩者只改其一即壞：只改 base 會讓 API 打到 /api（proxy 剝不到前綴、404）；
#    只改 API base 會讓靜態資源仍指向 /assets（proxy 剝不到前綴、整頁空白）。
# 詳見 TBMS repo 的 docs/infra/onprem-path-routing.md §5.1。
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH

RUN pnpm build

# ── Stage 2：nginx serve 靜態檔案 ──────────────────────────────
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
# 00- 字首確保 limit_req_zone 與 log_format／map（皆為 http 層）早於 default.conf 載入
COPY nginx/rate-limit.conf /etc/nginx/conf.d/00-rate-limit.conf
COPY nginx/log-format.conf /etc/nginx/conf.d/00-log-format.conf
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/security-headers.conf

# 建立 nginx cache 目錄並授權給 nginx 使用者
RUN mkdir -p /var/cache/nginx/client_temp \
             /var/cache/nginx/proxy_temp \
             /var/cache/nginx/fastcgi_temp \
             /var/cache/nginx/uwsgi_temp \
             /var/cache/nginx/scgi_temp && \
    chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/run && \
    chown -R nginx:nginx /run

# 以 nginx 內建的非 root 使用者執行。
# ⚠️ 副作用：entrypoint 的 10-listen-on-ipv6-by-default.sh 因此改不動 root 擁有的
# default.conf，容器內只監聽 IPv4。凡是「從容器內部打自己」的檢查（CD health check、
# compose healthcheck、監控腳本）一律要用 127.0.0.1，不可用 localhost——後者會先試
# ::1 而得到 Connection refused。
USER nginx

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
