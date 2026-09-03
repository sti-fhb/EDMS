#!/usr/bin/env bash
# ============================================================
# EDMS VM 側部署腳本（pull-based）
#
# 安裝於 bms-prod-02，由 edms-deploy.timer 定期執行。
#
# 為何是 pull-based 而非由 GitHub 推：本 repo 為 public，若讓其 workflow 取得
# 這台機器的存取權，等於讓 public repo 的 CD 身分握有 root 等級權限（部署必需的
# docker group 等同 root，可讀 /opt/tbms/.env.prod、連上 tbms-db），而這台機器
# 同時跑著 TBMS 血庫系統。改為 VM 主動拉取後，GitHub 側的最大爆炸半徑收斂為
# 「能推一個映像到 edms-image」。詳見 docs/infra/deployment.md。
#
# 流程：
#   1. 取得 origin/main 的最新 commit short SHA
#   2. 確認 Artifact Registry 已有對應的映像 tag（沒有代表 CI 還在跑／失敗，
#      本輪跳過——避免拉到與程式碼不一致的半成品）
#   3. 與已部署的 SHA 比對，相同即結束
#   4. checkout 該 commit → pull 映像 → 起 DB → 備份 → migration → up -d
#      → 內部 health check → 記錄已部署 SHA
#
# 任一步失敗即中止並保留現狀（已部署 SHA 不更新），下一輪會重試。
#
# 前置需求：
#   /opt/edms/repo          此 repo 的 clone（public，不需認證）
#   /opt/edms/.env.prod     機密設定，含 EDMS_BACKUP_BUCKET
#   /opt/edms/data/postgres DB 資料
#   external network edms-proxy-net
#   gcloud（VM Service Account 需具 edms-image 讀取與備份 bucket 寫入權限）
# ============================================================

set -euo pipefail

