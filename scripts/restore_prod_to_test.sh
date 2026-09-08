#!/usr/bin/env bash
# restore_prod_to_test.sh  (DigitalOcean)
# ---------------------------------------
# Copies the PRODUCTION database into the TEST database on the same managed
# MySQL server, then migrates, sanitizes, and re-points Stripe — leaving a
# test site that is safe to log into AND able to take a test-mode payment.
#
# Run ON the droplet (it reads DB creds from the env files in /etc/cwa/):
#   sudo -u cwa bash scripts/restore_prod_to_test.sh            # full run
#   sudo -u cwa bash scripts/restore_prod_to_test.sh --dry-run  # preview only
#
# Safety:
#   * Reads every credential from the systemd env files. Nothing is hardcoded.
#   * Refuses to run unless the DEST DB name contains "test".
#   * Refuses to run if the test env still holds a LIVE Stripe key.
#   * Only ever DROPs the test DB, never prod.
#
# Why the Stripe steps at the end are not optional
# ------------------------------------------------
# A prod dump carries prod's LIVE Stripe price ids (price_… minted with
# sk_live_). Restored onto test — which runs sk_test_ keys — every one of them
# is a live object the test key cannot see, so Stripe answers "No such price"
# and the student gets the app's generic "contact support". Nothing goes red;
# the test site just quietly stops taking payments. That is exactly what
# happened in September 2026 and it cost an intern a day.
#
# So: sanitize blanks the ids, sync_stripe_prices mints/links test-mode ones,
# and check_stripe_prices is a HARD GATE — a non-zero exit here means the test
# site cannot be paid on, and you want to know that now rather than from a
# tester's screenshot.
set -euo pipefail

PROD_ENV="${PROD_ENV:-/etc/cwa/cwa.env}"
TEST_ENV="${TEST_ENV:-/etc/cwa/cwa-test.env}"
TEST_APP_DIR="${TEST_APP_DIR:-/home/cwa/CWA_CLASS_APP_TEST}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true && echo "[DRY RUN] no changes will be written"

# ── Pull a KEY=value out of a systemd EnvironmentFile (no sourcing) ───────────
envget() { grep -E "^${2}=" "${1}" | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }

for f in "$PROD_ENV" "$TEST_ENV"; do
    [[ -r "$f" ]] || { echo "ABORT: cannot read env file '${f}'."; exit 1; }
done

SRC_NAME="$(envget "$PROD_ENV" DB_NAME)"
SRC_HOST="$(envget "$PROD_ENV" DB_HOST)"
SRC_PORT="$(envget "$PROD_ENV" DB_PORT)"
SRC_USER="$(envget "$PROD_ENV" DB_USER)"
SRC_PASS="$(envget "$PROD_ENV" DB_PASSWORD)"

DST_NAME="$(envget "$TEST_ENV" DB_NAME)"
DST_HOST="$(envget "$TEST_ENV" DB_HOST)"
DST_PORT="$(envget "$TEST_ENV" DB_PORT)"
DST_USER="$(envget "$TEST_ENV" DB_USER)"
DST_PASS="$(envget "$TEST_ENV" DB_PASSWORD)"

echo "Source (prod): ${SRC_USER}@${SRC_HOST}:${SRC_PORT}/${SRC_NAME}"
echo "Target (test): ${DST_USER}@${DST_HOST}:${DST_PORT}/${DST_NAME}"

# ── Guard: never touch a non-test database ───────────────────────────────────
if [[ -z "${DST_NAME}" || -z "${SRC_NAME}" ]]; then
    echo "ABORT: DB_NAME missing from one of the env files."
    exit 1
fi
if [[ "${DST_NAME,,}" != *test* ]]; then
    echo "ABORT: test DB name '${DST_NAME}' does not contain 'test'. Refusing to drop it."
    exit 1
fi
if [[ "${DST_NAME}" == "${SRC_NAME}" && "${DST_HOST}" == "${SRC_HOST}" ]]; then
    echo "ABORT: source and target are the same database."
    exit 1
fi

# ── Guard: a live Stripe key on test would charge real cards ─────────────────
# Worth an abort rather than a warning: the whole point of the steps below is
# to hand the test site working payments, and doing that against sk_live_ means
# a tester clicking "Subscribe" bills someone's real card.
TEST_STRIPE_KEY="$(envget "$TEST_ENV" STRIPE_SECRET_KEY)"
if [[ "${TEST_STRIPE_KEY}" == sk_live_* ]]; then
    echo "ABORT: ${TEST_ENV} holds a LIVE Stripe secret key (sk_live_…)."
    echo "       Point the test environment at sk_test_ keys before restoring."
    exit 1
