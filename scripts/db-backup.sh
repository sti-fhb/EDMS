#!/usr/bin/env bash
# ============================================================
# EDMS PostgreSQL 資料庫備份腳本
#
# 流程：
#   1. 容器內 pg_dump（custom format，自帶壓縮）
#   2. 容器內 pg_restore --list 驗證 dump 完整性（壞檔立即失敗）
#   3. docker cp 取出至本地 /opt/backup/edms-db
#   4. 上傳 GCS（VM Service Account 認證）
#   5. 本地只保留最近 3 份，GCS 端由 bucket lifecycle 自動清理
#
# 用法：
#   ./db-backup.sh                # 每日備份 → gs://.../daily/
#                                 # （台灣時間每月 1 日自動加存 monthly/）
#   ./db-backup.sh pre-migrate    # CD migration 前備份 → gs://.../pre-migrate/
#
# 前置需求（bms-prod-02 上）：
#   - docker（edms-db 容器運行中）
#   - gcloud，且 VM Service Account 具本 bucket 的寫入權限
#   - 環境變數 EDMS_BACKUP_BUCKET（於 /opt/edms/.env.prod 設定）
#
# ⚠️ **bucket 尚未建立時本腳本會直接失敗，這是刻意的**——CD 以「備份成功」作為
#    執行 migration 的前提，沒有可還原的快照就不動 schema。
#
# ⚠️ 本檔與 TBMS 的 scripts/db-backup.sh 是兩份獨立腳本（不同容器、不同 bucket
#    路徑）。修改其一時請評估另一份是否需同步。
#
# 建議的 GCS 保留策略（bucket lifecycle）：
#   - daily/       31 天自動刪除
#   - pre-migrate/ 31 天自動刪除
#   - monthly/     365 天自動刪除
#   另建議設 30 天 retention 鎖，防 VM 遭入侵時備份被一併銷毀。
# ============================================================

set -euo pipefail

# ---------- 設定 ----------
MODE="${1:-daily}"   # daily | pre-migrate
CONTAINER="edms-db"
DB_USER="${DB_BACKUP_USER:-edms}"
DB_NAME="${DB_BACKUP_NAME:-edms}"
BACKUP_ROOT="/opt/backup/edms-db"
BUCKET="${EDMS_BACKUP_BUCKET:-}"
LOG_FILE="${BACKUP_ROOT}/backup.log"
LOCAL_RETAIN=3
LOG_MAX_LINES=1000

if [[ "${MODE}" != "daily" && "${MODE}" != "pre-migrate" ]]; then
  echo "用法：$0 [daily|pre-migrate]" >&2
  exit 1
fi

if [[ -z "${BUCKET}" ]]; then
  echo "❌ 未設定 EDMS_BACKUP_BUCKET（應於 /opt/edms/.env.prod 指定，如 gs://edms-db-backup）" >&2
  echo "   備份是 migration 的前提，未設定即中止——不會在沒有快照的情況下改 schema。" >&2
  exit 1
fi

# ---------- 初始化 ----------
mkdir -p "${BACKUP_ROOT}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# 檔名以台灣時間命名（與團隊作業時區一致，避免 UTC 日期差一天的混淆）
TIMESTAMP=$(TZ='Asia/Taipei' date '+%Y%m%d-%H%M%S')
DUMP_NAME="edms-${MODE}-${TIMESTAMP}.dump"
LOCAL_FILE="${BACKUP_ROOT}/${DUMP_NAME}"
CONTAINER_TMP="/tmp/${DUMP_NAME}"

log "===== 開始 EDMS DB 備份（mode=${MODE}）====="

# ---------- 1. pg_dump（容器內產出，確保 TOC offset 完整）----------
log "執行 pg_dump（${DB_NAME}）..."
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" -Fc -f "${CONTAINER_TMP}" "${DB_NAME}"

# ---------- 2. 驗證 dump 完整性 ----------
# pg_restore --list 會讀取整份 TOC，壞檔（截斷/損毀）會直接失敗，
# 避免默默存下一份無法還原的廢檔
log "驗證 dump 完整性..."
docker exec "${CONTAINER}" pg_restore --list "${CONTAINER_TMP}" > /dev/null

# ---------- 3. 取出至本地 ----------
docker cp "${CONTAINER}:${CONTAINER_TMP}" "${LOCAL_FILE}"
docker exec "${CONTAINER}" rm -f "${CONTAINER_TMP}"
DUMP_SIZE=$(du -h "${LOCAL_FILE}" | cut -f1)
log "dump 完成：${LOCAL_FILE}（${DUMP_SIZE}）"

# ---------- 4. 上傳 GCS ----------
log "上傳至 ${BUCKET}/${MODE}/ ..."
gcloud storage cp "${LOCAL_FILE}" "${BUCKET}/${MODE}/" 2>&1 | tee -a "${LOG_FILE}"

# 台灣時間每月 1 日的 daily 備份，加存一份到 monthly/
if [[ "${MODE}" == "daily" && "$(TZ='Asia/Taipei' date '+%d')" == "01" ]]; then
  log "本日為每月 1 日，加存 monthly 備份..."
  gcloud storage cp "${LOCAL_FILE}" "${BUCKET}/monthly/" 2>&1 | tee -a "${LOG_FILE}"
fi

# ---------- 5. 本地清理 ----------
log "清理本地舊備份（${MODE} 保留 ${LOCAL_RETAIN} 份）..."
ls -1t "${BACKUP_ROOT}"/edms-"${MODE}"-*.dump 2>/dev/null | tail -n "+$((LOCAL_RETAIN + 1))" | xargs -r rm -f

if [ -f "${LOG_FILE}" ] && [ "$(wc -l < "${LOG_FILE}")" -gt "${LOG_MAX_LINES}" ]; then
  tail -n "${LOG_MAX_LINES}" "${LOG_FILE}" > "${LOG_FILE}.tmp"
  mv "${LOG_FILE}.tmp" "${LOG_FILE}"
fi

log "===== 備份完成（${DUMP_NAME}，${DUMP_SIZE}）====="
