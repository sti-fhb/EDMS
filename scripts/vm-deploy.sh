#!/usr/bin/env bash
# ============================================================
# EDMS VM 側部署腳本（pull-based）
#
# 安裝於 <PROD_VM>，由 edms-deploy.timer 定期執行。
#
# 為何是 pull-based 而非由 GitHub 推：本 repo 為 public，若讓其 workflow 取得
# 這台機器的存取權，等於讓 public repo 的 CD 身分握有 root 等級權限（部署必需的
# docker group 等同 root，可讀 /opt/tbms/.env.prod、連上 tbms-db），而這台機器
# 同時跑著 TBMS 血庫系統。改為 VM 主動拉取後，GitHub 側的最大爆炸半徑收斂為
# 「能推一個映像到 edms-image」。詳見 docs/infra/deployment.md。
#
# 流程：
#   1. 取得 origin/main 的最新 commit，與已部署的 SHA 比對，相同即結束
#   2. 在「已部署 → origin/main」之間由新到舊找第一個 Artifact Registry 已有
#      映像的 commit（只動 docs／.github 等的 commit 不會觸發 CD、永遠沒有映像，
#      不能只看 origin/main）；都沒有代表 CI 還在跑／失敗，本輪跳過
#   3. checkout 該 commit → pull 映像 → 起 DB → 備份 → migration → up -d
#      → 內部 health check → 記錄已部署 SHA
#
# 任一步失敗即中止並保留現狀（已部署 SHA 不更新），下一輪會重試。
#
# 前置需求：
#   /opt/edms/repo          此 repo 的 clone（public，不需認證）
#   /opt/edms/.env.prod     機密設定，含 EDMS_BACKUP_BUCKET
#   /opt/edms/data/postgres DB 資料
#   /opt/edms/postgres/     DB 對外連線的憑證與 pg_hba.conf（見 TBMS repo 的 docs/infra/db-external-access.md §二）
#   external network edms-proxy-net
#   gcloud（VM Service Account 需具 edms-image 讀取與備份 bucket 寫入權限）
# ============================================================

set -euo pipefail

REPO_DIR="/opt/edms/repo"
STATE_FILE="/opt/edms/deployed.sha"
# 已記過「等待映像」的 origin/main SHA，同一個 HEAD 只寫一次 log
PENDING_FILE="/opt/edms/pending.sha"
LOG_FILE="/opt/edms/deploy.log"
# 已部署 SHA 不在 origin/main 歷史上（首次部署、force-push）時，往回找的上限
MAX_LOOKBACK=20
AR_HOST="asia-east1-docker.pkg.dev"
AR_BASE="${AR_HOST}/blood-system-dev/edms-image"
# -p edms：專案名稱預設取自目錄名（/opt/edms/repo → "repo"），會產出 repo_edms-net
# 之類的名稱，與文件不一致且難辨識。明示固定。
COMPOSE=(docker compose -p edms -f docker-compose.yml -f docker-compose.prod.yml)

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

image_exists() {
  gcloud artifacts docker images describe "${AR_BASE}/$1" >/dev/null 2>&1
}

