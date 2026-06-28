import os
import pytest
from app.agent.run import run_task


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="needs a real OpenRouter key")
async def test_live_smoke_reaches_terminal_status():
    final = await run_task("Say the task is done by calling Complete(success=true).", thread_id="smoke")
    assert final.status in {"done", "failed"}
    assert final.step >= 1
