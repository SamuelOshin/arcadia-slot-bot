# ═══════════════════════════════════════════════════════════
# Arcadia Slot Bot — Multi-Stage Production Dockerfile
# ═══════════════════════════════════════════════════════════

# -----------------------------------------------------------
# Stage 1: Build Frontend React SPA (Node.js Build Environment)
# -----------------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------
# Stage 2: Final Production Application Runner (Python Environment)
# -----------------------------------------------------------
FROM python:3.12-slim AS runner

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"


# Copy Python backend application code
COPY . .

# Copy compiled SPA production assets from Stage 1 into /app/frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create persistent session storage directory
RUN mkdir -p /app/data

EXPOSE 8000 9090

CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]