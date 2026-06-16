# ═══════════════════════════════════════════════════════════
# Arcadia Slot Bot — Production Dockerfile
# ═══════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system deps for Playwright
RUN apt-get update && apt-get install -y \
    curl wget gnupg libglib2.0-0 libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Place executable scripts in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy app
COPY . .

# Create data dir for sessions
RUN mkdir -p /app/data

EXPOSE 8000 9090

CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]