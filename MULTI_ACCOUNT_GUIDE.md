# 👥 Arcadia Slot Bot — Multi-Account Configuration & Operations Guide

This guide explains how multi-account concurrent slot-locking operates, how to configure multiple sessions, and how to control them through the interactive Telegram dashboard.

---

## 🏗️ How It Works (Under the Hood)

The bot leverages Python's asynchronous event loop (`asyncio`) to run isolated tasks concurrently inside a single service process.

```
                              [Bot Process]
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
  [Account: Samuel]         [Account: John]           [Account: Alice]
  ├── SessionManager        ├── SessionManager        ├── SessionManager
  │    (auth_samuel.json)   │    (auth_john.json)     │    (auth_alice.json)
  ├── ArcadiaClient         ├── ArcadiaClient         ├── ArcadiaClient
  │    (Quota: 1/3 slots)   │    (Quota: 0/3 slots)   │    (Quota: 2/3 slots)
  └── Poll Job (30s)        └── Poll Job (30s)        └── Poll Job (30s)
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    ▼
                          [Shared Strategy Router]
                           (API, Playwright, AI)
```

### 🔒 1. Session Isolation
Each account configured in `ACCOUNTS` runs its own `SessionManager` instance. 
- State is persisted in separate storage files: `./data/auth_<name>.json` (where `<name>` is the lowercase account label).
- When Playwright or API strategy refreshes/saves cookies, it only updates that specific account's JSON storage file.

### 📈 2. Independent Quotas
Arcadia restricts slot claims per account. The bot mirrors this:
- Quota metrics (`_slots_locked_today` and `_locked_campaigns`) are tracked independently inside each account's `ArcadiaClient` instance.
- Locking a slot on Samuel's account consumes Samuel's daily limit but has zero impact on John's remaining quota.

### 🗃️ 3. Drop Databases
- Each account maintains its own drop-history database (`known_campaigns_<name>.json`).
- This allows accounts to react to campaigns independently; if a new campaign drops, both accounts will attempt to lock it.

---

## ⚙️ Configuration Setup

To configure multiple accounts, you must define the `ACCOUNTS` variable in your `.env` file as a **minified JSON array**.

### Step 1: Gather Session Credentials
For each account you want to run, log into the Arcadia website on your browser and extract:
1. **Session Cookie**: Open developer tools -> Application -> Cookies. Capture the full cookie string containing `__Secure-next-auth.session-token` or `arcadia_session`.
2. **KOL API Token**: Grab your KOL token used for background session refreshes.

### Step 2: Build the JSON Config
Create a list of objects containing `name` (a label for Telegram alerts), `session_cookie`, and `api_token`:

```json
[
  {
    "name": "Samuel",
    "session_cookie": "__Secure-next-auth.session-token=eyJhbGciOiJkaXIiLCJlbmM...",
    "api_token": "kol_token_samuel_abc123"
  },
  {
    "name": "John",
    "session_cookie": "__Secure-next-auth.session-token=eyJhbGciOiJkaXIiLCJlbmM...",
    "api_token": "kol_token_john_xyz789"
  }
]
```

### Step 3: Add to `.env`
Railway and docker environments require environment variables to be on a single line. Minify your JSON array and paste it into `.env`:

```env
ACCOUNTS=[{"name":"Samuel","session_cookie":"...","api_token":"..."},{"name":"John","session_cookie":"...","api_token":"..."}]
```

---

## 💬 Controlling Accounts via Telegram

The interactive Telegram bot allows you to monitor and trigger refreshes for all accounts from a single chat.

### 📊 Consolidated Summary (/status)
Sending `/status` renders a summary of all loaded accounts:
```
📊 Arcadia Bot Status Summary

🤖 Scheduler: 🟢 Active
⏰ Check Interval: 30s

⚙️ Active Accounts:
👤 Samuel: 🟢 Valid | Locked: 1/3
👤 John: 🔴 Invalid | Locked: 0/3

[ 👤 Samuel ] [ 👤 John ]
[ ⚡ Force Check All ] [ ⏸️ Toggle Scheduler ]
```

### 👤 Detailed Account View
Clicking an account's button (e.g. `[ 👤 Samuel ]`) edits the card to display details for that account:
```
👤 Account Details: Samuel

🔐 Session Auth: ✅ Live (200 OK)
⏰ Last Check: 12s ago

📈 Stats Today:
• Slots Locked: 1/3
• Remaining Quota: 2
• Total Monitored: 27

[ 🔄 Refresh Session ] [ 🔙 Back to Summary ]
```

- **`🔄 Refresh Session`**: Attempts a live session token refresh using the designated KOL API token *only* for this specific account.
- **`🔙 Back to Summary`**: Returns to the main accounts status grid.

### ⚡ Forced Check
- **`⚡ Force Check All`**: Instantly polls Arcadia and attempts slot locks for all accounts sequentially.
