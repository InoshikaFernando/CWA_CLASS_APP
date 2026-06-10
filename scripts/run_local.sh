#!/usr/bin/env bash
#
# One-command local runner for the Worksheet Builder.
#
#   ./scripts/run_local.sh
#
# Creates the MySQL database, applies migrations, seeds a demo teacher plus
# 30 Python/Variables coding questions, and starts the dev server on
# http://127.0.0.1:8000/  (log in as demo_teacher / pass1234!).
#
# Override any DB setting via env vars, e.g.:
#   DB_PASSWORD=secret DB_HOST=127.0.0.1 ./scripts/run_local.sh
#
set -euo pipefail
cd "$(dirname "$0")/../cwa_classroom"

# --- Config (defaults match a local MySQL root/root install) ---------------
export DB_ENGINE=mysql
export DB_NAME=${DB_NAME:-cwa_classroom}
export DB_USER=${DB_USER:-root}
export DB_PASSWORD=${DB_PASSWORD:-root}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-3306}
export DEBUG=True                       # MUST be exactly "True"
export SECRET_KEY=${SECRET_KEY:-dev-local-secret-change-me}
export ALLOWED_HOSTS=${ALLOWED_HOSTS:-localhost,127.0.0.1}
PORT=${PORT:-8000}

# --- 1. Create database (via Python so no mysql CLI is needed) -------------
echo "==> Ensuring database '$DB_NAME' exists"
python -c "import MySQLdb, os; c=MySQLdb.connect(host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']), user=os.environ['DB_USER'], passwd=os.environ['DB_PASSWORD']); c.cursor().execute('CREATE DATABASE IF NOT EXISTS ' + os.environ['DB_NAME'] + ' CHARACTER SET utf8mb4'); c.commit()"

# --- 2. Migrate ------------------------------------------------------------
echo "==> Applying migrations"
python manage.py migrate --noinput

# --- 3. Seed demo teacher + coding questions -------------------------------
echo "==> Seeding demo data"
SEED="$(cd "$(dirname "$0")" && pwd)/seed_demo.py"
python manage.py shell -c "exec(open('$SEED').read())"

# --- 4. Run ----------------------------------------------------------------
echo "==> Starting server on http://127.0.0.1:${PORT}/  (Ctrl+C to stop)"
echo "    Log in as demo_teacher / pass1234! then open /worksheets/builder/"
exec python manage.py runserver "127.0.0.1:${PORT}"
