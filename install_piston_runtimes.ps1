# install_piston_runtimes.ps1
# Run this from the project root after starting Piston:
#   docker-compose -f docker-compose.piston.yml up -d
#   .\install_piston_runtimes.ps1

$PISTON_URL = "http://localhost:2000"

Write-Host "Waiting for Piston to be ready..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "$PISTON_URL/api/v2/runtimes" -Method Get -ErrorAction Stop
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    Write-Host "ERROR: Piston did not start in time. Check: docker ps" -ForegroundColor Red
    exit 1
}

Write-Host "Piston is up." -ForegroundColor Green

Write-Host "`nInstalling Python 3.10.0..." -ForegroundColor Cyan
try {
    $body = '{"language": "python", "version": "3.10.0"}'
    $result = Invoke-RestMethod -Uri "$PISTON_URL/api/v2/packages" -Method Post `
        -ContentType "application/json" -Body $body
    Write-Host "Python: $($result | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "Python: $($_.ErrorDetails.Message)" -ForegroundColor Yellow
}

Write-Host "`nInstalling Node.js 18.15.0..." -ForegroundColor Cyan
try {
    $body = '{"language": "node", "version": "18.15.0"}'
    $result = Invoke-RestMethod -Uri "$PISTON_URL/api/v2/packages" -Method Post `
        -ContentType "application/json" -Body $body
    Write-Host "Node: $($result | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Host "Node: $($_.ErrorDetails.Message)" -ForegroundColor Yellow
}

Write-Host "`nCurrently installed runtimes:" -ForegroundColor Green
Invoke-RestMethod -Uri "$PISTON_URL/api/v2/runtimes" | ForEach-Object {
    Write-Host "  $($_.language) $($_.version)" -ForegroundColor Cyan
}

Write-Host "`nDone. Piston is ready." -ForegroundColor Green