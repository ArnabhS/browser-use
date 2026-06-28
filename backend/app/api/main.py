from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ws import ws_run

app = FastAPI(title="browser-agent backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_api_websocket_route("/ws/run", ws_run)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
