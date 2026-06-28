from app.memory.document import build_document, parse_knowledge, update_knowledge, append_run


def test_build_then_parse_roundtrips_knowledge():
    md = build_document({"a": "1", "b": "two"}, ["did a thing (done)"])
    assert "## Knowledge" in md and "## Run History" in md
    assert "- **a**: 1" in md and "- **b**: two" in md
    assert "- did a thing (done)" in md
    assert parse_knowledge(md) == {"a": "1", "b": "two"}


def test_parse_knowledge_ignores_run_history_and_malformed_lines():
    md = build_document({"k": "v"}, ["run one (done)"])
    # a stray line in Run History must not leak into knowledge
    assert parse_knowledge(md) == {"k": "v"}


def test_update_knowledge_adds_and_overwrites_in_place():
    md = build_document({"a": "1"}, [])
    md = update_knowledge(md, "b", "2")        # add
    md = update_knowledge(md, "a", "99")       # overwrite
    assert parse_knowledge(md) == {"a": "99", "b": "2"}


def test_append_run_keeps_newest_and_caps_length():
    md = build_document({}, [])
    for i in range(25):
        md = append_run(md, f"run {i} (done)", max_runs=20)
    runs = [ln for ln in md.splitlines() if ln.startswith("- ") and "run " in ln]
    assert len(runs) == 20            # capped
    assert "run 24 (done)" in md      # newest kept
    assert "run 4 (done)" not in md   # oldest dropped
