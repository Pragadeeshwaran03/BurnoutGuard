# ============================================================
#  BurnoutGuard – Auto Installer & Launcher
#  Run this from the burnout-system directory:
#     powershell -ExecutionPolicy Bypass -File start.ps1
# ============================================================

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$ML   = "$ROOT\ml-engine"
$BE   = "$ROOT\backend"
$FE   = "$ROOT\frontend"

function Write-Header($msg) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

# ── 1. Python ML Engine deps ──────────────────────────────
Write-Header "Installing ML Engine Python dependencies..."
$pipOk = (Get-Command pip -ErrorAction SilentlyContinue) -ne $null
if (-not $pipOk) {
    Write-Host "ERROR: pip not found. Make sure Python is installed and on PATH." -ForegroundColor Red
    exit 1
}
pip install -r "$ML\requirements.txt" --quiet
Write-Host "ML Engine deps OK." -ForegroundColor Green

# ── 2. Frontend npm deps ──────────────────────────────────
Write-Header "Installing Frontend npm dependencies..."
$npmOk = (Get-Command npm -ErrorAction SilentlyContinue) -ne $null
if (-not $npmOk) {
    Write-Host "ERROR: npm not found. Make sure Node.js is installed and on PATH." -ForegroundColor Red
    exit 1
}
Push-Location $FE
npm install --silent
Pop-Location
Write-Host "Frontend deps OK." -ForegroundColor Green

# ── 3. Check mvn ─────────────────────────────────────────
Write-Header "Checking Maven..."
$mvnOk = (Get-Command mvn -ErrorAction SilentlyContinue) -ne $null
if (-not $mvnOk) {
    Write-Host "ERROR: mvn not found. Make sure Maven is installed and on PATH." -ForegroundColor Red
    exit 1
}
Write-Host "Maven OK." -ForegroundColor Green

# ── 4. Launch all three services in separate windows ─────
Write-Header "Starting all services..."

# ML Engine
Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "Write-Host 'ML ENGINE (Flask :5001)' -ForegroundColor Cyan; cd '$ML'; python app.py"

Start-Sleep -Seconds 3

# Spring Boot Backend
Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "Write-Host 'BACKEND (Spring Boot :8080)' -ForegroundColor Yellow; cd '$BE'; mvn spring-boot:run"

Start-Sleep -Seconds 5

# Vite Frontend
Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "Write-Host 'FRONTEND (Vite :5173)' -ForegroundColor Green; cd '$FE'; npm run dev"

Write-Host ""
Write-Host "All services launched!" -ForegroundColor Green
Write-Host ""
Write-Host ">>> Open in browser: http://localhost:3000 <<<" -ForegroundColor Magenta
Write-Host ""
Write-Host "Services:" -ForegroundColor White
Write-Host "  ML Engine  -> http://localhost:5001" -ForegroundColor Cyan
Write-Host "  Backend    -> http://localhost:8080" -ForegroundColor Yellow
Write-Host "  Frontend   -> http://localhost:3000" -ForegroundColor Green
Start-Sleep -Seconds 3
Start-Process "http://localhost:3000"
Write-Host ""
