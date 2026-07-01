# syntax=docker/dockerfile:1
#
# Backend image for the browser-agent "brain" (FastAPI + LangGraph + Playwright Chromium).
#
# IMPORTANT: build from the REPO ROOT, not from backend/. The backend has an editable path
# dependency on packages/contracts (see backend/pyproject.toml [tool.uv.sources]), so both
# trees must be in the build context:
#     docker build -t browser-agent-backend .
#
# Base = official uv image on Python 3.12 (Debian bookworm slim); uv + Python already present.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Chromium is launched as a per-session subprocess. Install it to a world-readable path so a
# non-root runtime user (e.g. Hugging Face Spaces' UID 1000) can still execute it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    # Cloud containers have no display — settings.py defaults cdp_headless to False, so force it.
    CDP_HEADLESS=true

WORKDIR /app

# The editable path dep must be present for uv to resolve it.
COPY packages/contracts ./packages/contracts

# Copy dependency manifests first so the (slow) dependency layer caches across source edits.
COPY backend/pyproject.toml backend/uv.lock ./backend/

WORKDIR /app/backend
RUN uv sync --frozen --no-dev --no-install-project

# Now the backend source, then install the project itself (editable).
COPY backend ./
RUN uv sync --frozen --no-dev

# Chromium binary + its apt system libraries. Needs root + apt; make it world-readable so the
# non-root runtime user below can launch it.
RUN uv run --no-sync playwright install --with-deps chromium \
    && chmod -R a+rx /ms-playwright

# Drop to a non-root user. Hugging Face Spaces runs the container as UID 1000; harmless on
# Render / Cloud Run (they only need the process to bind the port).
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user
ENV PATH="/app/backend/.venv/bin:$PATH"

# HF Spaces expects the app on 7860 (PORT unset → default). Render / Cloud Run inject $PORT.
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
