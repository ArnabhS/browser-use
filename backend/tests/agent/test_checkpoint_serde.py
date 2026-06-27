from __future__ import annotations

import logging
import warnings

import pytest

from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


@pytest.mark.asyncio
async def test_no_unregistered_type_warning_on_checkpoint_roundtrip(caplog):
    """Checkpoint round-trips must not emit 'Deserializing unregistered type' log warnings.

    capsys does not capture logger.warning() calls; caplog does.
    The warnings.catch_warnings block turns any Python-level warning into an error
    as an extra guard, while caplog catches the langgraph logger output.
    """
    llm = FakeLLMClient(turns=[ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "1"}])])
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=llm)
    with caplog.at_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus"):
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any Python warning becomes an error
            final = await run(graph, task="t", thread_id="t1")
    assert final.status == "done"
    assert "Deserializing unregistered type" not in caplog.text
