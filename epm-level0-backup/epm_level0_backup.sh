#!/usr/bin/env bash
# =============================================================================
# epm_level0_backup.sh
#
# Author     : Vikram Kumar (Vik)
# Created    : 2026-08-16
# Tested     : Non-Prod & Prod EPM environment
# Deployed   : Fully Functional
#
# Disclaimer : Provided "as is", without warranty of any kind. Review and
#              test thoroughly in a non-production environment before
#              relying on it — you are responsible for verifying this
#              script's behavior against your own Oracle EPM environment,
#              credentials, and retention requirements before deployment.
# =============================================================================
#
# Takes a Level0 backup of any number of Essbase cubes in an Oracle EPM
# Cloud application — works for BSO, Hybrid, and ASO cubes alike, since
# `exportEssbaseData ... level=0` is valid for all three (per Oracle's
# EPM Automate docs: ASO cubes support level=0 only; BSO/Hybrid cubes
# support level=0 or level=All — this script always uses level=0).
#
# For each cube it:
#   1. Clears any stale zip left in the EPM outbox from a previous run
#   2. Runs the Level0 export
#   3. Downloads the resulting zip to a local backup folder
#   4. Verifies the download actually landed and isn't empty
#
# Then purges local backups older than RETENTION_DAYS and writes a JSON
# status file summarizing the run.
#
# Contract with backup_notifier.py:
#   - The LAST line printed to stdout must be the path to the JSON status
#     file this script writes.
#   - Exit 0 if every cube succeeded, non-zero if any cube failed.
# =============================================================================
set -u

# ================== CONFIGURATION ==================
# Point these at your own environment. In a real deployment you'd likely
# source these from a small .conf file kept out of version control,
# rather than hardcoding them here — especially APP_URL, USERNAME, and
# the PASSWORD file path.
EPM_BIN="/path/to/epmautomate/bin"
APP_URL="https://your-instance.epm.us-region-1.ocs.oraclecloud.com/HyperionPlanning"
USERNAME="your_service_account"
PASSWORD="/path/to/epmautomate/bin/epm_login.epw"   # encrypted password file — see epmautomate encrypt

# Cubes to back up — works for BSO, Hybrid, or ASO, any mix
CUBES=("CUBE_ONE" "CUBE_TWO")

# Local backup directory
BACKUP_DIR="/path/to/backup/archive"

# Retention period in days
RETENTION_DAYS=90

# Log directory
LOG_DIR="/path/to/logs"
DT_STAMP="$(date +%Y-%m-%d-%H-%M-%S)"
LOG_FILE="$LOG_DIR/EPM_Level0_Backup-${DT_STAMP}.log"
STATUS_FILE="$LOG_DIR/EPM_Level0_Backup_Status-${DT_STAMP}.json"

# Java & Path — EPM Automate needs Java on PATH
export JAVA_HOME="/path/to/jdk/"
export PATH=$JAVA_HOME/bin:$PATH

# ================== HELPER FUNCTIONS ==================
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

run_to_log() {
  "$@" 2>&1 | tee -a "$LOG_FILE"
  return "${PIPESTATUS[0]}"
}

write_status_json() {
  local overall_status="$1"
  local cube_json=""

  for entry in "${CUBE_STATUS_ENTRIES[@]}"; do
    [[ -n "$cube_json" ]] && cube_json+=","
    cube_json+="$entry"
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
  "cubes": [${cube_json}]
}
EOF
  log "[INFO] Status JSON written: $STATUS_FILE"
}

mkdir -p "$BACKUP_DIR" "$LOG_DIR"

# ================== MAIN SCRIPT ==================
log "========================================"
log "Starting EPM Level0 Backup"
log "Cubes      : ${CUBES[*]}"
log "Backup Dir : $BACKUP_DIR"
log "Retention  : $RETENTION_DAYS days"
log "========================================"

# ================== LOGIN ==================
log "Logging into EPM Cloud..."
run_to_log "$EPM_BIN/epmautomate.sh" login "$USERNAME" "$PASSWORD" "$APP_URL"
LOGIN_RC=$?
if [[ $LOGIN_RC -ne 0 ]]; then
  log "[ERROR] Login failed (rc=$LOGIN_RC). Aborting."
  CUBE_STATUS_ENTRIES=()
  PURGE_COUNT=0
  write_status_json "FAILURE"
  echo "$STATUS_FILE"
  exit 1
fi
log "[INFO] Login successful."

FAILED_CUBES=()
CUBE_STATUS_ENTRIES=()

