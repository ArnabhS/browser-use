from fastapi import FastAPI

app = FastAPI(title="browser-agent backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