fi
if [[ -z "${TEST_STRIPE_KEY}" ]]; then
    echo "WARNING: no STRIPE_SECRET_KEY in ${TEST_ENV} — the Stripe re-point"
    echo "         steps will be skipped and the test site will not take payments."
fi

DUMP_FILE="/tmp/prod_to_test_$(date +%Y%m%d_%H%M%S).sql"

if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would: dump ${SRC_NAME} -> ${DUMP_FILE}, DROP+CREATE ${DST_NAME},"
    echo "[DRY RUN]        restore, migrate, sanitize, re-point Stripe, verify."
    exit 0
fi

echo "==> Dumping prod -> ${DUMP_FILE}"
mysqldump -h "$SRC_HOST" -P "$SRC_PORT" -u "$SRC_USER" -p"$SRC_PASS" \
    --single-transaction --no-tablespaces --routines --triggers \
    --set-gtid-purged=OFF "$SRC_NAME" > "$DUMP_FILE"
echo "    $(du -sh "$DUMP_FILE" | cut -f1)"

echo "==> Recreating test DB ${DST_NAME}"
mysql -h "$DST_HOST" -P "$DST_PORT" -u "$DST_USER" -p"$DST_PASS" \
    -e "DROP DATABASE IF EXISTS \`${DST_NAME}\`;
        CREATE DATABASE \`${DST_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "==> Restoring dump into ${DST_NAME}"
mysql -h "$DST_HOST" -P "$DST_PORT" -u "$DST_USER" -p"$DST_PASS" "$DST_NAME" < "$DUMP_FILE"
rm -f "$DUMP_FILE"

# From here on the DB holds real emails and real password hashes. Nobody may
# log in until the sanitize step below has run.
cd "${TEST_APP_DIR}/cwa_classroom"
set -a; source "$TEST_ENV"; set +a
PY="${TEST_APP_DIR}/venv/bin/python"

echo "==> Migrating test (using test env)"
"$PY" manage.py migrate --noinput

echo "==> Sanitizing test (passwords/emails/Stripe ids/sessions)"
"$PY" manage.py shell < "${SCRIPTS_DIR}/sanitize_test_db.py"

# ── Re-point Stripe at test-mode objects ─────────────────────────────────────
# sanitize_test_db.py blanked every stripe_price_id; without this the packages
# have no price at all and checkout fails just as surely as with a live id.
if [[ -n "${TEST_STRIPE_KEY}" ]]; then
    echo "==> Linking/creating test-mode Stripe prices"
    "$PY" manage.py sync_stripe_prices --create-missing

    echo "==> Syncing discount codes to test-mode Stripe coupons"
    "$PY" manage.py sync_stripe_coupons
fi

# ── Verify: sanitisation ─────────────────────────────────────────────────────
echo "==> Verifying sanitisation"
UNSCRUBBED="$(mysql -h "$DST_HOST" -P "$DST_PORT" -u "$DST_USER" -p"$DST_PASS" \
    -sse "SELECT COUNT(*) FROM accounts_customuser
           WHERE email <> '' AND email NOT LIKE '%@test.local';" "$DST_NAME")"
if [[ "${UNSCRUBBED}" != "0" ]]; then
    echo "FAILED: ${UNSCRUBBED} user email(s) are still real addresses."
    echo "        The sanitize step did not complete. Do not hand this"
    echo "        environment to anyone — re-run the sanitizer and re-check."
    exit 1
fi
echo "    OK — no real email addresses remain."

# ── Verify: payments actually work ───────────────────────────────────────────
# The hard gate. Non-zero exit = the test site cannot be paid on.
if [[ -n "${TEST_STRIPE_KEY}" ]]; then
    echo "==> Verifying every configured Stripe price is chargeable"
    if ! "$PY" manage.py check_stripe_prices --fresh; then
        echo ""
        echo "FAILED: the restored test DB has Stripe prices that cannot be charged."
        echo "        Students on those plans will see 'contact support'."
        echo "        Fix the rows listed above before handing this to a tester."
        exit 1
    fi
fi

echo ""
echo "Done — ${DST_NAME} is a sanitized, payable copy of prod."
echo "  Log in as user<id>@test.local / Password1!"
echo "  Smoke it:  cd ${TEST_APP_DIR}/cwa_classroom && \"$PY\" smoke_test.py https://test.wizardslearninghub.co.nz"