# ================== LOOP OVER EACH CUBE ==================
for CUBE in "${CUBES[@]}"; do

  log "----------------------------------------"
  log "[INFO] Processing cube: $CUBE"

  EPM_ZIP_NAME="${CUBE}_level0.zip"
  LOCAL_ZIP_NAME="${CUBE}_level0_${DT_STAMP}.zip"
  LOCAL_ZIP_PATH="$BACKUP_DIR/$LOCAL_ZIP_NAME"
  EPM_ZIP_OUTBOX_PATH="outbox/${EPM_ZIP_NAME}"

  CUBE_START_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
  CUBE_START_EPOCH=$(date +%s)
  CUBE_STATUS="SUCCESS"
  CUBE_NOTES=""
  FILE_SIZE=""
  CUBE_END_TIME=""
  ELAPSED=""

  # -------- PRE-STEP: Clear any stale zip left in the outbox --------
  log "[PRE-STEP] Checking EPM outbox for existing $EPM_ZIP_NAME..."
  run_to_log "$EPM_BIN/epmautomate.sh" deletefile "$EPM_ZIP_OUTBOX_PATH"
  PRE_DELETE_RC=$?

  if [[ $PRE_DELETE_RC -ne 0 ]]; then
    log "[INFO] No existing file found in outbox — proceeding to export."
  else
    log "[INFO] Existing outbox file deleted: $EPM_ZIP_NAME — verifying..."
    LISTFILES_OUT=$("$EPM_BIN/epmautomate.sh" listfiles 2>/dev/null)
    if echo "$LISTFILES_OUT" | grep -qi "$EPM_ZIP_NAME"; then
      log "[ERROR] $EPM_ZIP_NAME still exists in outbox after delete attempt. Skipping cube: $CUBE"
      CUBE_END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
      CUBE_END_EPOCH=$(date +%s)
      ELAPSED="$(echo "scale=2; ($CUBE_END_EPOCH - $CUBE_START_EPOCH) / 60" | bc)mins"
      CUBE_STATUS="FAILURE"
      CUBE_NOTES="Pre-delete failed — zip still exists in outbox"
      FAILED_CUBES+=("$CUBE:prestep_delete_failed")
      CUBE_STATUS_ENTRIES+=("{\"cube\":\"$CUBE\",\"status\":\"$CUBE_STATUS\",\"started\":\"$CUBE_START_TIME\",\"completed\":\"$CUBE_END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"N/A\",\"file_size\":\"N/A\",\"local_path\":\"N/A\",\"notes\":\"$CUBE_NOTES\"}")
      continue
    fi
    log "[INFO] Verified outbox cleared — proceeding to export."
  fi

  # -------- STEP 1: Run Level0 Export --------
  # level=0 is valid for BSO, Hybrid, and ASO cubes alike (BSO/Hybrid also
  # support level=All, but this script is Level0-only by design).
  log "[STEP 1] Running Level0 export for cube: $CUBE"
  run_to_log "$EPM_BIN/epmautomate.sh" exportEssbaseData \
    "$CUBE" \
    "$EPM_ZIP_NAME" \
    level=0
  EXPORT_RC=$?

  if [[ $EXPORT_RC -ne 0 ]]; then
    log "[ERROR] Level0 export failed for $CUBE (rc=$EXPORT_RC). Skipping."
    CUBE_END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
    CUBE_END_EPOCH=$(date +%s)
    ELAPSED="$(echo "scale=2; ($CUBE_END_EPOCH - $CUBE_START_EPOCH) / 60" | bc)mins"
    CUBE_STATUS="FAILURE"
    CUBE_NOTES="Export failed rc=$EXPORT_RC"
    FAILED_CUBES+=("$CUBE:export_failed")
    CUBE_STATUS_ENTRIES+=("{\"cube\":\"$CUBE\",\"status\":\"$CUBE_STATUS\",\"started\":\"$CUBE_START_TIME\",\"completed\":\"$CUBE_END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"N/A\",\"file_size\":\"N/A\",\"local_path\":\"N/A\",\"notes\":\"$CUBE_NOTES\"}")
    continue
  fi
  log "[INFO] Level0 export completed for $CUBE."

  # -------- STEP 2: Download zip from EPM outbox to local backup folder --------
  log "[STEP 2] Downloading $EPM_ZIP_NAME from EPM outbox to $LOCAL_ZIP_PATH"
  run_to_log "$EPM_BIN/epmautomate.sh" downloadFile \
    "$EPM_ZIP_OUTBOX_PATH" \
    "$LOCAL_ZIP_PATH"
  DOWNLOAD_RC=$?

  if [[ $DOWNLOAD_RC -ne 0 ]]; then
    log "[ERROR] Download failed for $CUBE (rc=$DOWNLOAD_RC)."
    CUBE_END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
    CUBE_END_EPOCH=$(date +%s)
    ELAPSED="$(echo "scale=2; ($CUBE_END_EPOCH - $CUBE_START_EPOCH) / 60" | bc)mins"
    CUBE_STATUS="FAILURE"
    CUBE_NOTES="Download failed rc=$DOWNLOAD_RC"
    FAILED_CUBES+=("$CUBE:download_failed")
    CUBE_STATUS_ENTRIES+=("{\"cube\":\"$CUBE\",\"status\":\"$CUBE_STATUS\",\"started\":\"$CUBE_START_TIME\",\"completed\":\"$CUBE_END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"N/A\",\"file_size\":\"N/A\",\"local_path\":\"N/A\",\"notes\":\"$CUBE_NOTES\"}")
    continue
  fi
  log "[INFO] Downloaded successfully: $LOCAL_ZIP_NAME"

  # -------- STEP 3: Verify downloaded file exists and is non-empty --------
  if [[ ! -s "$LOCAL_ZIP_PATH" ]]; then
    log "[ERROR] Downloaded file is missing or empty: $LOCAL_ZIP_PATH"
    CUBE_END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
    CUBE_END_EPOCH=$(date +%s)
    ELAPSED="$(echo "scale=2; ($CUBE_END_EPOCH - $CUBE_START_EPOCH) / 60" | bc)mins"
    CUBE_STATUS="FAILURE"
    CUBE_NOTES="File empty after download"
    FAILED_CUBES+=("$CUBE:download_empty")
    CUBE_STATUS_ENTRIES+=("{\"cube\":\"$CUBE\",\"status\":\"$CUBE_STATUS\",\"started\":\"$CUBE_START_TIME\",\"completed\":\"$CUBE_END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"$LOCAL_ZIP_NAME\",\"file_size\":\"0\",\"local_path\":\"$LOCAL_ZIP_PATH\",\"notes\":\"$CUBE_NOTES\"}")
    continue
  fi

  FILE_SIZE="$(du -sh "$LOCAL_ZIP_PATH" | cut -f1)"
  log "[INFO] Verified local backup file: $FILE_SIZE — $LOCAL_ZIP_PATH"
  log "[INFO] Zip retained in EPM outbox: $EPM_ZIP_OUTBOX_PATH"

  # -------- SUCCESS: Record status --------
  CUBE_NOTES="Backup downloaded successfully — zip retained in EPM outbox"
  CUBE_END_TIME="$(date '+%Y-%m-%d %H:%M:%S')"
  CUBE_END_EPOCH=$(date +%s)
  ELAPSED="$(echo "scale=2; ($CUBE_END_EPOCH - $CUBE_START_EPOCH) / 60" | bc)mins"

  CUBE_STATUS_ENTRIES+=("{\"cube\":\"$CUBE\",\"status\":\"$CUBE_STATUS\",\"started\":\"$CUBE_START_TIME\",\"completed\":\"$CUBE_END_TIME\",\"elapsed\":\"$ELAPSED\",\"local_file\":\"$LOCAL_ZIP_NAME\",\"file_size\":\"$FILE_SIZE\",\"local_path\":\"$LOCAL_ZIP_PATH\",\"notes\":\"$CUBE_NOTES\"}")

