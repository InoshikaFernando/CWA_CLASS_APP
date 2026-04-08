#!/usr/bin/env bash
# sanitise_test_db.sh
# -------------------
# Run this on PythonAnywhere AFTER restore_prod_to_test.sh to make the
# test database safe for development:
#   1. Scramble all user emails   → <id>+test@example.com
#   2. Reset all user passwords   → Password1!
#   3. Clear sessions             → no prod logins carry over
#
# Usage:
#   bash scripts/sanitise_test_db.sh
#
# Must be run from the repo root (where manage.py lives inside cwa_classroom/).

set -euo pipefail

# ── Config (matches restore_prod_to_test.sh) ─────────────────────────────────
DB_HOST="${DB_HOST:-avinesh.mysql.pythonanywhere-services.com}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-avinesh}"
DB_PASS="${DB_PASS:-wenuskala!1}"
DST_DB="${DST_DB:-avinesh\$cwa_classroom_test}"

MANAGE_DIR="${MANAGE_DIR:-$(dirname "$0")/../cwa_classroom}"
MYSQL="mysql -h ${DB_HOST} -P ${DB_PORT} -u ${DB_USER} -p${DB_PASS} ${DST_DB}"
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "======================================================"
echo " Sanitising test database: ${DST_DB}"
echo "======================================================"
echo ""

# ── Step 1: Scramble emails ───────────────────────────────────────────────────
echo "==> Scrambling user emails..."
$MYSQL -e "
  UPDATE accounts_customuser
  SET email = CONCAT(id, '+test@example.com');
"
echo "    Done."

# ── Step 2: Reset all passwords to Password1! ────────────────────────────────
echo "==> Resetting all passwords to 'Password1!' ..."
cd "${MANAGE_DIR}"
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
count = 0
for u in User.objects.all():
    u.set_password('Password1!')
    u.save(update_fields=['password'])
    count += 1
print(f'    Updated {count} user password(s).')
"

# ── Step 3: Clear sessions ────────────────────────────────────────────────────
echo "==> Clearing sessions..."
$MYSQL -e "DELETE FROM django_session;"
echo "    Done."

echo ""
echo "======================================================"
echo " Sanitisation complete."
echo " All users can now log in with:  Password1!"
echo "======================================================"
echo ""