REPO_DIR="/opt/edms/repo"
STATE_FILE="/opt/edms/deployed.sha"
LOG_FILE="/opt/edms/deploy.log"
AR_HOST="asia-east1-docker.pkg.dev"
AR_BASE="${AR_HOST}/blood-system-dev/edms-image"
# -p edms：專案名稱預設取自目錄名（/opt/edms/repo → "repo"），會產出 repo_edms-net
# 之類的名稱，與文件不一致且難辨識。明示固定。
COMPOSE=(docker compose -p edms -f docker-compose.yml -f docker-compose.prod.yml)

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# ⚠️ 整段包成函式再呼叫：bash 是**逐段讀取**腳本檔的，而本腳本執行中會
# `git checkout` 自己所在的 repo——若該 commit 改到本檔，bash 接下來會從
# 變動後的檔案讀取剩餘位元組，執行到錯亂的內容。包成函式可讓 bash 在呼叫前
# 就完整解析整個函式主體，把風險窗口收斂到最後一行。
main() {

cd "${REPO_DIR}"

# ---------- 1. 取得目標 commit ----------
git fetch --quiet origin main
TARGET_SHA=$(git rev-parse --short=7 origin/main)
CURRENT_SHA=$(cat "${STATE_FILE}" 2>/dev/null || echo "none")

if [ "${TARGET_SHA}" = "${CURRENT_SHA}" ]; then
  # 無變動時不寫 log，避免每輪都灌一行
  exit 0
fi

log "===== 偵測到新版本：${CURRENT_SHA} → ${TARGET_SHA} ====="

# ---------- 2. 確認映像已存在 ----------
# CI 尚未推完（或已失敗）時 tag 不存在，本輪跳過，等下一輪。
# 這一步是「程式碼與映像一致」的保證：只部署有對應映像的 commit。
if ! gcloud artifacts docker images describe \
      "${AR_BASE}/edms-backend:${TARGET_SHA}" >/dev/null 2>&1; then
  log "映像 edms-backend:${TARGET_SHA} 尚未就緒（CI 可能仍在執行或已失敗），本輪跳過"
  exit 0
fi
if ! gcloud artifacts docker images describe \
      "${AR_BASE}/edms-nginx:${TARGET_SHA}" >/dev/null 2>&1; then
  log "映像 edms-nginx:${TARGET_SHA} 尚未就緒，本輪跳過"
  exit 0
fi

# ---------- 3. 切到該 commit ----------
# 用 detached checkout：這份 clone 只供部署使用，不做開發
git checkout --quiet --detach "origin/main"
log "已切至 ${TARGET_SHA}"

export EDMS_IMAGE_TAG="${TARGET_SHA}"
cp /opt/edms/.env.prod .env.prod

# ---------- 4. 部署 ----------
# Artifact Registry 認證：IAM 授權（VM SA 的 artifactregistry.reader）只是 GCP 層的
# 許可，docker daemon 本身仍需持 token 才能 pull。token 有時效，故每次部署重取，
# 不依賴先前殘留的登入狀態。
log "登入 Artifact Registry..."
gcloud auth print-access-token | docker login -u oauth2accesstoken --password-stdin "$AR_HOST" >/dev/null

log "pull 映像..."
"${COMPOSE[@]}" pull --quiet

log "啟動 DB 並等待就緒..."
"${COMPOSE[@]}" up -d edms-db
DB_READY=0
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T edms-db pg_isready -U edms >/dev/null 2>&1; then
    DB_READY=1
    break
  fi
  sleep 2
done
if [ "${DB_READY}" -ne 1 ]; then
  log "❌ DB 未在 60 秒內就緒，中止"
  exit 1
fi

# 備份失敗即中止——沒有可還原的快照就不動 schema
# db-backup.sh 在**主機上**執行，而 .env.prod 是給 docker compose 的 env_file 用的
# ——那只注入容器內，主機的 shell 拿不到。故此處單獨取出 bucket 一項帶進環境；
# 刻意不整份 source，避免把 DB 密碼與金鑰灌進本行程及其所有子行程的環境。
EDMS_BACKUP_BUCKET=$(sed -n 's/^EDMS_BACKUP_BUCKET=//p' /opt/edms/.env.prod | tr -d '"'"'"'"' | head -1)
export EDMS_BACKUP_BUCKET
if [ -z "${EDMS_BACKUP_BUCKET}" ]; then
  log "❌ /opt/edms/.env.prod 未設定 EDMS_BACKUP_BUCKET，中止"
  exit 1
fi

log "migration 前備份..."
bash scripts/db-backup.sh pre-migrate

log "執行 migration..."
"${COMPOSE[@]}" run --rm edms-backend uv run alembic upgrade head

log "啟動所有服務..."
"${COMPOSE[@]}" up -d --remove-orphans

# ---------- 5. Health check ----------
# ⚠️ 必須用 127.0.0.1，不可用 localhost：edms-nginx 以非 root 執行，
# entrypoint 加不上 listen [::]:80，容器內只監聽 IPv4；BusyBox wget 解析
# localhost 會先試 ::1 而得到 Connection refused。
OK=0
for i in $(seq 1 6); do
  sleep 10
  if OUT=$(docker exec edms-nginx wget -q -O /dev/null http://127.0.0.1/health 2>&1); then
    log "✅ 內部健康檢查通過（嘗試 ${i}/6）"
    OK=1
    break
  fi
  log "嘗試 ${i}/6 未通過 — ${OUT:-（無輸出）}"
done

if [ "${OK}" -ne 1 ]; then
  log "❌ 部署後健康檢查失敗，已部署 SHA 不更新（下一輪會重試）"
  exit 1
fi

echo "${TARGET_SHA}" > "${STATE_FILE}"
log "===== 部署完成：${TARGET_SHA} ====="

docker image prune -f >/dev/null 2>&1 || true

# 截斷 log，保留最近 1000 行
if [ -f "${LOG_FILE}" ] && [ "$(wc -l < "${LOG_FILE}")" -gt 1000 ]; then
  tail -n 1000 "${LOG_FILE}" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "${LOG_FILE}"
fi

}

main "$@"
