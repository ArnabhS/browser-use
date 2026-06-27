from browser_agent_contracts import ActionCall, ActionResult
from app.telemetry.records import ErrorCode, StepRecord, TabInfo
from app.telemetry.store import InMemoryTrajectoryStore


def test_error_codes_exist():
    assert ErrorCode.REASONING_MISSING.value == "REASONING_MISSING"
    assert {e.value for e in ErrorCode} >= {"ACTION_TIMEOUT", "NO_ACTION", "MAX_STEPS"}


def test_step_record_defaults():
    rec = StepRecord(step=1, node="act", action=ActionCall(name="click", args={"index": 5}))
    assert rec.input_tokens == 0 and rec.error_code is None
    assert rec.action.args["index"] == 5


async def test_in_memory_trajectory_store_saves():
    store = InMemoryTrajectoryStore()
    await store.save("t1", StepRecord(step=1, node="observe"))
    await store.save("t1", StepRecord(step=2, node="reason"))
    assert [r.step for r in store.records["t1"]] == [1, 2]
