#!/usr/bin/env bash
# prepare_local_db.sh
# -------------------
# Import a prod SQL backup to local MySQL and sanitise it for development:
#   1. Import the SQL dump
#   2. Reset all user emails  → wlhtestmails+<username>@gmail.com
#   3. Reset all passwords    → Password1!
#   4. Reset Stripe price IDs → test/dev price IDs
#   5. Clear sessions
#
# Usage:
#   bash scripts/prepare_local_db.sh /path/to/backup.sql
#
# Must be run from the repo root.

set -euo pipefail

SQL_FILE="${1:-}"

if [[ -z "$SQL_FILE" ]]; then
  echo "Usage: bash scripts/prepare_local_db.sh /path/to/backup.sql"
  exit 1
fi

if [[ ! -f "$SQL_FILE" ]]; then
  echo "ERROR: File not found: $SQL_FILE"
  exit 1
fi

# ── Config ────────────────────────────────────────────────────────────────────
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASS="${DB_PASS:-root}"
DB_NAME="${DB_NAME:-cwa_classroom}"

MANAGE_DIR="${MANAGE_DIR:-$(dirname "$0")/../cwa_classroom}"
MYSQL_BIN="${MYSQL_BIN:-/c/Program Files/MySQL/MySQL Server 8.0/bin/mysql}"
mysql_cmd() { "${MYSQL_BIN}" -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" -p"${DB_PASS}" "${DB_NAME}" "$@"; }
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "======================================================"
echo " Preparing local database: ${DB_NAME}"
echo "======================================================"
echo ""

# ── Step 1: Import the SQL dump ───────────────────────────────────────────────
echo "==> Importing SQL dump: ${SQL_FILE}"
"${MYSQL_BIN}" -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" -p"${DB_PASS}" \
  -e "DROP DATABASE IF EXISTS \`${DB_NAME}\`; CREATE DATABASE \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
"${MYSQL_BIN}" -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" -p"${DB_PASS}" "${DB_NAME}" < "${SQL_FILE}"
echo "    Done."

# ── Step 2: Reset emails ──────────────────────────────────────────────────────
echo "==> Resetting user emails to wlhtestmails+<username>@gmail.com ..."
mysql_cmd -e "
  UPDATE accounts_customuser
  SET email = CONCAT('wlhtestmails+', username, '@gmail.com');
"
echo "    Done."

# ── Step 3: Reset all passwords to Password1! ────────────────────────────────
echo "==> Resetting all passwords to 'Password1!' ..."
cd "${MANAGE_DIR}"
DB_PASSWORD="${DB_PASS}" python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
count = 0
for u in User.objects.all():
    u.set_password('Password1!')
    u.save(update_fields=['password'])
    count += 1
print(f'    Updated {count} user password(s).')
"

# ── Step 4: Reset Stripe price IDs to dev/test values ────────────────────────
echo "==> Resetting Stripe price IDs ..."
mysql_cmd -e "
  -- Wizard package
  UPDATE billing_package
  SET stripe_price_id = 'price_1TBLKQFILwrEyytiOPzV8SW5'
  WHERE name = 'Wizard';

  -- Institute plans
  UPDATE billing_instituteplan SET stripe_price_id = 'price_1TBWHhFILwrEyytiScc7dnc3' WHERE slug = 'basic';
  UPDATE billing_instituteplan SET stripe_price_id = 'price_1TBWJoFILwrEyytiktVHLJJ5' WHERE slug = 'silver';
  UPDATE billing_instituteplan SET stripe_price_id = 'price_1TBWMeFILwrEyytiqiS6PVe9' WHERE slug = 'gold';
  UPDATE billing_instituteplan SET stripe_price_id = 'price_1TBWOdFILwrEyytiVDsUgsj9' WHERE slug = 'platinum';

  -- Module products
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TE3flFILwrEyytilWZ6XPt6' WHERE module = 'teachers_attendance';
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TE3fmFILwrEyytigBOmDGD7' WHERE module = 'students_attendance';
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TE3fnFILwrEyytiKXrIxYPO' WHERE module = 'student_progress_reports';
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TGyHyFILwrEyytiUSNBUG3i' WHERE module = 'ai_import_enterprise';
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TGyIEFILwrEyytiCNEKcveT' WHERE module = 'ai_import_professional';
  UPDATE billing_moduleproduct SET stripe_price_id = 'price_1TGyIWFILwrEyytiwWOhRDW9' WHERE module = 'ai_import_starter';
"
echo "    Done."

# ── Step 5: Clear sessions ────────────────────────────────────────────────────
echo "==> Clearing sessions..."
mysql_cmd -e "DELETE FROM django_session;"
echo "    Done."

echo ""
echo "======================================================"
echo " Done! Local DB is ready."
echo " All users: wlhtestmails+<username>@gmail.com / Password1!"
echo "======================================================"
echo ""
