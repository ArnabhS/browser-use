from app.agent.demo import run
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


class FakeMemory:
    def __init__(self, preload=None):
        self.appends = []
        self.runs = []
        self._preload = preload or {}
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self, timeout: float = 2.0):
        self.stopped = True

    def append(self, thread_id, key, value):
        self.appends.append((thread_id, key, value))

    def append_run(self, thread_id, summary):
        self.runs.append((thread_id, summary))

    async def load(self, thread_id):
        return dict(self._preload)


async def test_remember_enqueues_write_and_finalize_appends_run():
    llm = FakeLLMClient(turns=[
        ai("note it", [{"name": "Remember", "args": {"key": "url", "value": "https://x"}, "id": "r1"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "all set"}, "id": "c1"}]),
    ])
    mem = FakeMemory()
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm, memory=mem)
    final = await run(graph, task="t", thread_id="tw", memory=mem)
    assert final.status == "done"
    assert ("tw", "url", "https://x") in mem.appends     # Remember enqueued a write
    assert mem.runs and mem.runs[0][0] == "tw"           # finalize appended a run summary


async def test_run_rehydrates_agent_memory_from_store():
    llm = FakeLLMClient(turns=[
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "c1"}]),
    ])
    mem = FakeMemory(preload={"prior": "fact"})
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm, memory=mem)
    final = await run(graph, task="t", thread_id="tw2", memory=mem)
    assert final.agent_memory.get("prior") == "fact"   # loaded from MEMORY.md before the run
