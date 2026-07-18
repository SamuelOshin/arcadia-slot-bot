# 🔒 Arcadia Slot Bot

Multi-strategy automation for Arcadia Roster campaign slots. Built with **FastAPI**, featuring three layers of resilience: API-first, Playwright fallback, and AI agent emergency recovery.

Now supports **concurrent multi-account execution** out-of-the-box on a single server, with interactive account control via Telegram.

---

## 🏗️ High-Level Architecture

The bot uses Python's asynchronous event loop to run isolated monitoring jobs for multiple accounts simultaneously. Each account manages its own session, database, and rate-limiting metrics while routing requests through a shared multi-strategy core.

```
                  ┌──────────────────────────────────────────────┐
                  │            Telegram Chat Interface           │
                  │        (Consolidated Status & Controls)      │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │                 FastAPI App                  │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
         ┌──────────────────────────────────────────────────────────────┐
         │                         BotScheduler                         │
         └──────────┬──────────────────────────┬────────────────────────┘
                    │                          │
                    ▼ (Account Loop A)         ▼ (Account Loop B)
       ┌────────────────────────┐  ┌────────────────────────┐
       │   CampaignMonitor      │  │   CampaignMonitor      │
       │    [Name: Samuel]      │  │     [Name: John]       │
       ├────────────────────────┤  ├────────────────────────┤
       │ - SessionManager A     │  │ - SessionManager B     │
       │ - ArcadiaClient A      │  │ - ArcadiaClient B      │
       │   └─ Quota: 1/3 slots  │  │   └─ Quota: 0/3 slots  │
       │ - known_campaigns_sam  │  │ - known_campaigns_john │
       └────────────┬───────────┘  └───────────┬────────────┘
                    │                          │
                    └───────────┬──────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────────────────┐
         │                       StrategyRouter                         │
         ├──────────────────────────────────────────────────────────────┤
         │  routes calls sequentially based on circuit health:          │
         │                                                              │
         │  1. API Strategy      (~50ms)   ← PRIMARY (Direct JSON)     │
         │  2. Playwright        (~2-5s)   ← FALLBACK (Browser Engine)  │
         │  3. AI Agent          (~10-30s) ← EMERGENCY (Vision GPT-4o)  │
         └──────────────────────────────────────────────────────────────┘
```

---

## 🎯 What's Currently Working

### ⚡ Direct API Locking & Smart Filtering
- **Gold-Tier Slot Filtering**: Automatically parses incoming scheduled campaigns to filter out slots marked `reservedForGold` unless the user's tier explicitly matches.
- **Fail-Forward Slot Claims**: Evaluates slots sequentially. If a slot claim receives a business permission denial (HTTP `403` with tier messages), it automatically continues trying subsequent eligible slots in the campaign instead of aborting.
- **Session Expiry Detection**: Automatically detects expired session cookies (distinguished from normal 403 denials) and triggers live session refreshes using the KOL API token.

### 👥 Concurrent Multi-Account Isolation
- **Process-Level Concurrency**: Runs N async polling loops inside a single process, avoiding the need for multiple servers.
- **Credential & Storage Isolation**: Each account uses its own persistent cookie jar and logs in using distinct browser state profiles (e.g. `./data/auth_samuel.json`).
- **Quota Independence**: Daily slot limits (`max_slots_per_day` quota) are tracked independently for each account. Lock successes on one account do not exhaust the quota of another.
- **Isolated History**: Keeps separate lists of matched/ignored campaigns (e.g., `known_campaigns_john.json`) to prevent cross-account duplicates.

### 💬 Revamped Telegram UI/UX
- **Descriptive Auto-Lock Alerts**: Success and failure Telegram cards completely rebuilt to show targeted details (Campaign Name, Payout, Response Time, Slot Claimed, or exact reason for collision/miss).
- **Consolidated Dashboard**: Running `/status` prints a high-level summary list of all active accounts (scheduler health, active sessions, and slots locked today per-user).
- **Interactive Navigation Keyboard**: Select individual accounts using inline buttons (e.g., `[ 👤 Samuel ]`, `[ 👤 John ]`) to inspect detailed credentials, and execute specific operations like a targeted `[ 🔄 Refresh Session ]` or go `[ 🔙 Back to Summary ]`.

---

## 🚀 Quick Start

### 1. Clone & Setup
```bash
git clone <repo>
cd arcadia-slot-bot
cp .env.example .env
```

### 2. Configure Authentication
To run in **Multi-Account Mode**, define the `ACCOUNTS` environment variable in your `.env` file as a JSON array of objects:

```env
ACCOUNTS=[{"name": "Samuel", "session_cookie": "...", "api_token": "..."},{"name": "John", "session_cookie": "...", "api_token": "..."}]
```

For **Single-Account Mode** (backwards compatibility), you can continue using the original env keys:
```env
ARCADIA_SESSION_COOKIE="your_cookie_here"
ARCADIA_API_TOKEN="your_token_here"
```

### 3. Run
```bash
# Local development (FastAPI Dev Mode with reload)
uv run fastapi dev app/main.py
```

### 4. Verify
```bash
# Check health
curl http://localhost:8000/api/v1/health

# Run test suite
.venv\Scripts\pytest tests/
```

---

## 🔧 Configuration

Key settings in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `ACCOUNTS` | JSON array of accounts credentials | `None` |
| `POLL_INTERVAL_SECONDS` | How often to check for slots | `30` |
| `AUTO_LOCK_ENABLED` | Automatically lock available slots | `false` |
| `AUTO_LOCK_MAX_CONCURRENT` | Max simultaneous locks per cycle | `2` |
| `CAMPAIGN_FILTER_MIN_PAYOUT` | Ignore campaigns paying below this amount | `0.0` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot credentials | `None` |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for notifications | `None` |

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Bot health & strategy status |
| `/api/v1/campaigns` | GET | List available campaigns for default account |
| `/api/v1/slots/lock/{id}` | POST | Lock a specific campaign |
| `/api/v1/slots/lock-retry/{id}` | POST | Lock with retry on conflict |
| `/api/v1/dashboard/stats` | GET | Runtime statistics |

---

## 🧠 Strategies Explained

### 1. API Strategy (Primary)
Direct HTTP calls to reverse-engineered endpoints. Fastest but requires knowing the API structure. The bot tries multiple endpoint patterns automatically.

### 2. Playwright Strategy (Fallback)
Real browser automation with anti-detection. Used when API auth fails or endpoints are unknown. Persists session state across runs.

### 3. AI Agent Strategy (Emergency)
Vision-language model (GPT-4o) that "sees" and interacts with the UI. Slowest but handles unexpected layouts, CAPTCHAs, and complex flows.

---

## ⚡ Circuit Breaker

If a strategy fails 5 times in a row, it's temporarily disabled for 5 minutes. This prevents hammering failing methods and allows automatic recovery.

---

## 🔔 Notifications

Configure Telegram and/or Discord to get instant alerts:
- 🎯 New campaign drops
- 🔒 Successful slot locks (tagged per account)
- ⚠️ Errors and session expiry

---

## 🐳 Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f bot
```

---

## 📄 License

MIT — Personal use only. Do not distribute.