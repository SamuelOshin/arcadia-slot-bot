# 🔒 Arcadia Slot Bot

Multi-strategy automation for Arcadia Roster campaign slots. Built with **FastAPI**, featuring three layers of resilience: API-first, Playwright fallback, and AI agent emergency recovery.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ARCADIA SLOT BOT                          │
├─────────────────────────────────────────────────────────────┤
│  Strategy Router → Circuit Breaker → Notifications          │
│                                                             │
│  1. API Strategy      (~50ms)   ← PRIMARY                  │
│  2. Playwright        (~2-5s)   ← FALLBACK                 │
│  3. AI Agent          (~10-30s) ← EMERGENCY                │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Clone & Setup
```bash
git clone <repo>
cd arcadia-slot-bot
cp .env.example .env
```

### 2. Configure Authentication
```bash
# Option A: Interactive browser capture (most reliable)
python scripts/setup_session.py --capture

# Option B: Manual — edit .env with your session cookie or API token
```

### 3. Run
```bash
# Local development (FastAPI Dev Mode with reload)
uv run fastapi dev app/main.py

# Or using the startup script
./run.sh

# Or with Docker (using FastAPI Run Production Mode)
docker-compose up -d
```

### 4. Verify
```bash
# Check health
curl http://localhost:8000/api/v1/health

# Test strategies
python scripts/test_strategies.py

# List campaigns
curl http://localhost:8000/api/v1/campaigns
```

## 🔧 Configuration

Key settings in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `POLL_INTERVAL_SECONDS` | How often to check for slots | 30 |
| `AUTO_LOCK_ENABLED` | Automatically lock available slots | false |
| `AUTO_LOCK_MAX_CONCURRENT` | Max simultaneous locks | 2 |
| `STRATEGY_PRIORITY` | Execution order | api,playwright,ai_agent |
| `CAMPAIGN_FILTER_MIN_PAYOUT` | Ignore low-payout campaigns | $5 |
| `TELEGRAM_BOT_TOKEN` | Telegram notifications | — |
| `DISCORD_WEBHOOK_URL` | Discord notifications | — |

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Bot health & strategy status |
| `/api/v1/campaigns` | GET | List available campaigns |
| `/api/v1/slots/lock/{id}` | POST | Lock a specific campaign |
| `/api/v1/slots/lock-retry/{id}` | POST | Lock with retry on conflict |
| `/api/v1/slots/auto-lock` | POST | Auto-lock all matching campaigns |
| `/api/v1/dashboard/config` | GET | Current configuration |
| `/api/v1/dashboard/stats` | GET | Runtime statistics |

## 🧠 Strategies Explained

### 1. API Strategy (Primary)
Direct HTTP calls to reverse-engineered endpoints. Fastest but requires knowing the API structure. The bot tries multiple endpoint patterns automatically.

### 2. Playwright Strategy (Fallback)
Real browser automation with anti-detection. Used when API auth fails or endpoints are unknown. Persists session state across runs.

### 3. AI Agent Strategy (Emergency)
Vision-language model (GPT-4o) that "sees" and interacts with the UI. Slowest but handles unexpected layouts, CAPTCHAs, and complex flows.

## ⚡ Circuit Breaker

If a strategy fails 5 times in a row, it's temporarily disabled for 5 minutes. This prevents hammering failing methods and allows automatic recovery.

## 🔔 Notifications

Configure Telegram and/or Discord to get instant alerts:
- 🎯 New campaign drops
- 🔒 Successful slot locks
- ⚠️ Errors and session expiry

## 🐳 Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f bot

# Scale scheduler separately
docker-compose up -d --scale scheduler=1
```

## ⚠️ Disclaimer

This tool is for **personal use only**. Automation may violate Arcadia's Terms of Service. Use at your own risk. The bot includes rate limiting and respects quotas to minimize impact.

## 📄 License

MIT — Personal use only. Do not distribute.