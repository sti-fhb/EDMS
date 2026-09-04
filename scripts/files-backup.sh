#!/usr/bin/env bash
# ============================================================
# EDMS 檔案備份：DM 受控文件與 ET 影音教材 → GCS
#
# 與 db-backup.sh 互補：後者只 dump 資料庫。少了本腳本，磁碟損毀時會變成
# 「資料庫還原了，但每份文件都指向不存在的檔案」。
#
# 用 rsync 而非每日全量複製：只上傳有變動的物件，教材類大檔不會重複傳。
#
# ⚠️ **刻意不加 --delete-unmatched-destination-objects**：
#    來源端誤刪時，備份端仍留有副本可救。代價是 GCS 用量只增不減，
#    需定期人工檢視。若日後改為鏡像語意，要同時想清楚誤刪的救援路徑。
#
# 前置：EDMS_BACKUP_BUCKET（/opt/edms/.env.prod）、VM SA 具 bucket 寫入權
# ============================================================

set -euo pipefail

BUCKET="${EDMS_BACKUP_BUCKET:-}"
LOG_FILE="/opt/backup/edms-db/files-backup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"; }

if [[ -z "${BUCKET}" ]]; then
  echo "❌ 未設定 EDMS_BACKUP_BUCKET" >&2
  exit 1
fi

mkdir -p "$(dirname "${LOG_FILE}")"
log "===== 開始檔案備份 ====="

for dir in dm_files et_videos; do
  src="/opt/edms/data/${dir}"
  if [[ ! -d "${src}" ]]; then
    log "略過 ${dir}：來源目錄不存在"
    continue
  fi
  log "同步 ${dir} → ${BUCKET}/files/${dir}/ ..."
  gcloud storage rsync -r "${src}" "${BUCKET}/files/${dir}" 2>&1 | tail -3 | tee -a "${LOG_FILE}"
done

log "===== 檔案備份完成 ====="

if [ -f "${LOG_FILE}" ] && [ "$(wc -l < "${LOG_FILE}")" -gt 1000 ]; then
  tail -n 1000 "${LOG_FILE}" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "${LOG_FILE}"
fi
