<#
.SYNOPSIS
  One-command local runner for the Worksheet Builder (Windows PowerShell).

.DESCRIPTION
  Creates the MySQL database, applies migrations, seeds a demo teacher plus
  30 Python/Variables coding questions, and starts the dev server on
  http://127.0.0.1:8000/  (log in as demo_teacher / pass1234!).

  Run from the repo root:
      .\scripts\run_local.ps1

  Override any DB setting with an env var first, e.g.:
      $env:DB_PASSWORD = "secret"; .\scripts\run_local.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\cwa_classroom")

# --- Config (defaults match a local MySQL root/root install) ---------------
$env:DB_ENGINE = "mysql"
if (-not $env:DB_NAME)      { $env:DB_NAME = "cwa_classroom" }
if (-not $env:DB_USER)      { $env:DB_USER = "root" }
if (-not $env:DB_PASSWORD)  { $env:DB_PASSWORD = "root" }
if (-not $env:DB_HOST)      { $env:DB_HOST = "127.0.0.1" }
if (-not $env:DB_PORT)      { $env:DB_PORT = "3306" }
$env:DEBUG = "True"                       # MUST be exactly "True"
if (-not $env:SECRET_KEY)    { $env:SECRET_KEY = "dev-local-secret-change-me" }
if (-not $env:ALLOWED_HOSTS) { $env:ALLOWED_HOSTS = "localhost,127.0.0.1" }
if (-not $env:PORT)          { $env:PORT = "8000" }

# --- 1. Create database (via Python so no mysql CLI is needed) -------------
Write-Host "==> Ensuring database '$($env:DB_NAME)' exists"
python -c "import MySQLdb, os; c=MySQLdb.connect(host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']), user=os.environ['DB_USER'], passwd=os.environ['DB_PASSWORD']); c.cursor().execute('CREATE DATABASE IF NOT EXISTS ' + os.environ['DB_NAME'] + ' CHARACTER SET utf8mb4'); c.commit()"

# --- 2. Migrate ------------------------------------------------------------
Write-Host "==> Applying migrations"
python manage.py migrate --noinput

# --- 3. Seed demo teacher + coding questions -------------------------------
Write-Host "==> Seeding demo data"
$seed = (Join-Path $PSScriptRoot "seed_demo.py") -replace '\\', '/'
python manage.py shell -c "exec(open('$seed').read())"

# --- 4. Run ----------------------------------------------------------------
Write-Host "==> Starting server on http://127.0.0.1:$($env:PORT)/  (Ctrl+C to stop)"
Write-Host "    Log in as demo_teacher / pass1234! then open /worksheets/builder/"
python manage.py runserver "127.0.0.1:$($env:PORT)"