# ⚠️ 整段包成函式再呼叫：bash 是**逐段讀取**腳本檔的，而本腳本執行中會
# `git checkout` 自己所在的 repo——若該 commit 改到本檔，bash 接下來會從
# 變動後的檔案讀取剩餘位元組，執行到錯亂的內容。包成函式可讓 bash 在呼叫前
# 就完整解析整個函式主體，把風險窗口收斂到最後一行。
main() {

cd "${REPO_DIR}"

# ---------- 1. 取得 origin/main ----------
git fetch --quiet origin main
HEAD_SHA=$(git rev-parse --short=7 origin/main)
CURRENT_SHA=$(cat "${STATE_FILE}" 2>/dev/null || echo "none")

if [ "${HEAD_SHA}" = "${CURRENT_SHA}" ]; then
  # 無變動時不寫 log，避免每輪都灌一行
  exit 0
fi

# ---------- 2. 找出最新一個有映像的 commit ----------
# cd.yml 的 paths-ignore 會跳過只動 docs／*.md／.claude／.github 的 push，這類
# commit 永遠不會有映像。若只看 origin/main，HEAD 落在這類 commit 時會一直等
# 下去，直到下一個改到程式碼的 commit 推上來。故改為由新到舊找第一個兩個映像
# 都齊全的 commit——它與 HEAD 的差異只在被 paths-ignore 的檔案，部署它即是部署
# 最新程式碼。
#
# 不依 paths-ignore 規則推算「哪個 commit 該有映像」：同一次 push 含多個 commit
# 時 CD 只建最後一個，依路徑推算會挑到沒有映像的 commit。以 AR 實際有無為準。
#
# 仍保證「程式碼與映像一致」：只部署有對應映像的 commit，並 checkout 該 commit。
if [ "${CURRENT_SHA}" != "none" ] \
   && git merge-base --is-ancestor "${CURRENT_SHA}" origin/main 2>/dev/null; then
  CANDIDATES=$(git rev-list --first-parent "${CURRENT_SHA}..origin/main")
else
  CANDIDATES=$(git rev-list --first-parent --max-count="${MAX_LOOKBACK}" origin/main)
fi

TARGET_SHA=""
for sha in ${CANDIDATES}; do
  short=${sha:0:7}
  if image_exists "edms-backend:${short}" && image_exists "edms-nginx:${short}"; then
    TARGET_SHA="${short}"
    break
  fi
done

if [ -z "${TARGET_SHA}" ] || [ "${TARGET_SHA}" = "${CURRENT_SHA}" ]; then
  # CI 尚未推完（或已失敗）。同一個 HEAD 只記一次，避免每輪灌 log
  if [ "$(cat "${PENDING_FILE}" 2>/dev/null)" != "${HEAD_SHA}" ]; then
    log "origin/main 已到 ${HEAD_SHA}，但 ${CURRENT_SHA} 之後尚無可部署的映像（CI 可能仍在執行或已失敗），等待中"
    echo "${HEAD_SHA}" > "${PENDING_FILE}"
  fi
  exit 0
fi

if [ "${TARGET_SHA}" = "${HEAD_SHA}" ]; then
  log "===== 偵測到新版本：${CURRENT_SHA} → ${TARGET_SHA} ====="
else
  log "===== 偵測到新版本：${CURRENT_SHA} → ${TARGET_SHA}（origin/main 為 ${HEAD_SHA}，其後的 commit 無映像）====="
fi

# ---------- 3. 切到該 commit ----------
# 用 detached checkout：這份 clone 只供部署使用，不做開發
git checkout --quiet --detach "${TARGET_SHA}"
log "已切至 ${TARGET_SHA}"

export EDMS_IMAGE_TAG="${TARGET_SHA}"
cp /opt/edms/.env.prod .env.prod

# ---------- 4. 部署 ----------
# Artifact Registry 認證：IAM 授權（VM SA 的 artifactregistry.reader）只是 GCP 層的
# 許可，docker daemon 本身仍需持 token 才能 pull。token 有時效，故每次部署重取，
# 不依賴先前殘留的登入狀態。
log "登入 Artifact Registry..."
gcloud auth print-access-token | docker login -u oauth2accesstoken --password-stdin "$AR_HOST" >/dev/null

# DB 對外連線（docker-compose.prod.yml 的 edms-db）依賴主機上的憑證與 pg_hba。
# 缺任一個時 up -d edms-db 會把現行 DB 停掉、新容器卻起不來——等於整套 EDMS
# 停擺。故在動到任何容器之前先擋下。產生方式見 TBMS repo 的 docs/infra/db-external-access.md §二。
for f in /opt/edms/postgres/certs/server.crt /opt/edms/postgres/certs/server.key \
         /opt/edms/postgres/certs/root.crt /opt/edms/postgres/pg_hba.conf; do
  if [ ! -s "${f}" ]; then
    log "❌ 缺少 ${f}（DB 對外連線前置未完成），中止；現行服務未受影響"
    exit 1
  fi
done

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
# 容器內指令一律以絕對路徑 /app/.venv/bin/ 執行：映像不含 uv（新舊映像皆有此路徑）。
"${COMPOSE[@]}" run --rm edms-backend /app/.venv/bin/alembic upgrade head

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
# HEAD 之後的 commit 本就沒有映像，標記為已記過，下一輪不再寫「等待中」
echo "${HEAD_SHA}" > "${PENDING_FILE}"
log "===== 部署完成：${TARGET_SHA} ====="

docker image prune -f >/dev/null 2>&1 || true

# 截斷 log，保留最近 1000 行
if [ -f "${LOG_FILE}" ] && [ "$(wc -l < "${LOG_FILE}")" -gt 1000 ]; then
  tail -n 1000 "${LOG_FILE}" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "${LOG_FILE}"
fi

}

main "$@"
