import json
import subprocess
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1]


def test_gen_writes_camelcase_schema_and_version_ts():
    subprocess.run([sys.executable, "scripts/gen.py"], cwd=CONTRACTS, check=True)

    obs_schema = json.loads((CONTRACTS / "schema/observation.schema.json").read_text())
    props = obs_schema["properties"]
    assert "protocolVersion" in props and "droppedCount" in props
    assert "snapshot" not in props and "html" not in props  # no raw DOM

    version_ts = (CONTRACTS / "src/generated/version.ts").read_text()
    assert "export const PROTOCOL_VERSION" in version_ts
