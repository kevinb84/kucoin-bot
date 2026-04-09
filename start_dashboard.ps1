# Trading Bot Dashboard Launcher
# This script starts the web dashboard for monitoring the trading bot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Trading Bot Dashboard Launcher" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
Write-Host "Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found! Please install Python 3.9+" -ForegroundColor Red
    exit 1
}

# Check if dependencies are installed
Write-Host "`nChecking dependencies..." -ForegroundColor Yellow
$requiredModules = @("flask", "flask_socketio", "pandas", "numpy", "ccxt", "sklearn")
$missingModules = @()

foreach ($module in $requiredModules) {
    try {
        python -c "import $module" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ $module" -ForegroundColor Green
        } else {
            Write-Host "  ✗ $module" -ForegroundColor Red
            $missingModules += $module
        }
    } catch {
        Write-Host "  ✗ $module" -ForegroundColor Red
        $missingModules += $module
    }
}

if ($missingModules.Count -gt 0) {
    Write-Host "`n✗ Missing dependencies: $($missingModules -join ', ')" -ForegroundColor Red
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n✗ Failed to install dependencies" -ForegroundColor Red
        Write-Host "Run manually: pip install -r requirements.txt" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✓ Dependencies installed successfully" -ForegroundColor Green
} else {
    Write-Host "✓ All dependencies found" -ForegroundColor Green
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "  Starting Dashboard..." -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Dashboard will be available at:" -ForegroundColor Yellow
Write-Host "  http://localhost:5000" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the dashboard`n" -ForegroundColor Yellow

# Start the dashboard
python src/dashboard/app.py
