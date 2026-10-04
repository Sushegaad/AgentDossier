# AgentDossier self-hosted edition: one container with the scanner, the ARD REST API,
# /qualify, the scheduler and the web UI. Build from the repository root:
#   docker build -f deploy/Dockerfile -t agentdossier:latest .
#
# Base images are pinned by digest (Dependabot keeps them current) and the Python
# environment is installed from uv.lock, so the image contains exactly what CI audited.

# --- stage 1: the web UI, built for the root path -----------------------------------
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY config /src/config
COPY docs /src/docs
COPY web ./
# The UI is served by the API at /, and reads /catalog/* from the same origin.
ENV SITE_BASE=/ SITE_URL=http://localhost:8080 CATALOG_DIR=/nonexistent PUBLIC_DYNAMIC_AGENTS=1
RUN npm run build

# --- stage 2: the Python environment, from the lockfile ----------------------------------
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
# dependencies only, from the lock; the package itself is added in the next stage
RUN uv sync --frozen --no-dev --no-install-project --extra connectors --extra server --extra mcp

# --- stage 3: the service -------------------------------------------------------------------
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN useradd --create-home --uid 10001 agentdossier
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY pyproject.toml README.md LICENSE ./
COPY agentdossier ./agentdossier
COPY config ./config
COPY schema ./schema
COPY data/curated ./data/curated
COPY data/seed ./data/seed
COPY docs ./docs
# The package is pure Python: no install step, no build backend, nothing resolved at image
# build time. A one-line launcher keeps the `agentdossier` CLI available in the container.
ENV PYTHONPATH=/app
RUN printf '#!/bin/sh\nexec /opt/venv/bin/python -m agentdossier.cli "$@"\n' > /usr/local/bin/agentdossier && chmod +x /usr/local/bin/agentdossier
COPY --from=web /src/web/dist ./web/dist
RUN mkdir -p /data && chown -R agentdossier:agentdossier /data /app
USER agentdossier
VOLUME ["/data"]
ENV AGENTDOSSIER_DB=/data/agentdossier.db \
    AGENTDOSSIER_CATALOG_DIR=/data/catalog \
    AGENTDOSSIER_WEB_DIST=/app/web/dist \
    AGENTDOSSIER_SITE=http://localhost:8080/ \
    AGENTDOSSIER_TRUSTED_PROXIES=""
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"
# AGENTDOSSIER_AUTH_MODE must be set (token | oidc); the app refuses to start without it.
# Set AGENTDOSSIER_TRUSTED_PROXIES to your reverse proxy's address(es) so client IPs and the
# https scheme come from X-Forwarded-* only when a trusted proxy sent them.
CMD ["sh", "-c", "exec uvicorn --factory agentdossier.server.app:create_app --host 0.0.0.0 --port 8080 ${AGENTDOSSIER_TRUSTED_PROXIES:+--proxy-headers --forwarded-allow-ips \"$AGENTDOSSIER_TRUSTED_PROXIES\"}"]
