# AgentDossier self-hosted edition: one container with the scanner, the ARD REST API,
# /qualify, the scheduler and the web UI. Build from the repository root:
#   docker build -f deploy/Dockerfile -t agentdossier:latest .

# --- stage 1: the web UI, built for the root path -----------------------------------
FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY config /src/config
COPY docs /src/docs
COPY web ./
# The UI is served by the API at /, and reads /catalog/* from the same origin.
ENV SITE_BASE=/ SITE_URL=http://localhost:8080 CATALOG_DIR=/nonexistent PUBLIC_DYNAMIC_AGENTS=1
RUN npm run build

# --- stage 2: the Python service ------------------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 agentdossier
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY agentdossier ./agentdossier
COPY config ./config
COPY schema ./schema
COPY data/curated ./data/curated
COPY data/seed ./data/seed
COPY docs ./docs
RUN pip install --no-cache-dir ".[connectors,server,mcp]"
COPY --from=web /src/web/dist ./web/dist
RUN mkdir -p /data && chown -R agentdossier:agentdossier /data /app
USER agentdossier
VOLUME ["/data"]
ENV AGENTDOSSIER_DB=/data/agentdossier.db \
    AGENTDOSSIER_CATALOG_DIR=/data/catalog \
    AGENTDOSSIER_WEB_DIST=/app/web/dist \
    AGENTDOSSIER_SITE=http://localhost:8080/
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "agentdossier.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
