#!/bin/bash
set -e

echo "🚀 Arcadia Slot Bot — Startup"

# Check .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env not found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your credentials before running again."
    exit 1
fi

# Create data directories
mkdir -p data logs

# Sync dependencies
echo "📦 Syncing dependencies with uv..."
uv sync

# Install playwright browsers if not present
if ! uv run python -c "import playwright" 2>/dev/null; then
    echo "🎭 Installing Playwright browsers..."
    uv run playwright install chromium
fi

echo "🔧 Running setup checks..."
uv run python scripts/setup_session.py --check

echo "🏁 Starting FastAPI server..."
uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000