done

# ================== LOGOUT ==================
run_to_log "$EPM_BIN/epmautomate.sh" logout || true
log "[INFO] Logged out from EPM Cloud."

# ================== PURGE FILES OLDER THAN RETENTION_DAYS ==================
log "========================================"
log "[STEP] Purging local backups older than $RETENTION_DAYS days from $BACKUP_DIR"

PURGE_COUNT=0
while IFS= read -r -d '' OLD_FILE; do
  log "[PURGE] Removing old backup: $(basename "$OLD_FILE")"
  rm -f "$OLD_FILE"
  PURGE_COUNT=$((PURGE_COUNT + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -name "*_level0_*.zip" -mtime +${RETENTION_DAYS} -print0)

if [[ $PURGE_COUNT -eq 0 ]]; then
  log "[INFO] No backups older than $RETENTION_DAYS days found. Nothing purged."
else
  log "[INFO] Purged $PURGE_COUNT old backup file(s)."
fi

# ================== SUMMARY ==================
OVERALL_STATUS="SUCCESS"
[[ ${#FAILED_CUBES[@]} -gt 0 ]] && OVERALL_STATUS="FAILURE"

write_status_json "$OVERALL_STATUS"

log "Completed at $(date '+%Y-%m-%d %H:%M:%S') — overall status: $OVERALL_STATUS"
log "========================================"

# Last line of stdout — backup_notifier.py reads this
echo "$STATUS_FILE"

[[ ${#FAILED_CUBES[@]} -gt 0 ]] && exit 1
exit 0