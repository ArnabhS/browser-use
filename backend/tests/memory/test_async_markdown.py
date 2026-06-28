# backend/tests/memory/test_async_markdown.py
import asyncio
from pathlib import Path

from app.memory.store import AsyncMarkdownMemory


async def test_append_writes_knowledge_file(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    try:
        mem.append("t1", "invoice_url", "https://x")
        mem.append("t1", "logged_in", "true")
        await asyncio.sleep(0.05)  # let the worker drain
    finally:
        await mem.stop()
    md = Path(tmp_path, "t1", "memory.md").read_text()
    assert "- **invoice_url**: https://x" in md and "- **logged_in**: true" in md


async def test_load_roundtrips_after_stop(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    mem.append("t2", "k", "v")
    await mem.stop()                      # stop drains remaining writes
    mem2 = AsyncMarkdownMemory(base_dir=str(tmp_path))
    assert await mem2.load("t2") == {"k": "v"}   # load needs no running worker


async def test_append_run_persists_summary(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    mem.append_run("t3", "did the task (done)")
    await mem.stop()
    md = Path(tmp_path, "t3", "memory.md").read_text()
    assert "- did the task (done)" in md


async def test_append_after_queue_full_drops_not_raises(tmp_path, caplog):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path), max_queue=1)
    # do NOT start the worker, so nothing drains; fill the queue past capacity
    mem.append("t4", "a", "1")
    mem.append("t4", "b", "2")   # queue full -> must drop + warn, never raise
    assert any("drop" in r.message.lower() or "full" in r.message.lower() for r in caplog.records)
