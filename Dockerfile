# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12
ARG TYPST_VERSION=0.15.1
ARG UV_VERSION=0.13.7
ARG NODE_VERSION=24.22.1

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- Typst binary -----------------------------------------------------------
FROM debian:bookworm-slim AS typst
ARG TYPST_VERSION
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN case "${TARGETARCH}" in \
      amd64) arch=x86_64 ;; \
      arm64) arch=aarch64 ;; \
      *) echo "unsupported arch ${TARGETARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${arch}-unknown-linux-musl.tar.xz" \
       | tar -xJ --strip-components=1 -C /usr/local/bin "typst-${arch}-unknown-linux-musl/typst"

# --- Frontend (React + Vite): type check, tests, build -----------------------
FROM node:${NODE_VERSION}-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run typecheck && npm test && npx vite build

# --- Python dependencies ----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --no-install-project
COPY application_crew ./application_crew
RUN uv sync --no-dev

# --- Semantic ranking model (job search), downloaded once at build time -----
# Must match [search].semantic_model in config.toml.
FROM builder AS models
ARG SEMANTIC_MODEL=jinaai/jina-embeddings-v2-base-de
RUN /opt/venv/bin/python -c "from fastembed import TextEmbedding; \
TextEmbedding('${SEMANTIC_MODEL}', cache_dir='/opt/models')"

# --- Runtime ----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /data && chown app:app /data
COPY --from=typst /usr/local/bin/typst /usr/local/bin/typst
COPY --from=builder /opt/venv /opt/venv
COPY --from=models /opt/models /opt/models
WORKDIR /app
COPY --chown=app:app application_crew ./application_crew
COPY --chown=app:app typst ./typst
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app config.toml ./
COPY --from=frontend --chown=app:app /frontend/dist ./frontend/dist
ENV PATH="/opt/venv/bin:${PATH}" \
    FASTEMBED_CACHE_PATH=/opt/models \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/data
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "application_crew.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Test image: `docker build --target test -t application-crew:test . && docker run --rm application-crew:test`
FROM runtime AS test
USER root
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* README.md ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --group dev
COPY --chown=app:app tests ./tests
USER app
CMD ["pytest", "-q"]
