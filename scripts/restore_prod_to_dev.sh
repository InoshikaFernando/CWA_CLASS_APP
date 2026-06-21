#!/usr/bin/env bash
# restore_prod_to_dev.sh  (DigitalOcean)
# --------------------------------------
# Copies the PRODUCTION database into the DEV database on the same managed
# MySQL server, then migrates and sanitizes it — giving you a safe, realistic
# environment to trial data scripts (e.g. fix_duplicate_import_students.py).
#
# Run ON the droplet (it reads DB creds from the env files in /etc/cwa/):
#   sudo -u cwa bash scripts/restore_prod_to_dev.sh            # full run
#   sudo -u cwa bash scripts/restore_prod_to_dev.sh --dry-run  # preview only
#
# Safety:
#   * Refuses to run unless the DEST DB name contains "dev".
#   * Dumps with --set-gtid-purged=OFF (managed MySQL emits GTIDs otherwise).
#   * Only ever DROPs the dev DB, never prod.
set -euo pipefail

PROD_ENV="${PROD_ENV:-/etc/cwa/cwa.env}"
DEV_ENV="${DEV_ENV:-/etc/cwa/cwa-dev.env}"
DEV_APP_DIR="${DEV_APP_DIR:-/home/cwa/CWA_CLASS_APP_DEV}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true && echo "[DRY RUN] no changes will be written"

# ── Pull a KEY=value out of a systemd EnvironmentFile (no sourcing) ───────────
envget() { grep -E "^${2}=" "${1}" | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

SRC_NAME="$(envget "$PROD_ENV" DB_NAME)"
SRC_HOST="$(envget "$PROD_ENV" DB_HOST)"
SRC_PORT="$(envget "$PROD_ENV" DB_PORT)"
SRC_USER="$(envget "$PROD_ENV" DB_USER)"
SRC_PASS="$(envget "$PROD_ENV" DB_PASSWORD)"

DST_NAME="$(envget "$DEV_ENV" DB_NAME)"
DST_HOST="$(envget "$DEV_ENV" DB_HOST)"
DST_PORT="$(envget "$DEV_ENV" DB_PORT)"
DST_USER="$(envget "$DEV_ENV" DB_USER)"
DST_PASS="$(envget "$DEV_ENV" DB_PASSWORD)"

echo "Source (prod): ${SRC_USER}@${SRC_HOST}:${SRC_PORT}/${SRC_NAME}"
echo "Target (dev) : ${DST_USER}@${DST_HOST}:${DST_PORT}/${DST_NAME}"

# ── Guard: never touch a non-dev database ────────────────────────────────────
if [[ "${DST_NAME,,}" != *dev* ]]; then
    echo "ABORT: dev DB name '${DST_NAME}' does not contain 'dev'. Refusing to drop it."
    exit 1
fi
if [[ "${DST_NAME}" == "${SRC_NAME}" ]]; then
    echo "ABORT: source and target are the same database."
    exit 1
fi

DUMP_FILE="/tmp/prod_to_dev_$(date +%Y%m%d_%H%M%S).sql"

if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would: dump ${SRC_NAME} -> ${DUMP_FILE}, DROP+CREATE ${DST_NAME}, restore, migrate, sanitize."
    exit 0
fi

echo "==> Dumping prod -> ${DUMP_FILE}"
mysqldump -h "$SRC_HOST" -P "$SRC_PORT" -u "$SRC_USER" -p"$SRC_PASS" \
    --single-transaction --no-tablespaces --routines --triggers \
    --set-gtid-purged=OFF "$SRC_NAME" > "$DUMP_FILE"
echo "    $(du -sh "$DUMP_FILE" | cut -f1)"

echo "==> Recreating dev DB ${DST_NAME}"
mysql -h "$DST_HOST" -P "$DST_PORT" -u "$DST_USER" -p"$DST_PASS" \
    -e "DROP DATABASE IF EXISTS \`${DST_NAME}\`;
        CREATE DATABASE \`${DST_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "==> Restoring dump into ${DST_NAME}"
mysql -h "$DST_HOST" -P "$DST_PORT" -u "$DST_USER" -p"$DST_PASS" "$DST_NAME" < "$DUMP_FILE"
rm -f "$DUMP_FILE"

echo "==> Migrating dev (using dev env)"
cd "${DEV_APP_DIR}/cwa_classroom"
set -a; source "$DEV_ENV"; set +a
../venv/bin/python manage.py migrate --noinput

echo "==> Sanitizing dev (passwords/emails/Stripe)"
../venv/bin/python manage.py shell < "${SCRIPTS_DIR}/sanitize_test_db.py"

echo ""
echo "Done — ${DST_NAME} is a sanitized copy of prod."
echo "Trial the cleanup next:"
echo "  cd ${DEV_APP_DIR}/cwa_classroom && set -a && source ${DEV_ENV} && set +a"
echo "  ../venv/bin/python ../scripts/fix_duplicate_import_students.py --dry-run"
