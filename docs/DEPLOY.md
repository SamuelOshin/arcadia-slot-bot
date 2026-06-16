# 🚀 Arcadia Slot Bot — Deployment Guide

This guide details how to deploy the Arcadia Slot Bot to a **VPS**, **Railway**, or **Render** service.

---

## 📋 Prerequisites

Before deploying, ensure you have:
1. A verified X (Twitter) account.
2. The initial Next-Auth session cookies captured from your browser (via Chrome DevTools as explained in the setup).
3. If deploying via Docker, a server with Docker and Docker Compose installed.

---

## 🐳 Option 1: VPS Deployment (Recommended)

Deploying on a VPS (such as DigitalOcean, Hetzner, Linode, AWS EC2) is the **recommended** approach because the local disk is persistent. The bot will automatically renew session cookies in the background and write them back to `.env`, meaning you will never have to re-authenticate manually.

### 1. Set Up the Repository
SSH into your VPS and clone the repository:
```bash
git clone https://github.com/yourusername/arcadia-slot-bot.git
cd arcadia-slot-bot
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and populate your variables:
```bash
cp .env.example .env
nano .env
```
Ensure you set:
* `ARCADIA_SESSION_COOKIE`: Your captured browser session cookie string.
* `POLL_INTERVAL_SECONDS`: Set to `10` (or `5` if you want higher speed).
* `AUTO_LOCK_ENABLED`: Set to `true`.
* `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: (Optional) Your Telegram bot credentials for real-time notifications. Remove/leave blank if unused to prevent warnings.

### 3. Deploy via Docker Compose
Build and run the containers in detached (background) mode:
```bash
docker compose up -d --build
```
This boots three services:
1. **Redis (`arcadia-redis`)**: Used for rate-limiting and job state persistence.
2. **FastAPI Web App (`arcadia-slot-bot`)**: Serves the API and dashboard on port `8000`.
3. **Scheduler Daemon (`arcadia-scheduler`)**: Runs the background loop that polls campaigns, renews sessions, and triggers slot locks.

### 4. Verification
View the logs to ensure the bot starts up and loads the session successfully:
```bash
docker compose logs -f bot
```

---

## 🚆 Option 2: Railway Deployment

Railway is a great serverless alternative. Because Railway containers use ephemeral file systems, you **must** attach a persistent volume to preserve the session cookies across redeployments.

### 1. Configure Persistent Storage
The bot updates and saves refreshed cookies in `data/auth.json` (Playwright storage state).
* Set up a **Volume** in your Railway service settings.
* Mount it to `/app/data`.

### 2. Deploy Steps
1. Create a new project on Railway.
2. Add a **Redis** service.
3. Deploy your GitHub repository as a Web Service. Railway will automatically detect the `Dockerfile` and build the container.
4. Set the following variables in the **Variables** tab:
   * `REDIS_URL`: `redis://redis:6379/0` (or match your Railway Redis internal URL).
   * `ARCADIA_SESSION_COOKIE`: Your initial cookie string.
   * `POLL_INTERVAL_SECONDS`: `10`
   * `AUTO_LOCK_ENABLED`: `true`
5. Expose port `8000`.

---

## 🎨 Option 3: Render Deployment

Render supports Docker deployments directly from GitHub.

### 1. Deploy Redis
1. In the Render Dashboard, click **New +** and select **Redis**.
2. Name it `arcadia-redis` and click **Create Redis**.
3. Copy the **Internal Redis URL**.

### 2. Deploy the Bot Web Service
1. Click **New +** and select **Web Service**.
2. Connect your GitHub repository.
3. In the settings:
   * **Runtime**: Select `Docker`.
   * **Instance Type**: Select your plan.
4. Add the following **Environment Variables**:
   * `REDIS_URL`: Paste the Internal Redis URL you copied.
   * `ARCADIA_SESSION_COOKIE`: Your initial cookie string.
   * `POLL_INTERVAL_SECONDS`: `10`
   * `AUTO_LOCK_ENABLED`: `true`
5. In the **Advanced** section:
   * Add a **Disk (Persistent Volume)**.
   * **Mount Path**: `/app/data`
   * **Size**: `1 GB` (More than enough for storing auth details).
6. Click **Create Web Service**. Render will build the Docker container and start the app.

---

## 🔄 How Session Renewal Works (Set-and-Forget)

* **Initial Boot**: The bot loads the cookie string you provided under `ARCADIA_SESSION_COOKIE` in `.env`.
* **Rolling Extension**: Every 60 seconds, the background scheduler sends a request to `/api/auth/session`. The server extends the session by 30 days and sends back a renewed cookie.
* **Auto-Save**: The bot intercepts this cookie and writes it to `/app/data/auth.json` and `.env`. On next restart, it loads the fresh cookie from the persistent storage.
* **Important**: Always ensure `/app/data` is mounted to a **persistent volume** on Railway/Render. If the volume is missing, the renewed cookie is lost when the service restarts, forcing you to re-authenticate manually after 30 days.
