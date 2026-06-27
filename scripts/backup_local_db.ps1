<#
.SYNOPSIS
    Daily local backup of the CWA Classroom MySQL database.

.DESCRIPTION
    Dumps the local dev MySQL database with mysqldump, compresses the dump to a
    timestamped .zip in a known backup folder, then prunes backups older than the
    retention window. Designed to be run unattended by Windows Task Scheduler.

    Defaults match the local dev setup (root/root @ 127.0.0.1:3306, db cwa_classroom).
    Override any of them via the parameters below if needed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup_local_db.ps1

.EXAMPLE
    # Custom folder and 7-day retention
    powershell -File scripts\backup_local_db.ps1 -BackupDir D:\Backups -RetentionDays 7
#>
[CmdletBinding()]
param(
    [string]$DbName        = $(if ($env:DB_NAME)     { $env:DB_NAME }     else { 'cwa_classroom' }),
    [string]$DbUser        = $(if ($env:DB_USER)     { $env:DB_USER }     else { 'root' }),
    [string]$DbPassword    = $(if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { 'root' }),
    [string]$DbHost        = $(if ($env:DB_HOST)     { $env:DB_HOST }     else { '127.0.0.1' }),
    [int]   $DbPort        = $(if ($env:DB_PORT)     { [int]$env:DB_PORT } else { 3306 }),
    [string]$BackupDir     = 'C:\CWA_Backups',
    [int]   $RetentionDays = 30,
    [string]$MysqldumpPath = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe'
)

$ErrorActionPreference = 'Stop'

function Write-Log([string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Output "[$ts] $msg"
}

# --- Locate mysqldump --------------------------------------------------------
if (-not (Test-Path $MysqldumpPath)) {
    $fallback = (Get-Command mysqldump.exe -ErrorAction SilentlyContinue).Source
    if ($fallback) {
        $MysqldumpPath = $fallback
    } else {
        throw "mysqldump.exe not found at '$MysqldumpPath' and not on PATH. Pass -MysqldumpPath."
    }
}

# --- Ensure backup folder exists ---------------------------------------------
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Log "Created backup folder $BackupDir"
}

$stamp   = Get-Date -Format 'yyyyMMdd_HHmmss'
$sqlFile = Join-Path $BackupDir "$($DbName)_$stamp.sql"
$zipFile = Join-Path $BackupDir "$($DbName)_$stamp.zip"

# --- Dump --------------------------------------------------------------------
# Pass the password via MYSQL_PWD so it never appears in the process command line.
Write-Log "Dumping '$DbName' from ${DbHost}:${DbPort} ..."
$env:MYSQL_PWD = $DbPassword
try {
    & $MysqldumpPath `
        --host=$DbHost --port=$DbPort --user=$DbUser `
        --single-transaction --quick --routines --events --triggers `
        --default-character-set=utf8mb4 `
        --result-file=$sqlFile `
        $DbName
    if ($LASTEXITCODE -ne 0) { throw "mysqldump exited with code $LASTEXITCODE" }
} finally {
    Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
}

if (-not (Test-Path $sqlFile) -or (Get-Item $sqlFile).Length -eq 0) {
    throw "Dump file '$sqlFile' missing or empty - backup failed."
}

# --- Compress and drop the raw .sql ------------------------------------------
Write-Log "Compressing to $zipFile ..."
Compress-Archive -Path $sqlFile -DestinationPath $zipFile -Force
Remove-Item $sqlFile -Force

$sizeMB = [math]::Round((Get-Item $zipFile).Length / 1MB, 2)
Write-Log "Backup complete: $zipFile ($sizeMB MB)"

# --- Prune old backups -------------------------------------------------------
$cutoff = (Get-Date).AddDays(-$RetentionDays)
$old = Get-ChildItem -Path $BackupDir -Filter "$($DbName)_*.zip" |
       Where-Object { $_.LastWriteTime -lt $cutoff }
foreach ($f in $old) {
    Remove-Item $f.FullName -Force
    Write-Log "Pruned old backup $($f.Name)"
}
$count = (Get-ChildItem -Path $BackupDir -Filter "$($DbName)_*.zip").Count
Write-Log "Done. Retention: $RetentionDays days. $count backup(s) on disk."
