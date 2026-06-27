from browser_agent_contracts import (
    PROTOCOL_VERSION, Observation, ActionCall, ActionResult, Envelope, Viewport, Element,
)


def test_protocol_version_is_nonempty_string():
    assert isinstance(PROTOCOL_VERSION, str) and PROTOCOL_VERSION


def test_observation_roundtrips_via_camelcase_aliases():
    obs = Observation(
        url="https://example.com",
        title="Example",
        viewport=Viewport(width=1280, height=800, scrollX=0, scrollY=0),
        elements=[Element(index=1, role="button", name="Login")],
    )
    dumped = obs.model_dump(by_alias=True)
    assert dumped["protocolVersion"] == PROTOCOL_VERSION
    assert dumped["droppedCount"] == 0
    assert dumped["viewport"]["scrollX"] == 0
    # round-trips back from the camelCase wire form
    assert Observation.model_validate(dumped).elements[0].name == "Login"


def test_observation_has_no_coordinate_or_dom_fields():
    fields = set(Observation.model_fields)
    assert not (fields & {"x", "y", "center_x", "center_y", "dom", "html", "snapshot"})


def test_action_call_and_result_and_envelope():
    assert ActionCall(name="click", args={"index": 5}).args["index"] == 5
    assert ActionResult(success=False, reason="timeout", errorCode="ACTION_TIMEOUT").error_code == "ACTION_TIMEOUT"
    env = Envelope(type="observation", payload={"a": 1})
    assert env.model_dump(by_alias=True)["protocolVersion"] == PROTOCOL_VERSION
