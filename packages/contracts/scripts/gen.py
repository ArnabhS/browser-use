"""Emit JSON Schema (camelCase) + a TS protocol-version constant from the Pydantic models."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src_py"))

from browser_agent_contracts import (  # noqa: E402
    PROTOCOL_VERSION,
    ActionCall,
    ActionResult,
    Envelope,
    Observation,
)

SCHEMA_DIR = ROOT / "schema"
GEN_TS_DIR = ROOT / "src" / "generated"

MODELS = {
    "observation": Observation,
    "action_call": ActionCall,
    "action_result": ActionResult,
    "envelope": Envelope,
}


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    GEN_TS_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        schema = model.model_json_schema(by_alias=True)
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        (SCHEMA_DIR / f"{name}.schema.json").write_text(text)
    (GEN_TS_DIR / "version.ts").write_text(
        f'export const PROTOCOL_VERSION = "{PROTOCOL_VERSION}";\n'
    )
    print("gen.py: wrote schema/*.json and src/generated/version.ts")


if __name__ == "__main__":
    main()
