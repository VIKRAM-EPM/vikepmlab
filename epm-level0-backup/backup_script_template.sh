#!/usr/bin/env bash
# =============================================================================
# backup_script_template.sh
#
# Generic pattern for a "backup N targets, download them, purge old files,
# write a JSON status report" job. Adapt the actual per-target work (the
# TODO block below) to whatever you're backing up — a database, an app's
# export API, a cloud bucket sync, etc. Everything else (logging, status
# JSON, retention purge) works as-is.
#
# Contract with backup_notifier.py:
#   - The LAST line printed to stdout must be the path to the JSON status
#     file this script writes.
#   - Exit 0 on full success, non-zero if anything failed.
# =============================================================================
set -u

# ================== CONFIGURATION ==================
# Point these at your own paths. In a real project you'd likely source
# these from a small .conf file rather than hardcoding them here — same
# idea as config.yaml, just on the bash side.
TARGETS=("target_one" "target_two")     # whatever you're backing up
BACKUP_DIR="/path/to/backup/archive"
LOG_DIR="/path/to/logs"
RETENTION_DAYS=90

DT_STAMP="$(date +%Y-%m-%d-%H-%M-%S)"
LOG_FILE="$LOG_DIR/backup-${DT_STAMP}.log"
STATUS_FILE="$LOG_DIR/backup_status-${DT_STAMP}.json"

# ================== HELPERS ==================
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

write_status_json() {
  local overall_status="$1"
  local target_json=""
  for entry in "${TARGET_STATUS_ENTRIES[@]}"; do
    [[ -n "$target_json" ]] && target_json+=","
    target_json+="$entry"
  done

  cat > "$STATUS_FILE" <<EOF
{
  "overall_status": "${overall_status}",
  "run_date": "$(date '+%Y-%m-%d %H:%M:%S')",
  "hostname": "$(hostname)",
  "backup_dir": "${BACKUP_DIR}",
  "retention_days": ${RETENTION_DAYS},
  "log_file": "${LOG_FILE}",
  "purge_count": ${PURGE_COUNT:-0},
  "targets": [${target_json}]
}
EOF
  log "[INFO] Status JSON written: $STATUS_FILE"
}

mkdir -p "$BACKUP_DIR" "$LOG_DIR"

log "========================================"
log "Starting backup job"
log "Targets    : ${TARGETS[*]}"
log "Backup Dir : $BACKUP_DIR"
log "Retention  : $RETENTION_DAYS days"
log "========================================"

FAILED_TARGETS=()
TARGET_STATUS_ENTRIES=()

for TARGET in "${TARGETS[@]}"; do
  log "----------------------------------------"
  log "[INFO] Processing target: $TARGET"

  START_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
  START_EPOCH=$(date +%s)
  LOCAL_FILE_NAME="${TARGET}_backup_${DT_STAMP}.zip"
  LOCAL_FILE_PATH="$BACKUP_DIR/$LOCAL_FILE_NAME"
  STATUS="SUCCESS"
  NOTES=""

  # -------- TODO: replace this block with your real backup logic --------
  # Whatever command actually produces the backup file for $TARGET goes
  # here. It should end with a file sitting at $LOCAL_FILE_PATH.
  #
  #   your_backup_tool export "$TARGET" --output "$LOCAL_FILE_PATH"
  #
  # For demonstration purposes this just touches an empty file:
  touch "$LOCAL_FILE_PATH"
  RC=$?
  # ------------------------------------------------------------------------

  END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
  END_EPOCH=$(date +%s)
  ELAPSED="$(echo "scale=2; ($END_EPOCH - $START_EPOCH) / 60" | bc)mins"

  if [[ $RC -ne 0 ]] || [[ ! -s "$LOCAL_FILE_PATH" ]]; then
    log "[ERROR] Backup failed for $TARGET"
    STATUS="FAILURE"
    NOTES="Backup command failed or produced an empty file"
    FAILED_TARGETS+=("$TARGET")
    TARGET_STATUS_ENTRIES+=("{\"name\":\"$TARGET\",\"status\":\"$STATUS\",\"started\":\"$START_TIME\",\"completed\":\"$END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"N/A\",\"file_size\":\"N/A\",\"notes\":\"$NOTES\"}")
    continue
  fi

  FILE_SIZE="$(du -sh "$LOCAL_FILE_PATH" | cut -f1)"
  NOTES="Backup completed successfully"
  log "[INFO] $TARGET backed up: $FILE_SIZE -> $LOCAL_FILE_PATH"

  TARGET_STATUS_ENTRIES+=("{\"name\":\"$TARGET\",\"status\":\"$STATUS\",\"started\":\"$START_TIME\",\"completed\":\"$END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"$LOCAL_FILE_NAME\",\"file_size\":\"$FILE_SIZE\",\"notes\":\"$NOTES\"}")
done

# ================== PURGE OLD BACKUPS ==================
log "----------------------------------------"
log "[STEP] Purging backups older than $RETENTION_DAYS days"

PURGE_COUNT=0
while IFS= read -r -d '' OLD_FILE; do
  log "[PURGE] Removing old backup: $(basename "$OLD_FILE")"
  rm -f "$OLD_FILE"
  PURGE_COUNT=$((PURGE_COUNT + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -name "*_backup_*.zip" -mtime +${RETENTION_DAYS} -print0)

log "[INFO] Purged $PURGE_COUNT old backup file(s)."

# ================== SUMMARY ==================
OVERALL_STATUS="SUCCESS"
[[ ${#FAILED_TARGETS[@]} -gt 0 ]] && OVERALL_STATUS="FAILURE"

write_status_json "$OVERALL_STATUS"

log "Completed at $(date '+%Y-%m-%d %H:%M:%S') — overall status: $OVERALL_STATUS"
log "========================================"

# Last line of stdout — backup_notifier.py reads this
echo "$STATUS_FILE"

[[ ${#FAILED_TARGETS[@]} -gt 0 ]] && exit 1
exit 0