# 🚀 Arcadia Slot Bot — Windows Startup Script

Write-Host "🚀 Arcadia Slot Bot — Startup" -ForegroundColor Cyan

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "⚠️  .env not found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "📝 Please edit .env with your credentials before running again." -ForegroundColor Green
    Exit 1
}

# Create data directories
if (-not (Test-Path "data")) { New-Item -ItemType Directory -Path "data" | Out-Null }
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }

# Sync dependencies
Write-Host "📦 Syncing dependencies with uv..." -ForegroundColor Cyan
uv sync

# Run setup checks
Write-Host "🔧 Running setup checks..." -ForegroundColor Cyan
uv run python scripts/setup_session.py --check

# Force UTF-8 mode to prevent console encoding crashes on Windows
$env:PYTHONUTF8 = "1"

Write-Host "🏁 Starting FastAPI server..." -ForegroundColor Cyan
uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000
