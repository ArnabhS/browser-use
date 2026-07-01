---
title: Browser Agent Backend
emoji: 🧭
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Browser Agent — backend

FastAPI + LangGraph "brain" for the web-based browser-use agent. Drives a Playwright Chromium
per WebSocket session and streams every step to the cockpit UI over `/ws/run`.

The YAML front matter above configures this repo as a **Hugging Face Space** (Docker SDK, port
7860). It is ignored by GitHub and by Render / Cloud Run — safe to keep.

## Run locally

```bash
docker build -t browser-agent-backend .        # build context = repo root
docker run --rm -p 7860:7860 -e OPENROUTER_API_KEY=sk-... browser-agent-backend
# health: curl localhost:7860/health   ·   ws: ws://localhost:7860/ws/run
```

See `docs/` and `CLAUDE.md` for architecture.
