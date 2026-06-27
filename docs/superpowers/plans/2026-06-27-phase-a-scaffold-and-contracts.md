# Phase A — Monorepo Scaffold + Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the monorepo for all four units (backend, frontend, bridge-extension, packages/contracts) so each installs and builds, with a working Pydantic-first contracts pipeline (Pydantic v2 → JSON Schema → Zod) and a local drift guard.

**Architecture:** A pnpm workspace (JS units) + a uv-managed Python backend, orchestrated by a `justfile`. `packages/contracts` is the single source of truth: Pydantic v2 models authored in Python emit JSON Schema, from which Zod/TS types are generated; the backend imports the Python models directly via a uv path dependency, and the frontend/extension import the generated `@browser-agent/contracts` package.

**Tech Stack:** Python 3.12+, uv, FastAPI, Pydantic v2; pnpm workspace, TypeScript, Vite, React 18, Tailwind v4, Zod, vitest; `just` task runner; `json-schema-to-zod` for codegen.

## Global Constraints

- **Python ≥ 3.12**, backend managed by **uv**; JS units managed by **pnpm** workspace.
- **Pydantic v2 is the contracts source of truth.** Wire types (`Observation`, `ActionCall`, `ActionResult`, `Envelope`) are authored ONCE in `packages/contracts/src_py/`; never redefine them elsewhere. The TS/Zod side is **generated**, never hand-edited.
- **Wire format is camelCase** (`protocolVersion`, `screenshotRef`, `droppedCount`, `scrollX`, `scrollY`, `errorCode`); Python uses snake_case with Pydantic aliases; schema is emitted `by_alias=True`.
- `Observation` carries **no coordinates and no raw DOM**.
- Every wire message carries `protocolVersion`; the constant `PROTOCOL_VERSION` lives in `packages/contracts`.
- **`OPENROUTER_API_KEY` is server-side only**, read from a **gitignored `.env`**; never commit it; never ship it to frontend or extension.
- **Generated artifacts are committed** (`packages/contracts/schema/*.json`, `packages/contracts/src/generated/*.ts`); `just check` regenerates and fails on drift.
- Use **exact** versions/commands below; if `uv`/`pnpm` resolves a newer compatible version, that's fine — do not downgrade.

## File Structure

```
browser-use/
├─ .gitignore · .env.example · pnpm-workspace.yaml · package.json · justfile · CLAUDE.md
├─ packages/contracts/
│  ├─ pyproject.toml                         # the Python package "browser-agent-contracts"
│  ├─ src_py/browser_agent_contracts/
│  │  ├─ __init__.py                          # exports models + PROTOCOL_VERSION
│  │  ├─ version.py                           # PROTOCOL_VERSION
│  │  └─ models.py                            # Observation, ActionCall, ActionResult, Envelope, Viewport, Element
│  ├─ tests/test_models.py                    # pytest: validation + round-trip + schema shape
│  ├─ scripts/gen.py                          # Pydantic → schema/*.json + generated/version.ts
│  ├─ scripts/gen-zod.mjs                     # schema/*.json → src/generated/*.ts (Zod)
│  ├─ schema/*.schema.json                    # generated, committed
│  ├─ src/generated/*.ts                      # generated, committed (Zod + version)
│  ├─ src/index.ts                            # re-exports generated
│  ├─ tests/contracts.test.ts                 # vitest: Zod parses valid / rejects invalid
│  ├─ package.json · tsconfig.json            # @browser-agent/contracts
├─ backend/
│  ├─ pyproject.toml                          # uv; deps incl. path-dep on contracts
│  ├─ app/__init__.py
│  ├─ app/api/{__init__.py,main.py}           # FastAPI + /health
│  ├─ app/config/{__init__.py,settings.py}    # Settings (env)
│  ├─ app/{agent,tools,prompt,prompts,memory,events,browser,observation,actions,llm,telemetry}/__init__.py   # Phase B dirs (empty)
│  └─ tests/test_health.py
├─ frontend/    # Vite + React + TS + Tailwind v4, consumes @browser-agent/contracts (scaffold)
└─ bridge-extension/   # MV3 + plain Vite, consumes @browser-agent/contracts (scaffold)
```

---

### Task 1: Root tooling, workspace, git hygiene, promote CLAUDE.md

**Files:**
- Create: `.gitignore`, `.env.example`, `pnpm-workspace.yaml`, `package.json`, `justfile`, `CLAUDE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the `justfile` recipes `setup`, `gen-contracts`, `check`, `test`, `dev-backend`, `dev-frontend` (other tasks rely on these names); the pnpm workspace globs; `CLAUDE.md` at root.

- [ ] **Step 1: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.pyc
.venv/
# Node
node_modules/
dist/
# Env & secrets
.env
.env.local
# Agent run artifacts (memory.md, trajectories)
runs/
# OS / IDE
.DS_Store
```

- [ ] **Step 2: Create `.env.example`**

```bash
# Copy to .env (gitignored) and fill in. Server-side only — never shipped to FE/extension.
OPENROUTER_API_KEY=
AGENT_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

- [ ] **Step 3: Create `pnpm-workspace.yaml`**

```yaml
packages:
  - "packages/*"
  - "frontend"
  - "bridge-extension"
```

- [ ] **Step 4: Create root `package.json`**

```json
{
  "name": "browser-agent-monorepo",
  "private": true,
  "version": "0.0.0"
}
```

- [ ] **Step 5: Create `justfile`**

```make
set shell := ["bash", "-uc"]

# Install everything (backend env, Chromium for Phase B, JS workspace, build contracts)
setup:
    cd backend && uv sync
    uv run --project backend playwright install chromium
    pnpm install
    just gen-contracts

# Regenerate contracts: Pydantic -> JSON Schema -> Zod -> build the TS package
gen-contracts:
    uv run --project backend python packages/contracts/scripts/gen.py
    node packages/contracts/scripts/gen-zod.mjs
    pnpm -C packages/contracts build

# Drift guard: regenerate and fail if committed artifacts changed
check: gen-contracts
    git diff --exit-code -- packages/contracts/schema packages/contracts/src/generated

# Run all tests
test:
    cd backend && uv run pytest -q
    cd backend && uv run pytest -q ../packages/contracts/tests
    pnpm -r test

# Dev servers
dev-backend:
    cd backend && uv run uvicorn app.api.main:app --reload

dev-frontend:
    pnpm -C frontend dev
```

- [ ] **Step 6: Promote the source contract to root `CLAUDE.md`**

Run: `cp .idea/CLAUDE-browser-agent-web.md CLAUDE.md`
Expected: `CLAUDE.md` exists at repo root.

- [ ] **Step 7: Verify the justfile parses**

Run: `just --list`
Expected: lists `setup`, `gen-contracts`, `check`, `test`, `dev-backend`, `dev-frontend`. (If `just` is missing: `brew install just`.)

- [ ] **Step 8: Verify `.env` is ignored**

Run: `touch .env && git check-ignore .env && rm .env`
Expected: prints `.env` (it is ignored).

- [ ] **Step 9: Commit**

```bash
git add .gitignore .env.example pnpm-workspace.yaml package.json justfile CLAUDE.md
git commit -m "chore: root tooling, pnpm workspace, justfile, promote CLAUDE.md"
```

---

### Task 2: Contracts — Pydantic source models (TDD)

**Files:**
- Create: `packages/contracts/pyproject.toml`, `packages/contracts/src_py/browser_agent_contracts/__init__.py`, `.../version.py`, `.../models.py`
- Test: `packages/contracts/tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (imported by the backend and by `scripts/gen.py`):
  - `PROTOCOL_VERSION: str`
  - `Observation`, `ActionCall`, `ActionResult`, `Envelope`, `Viewport`, `Element` (Pydantic v2 `BaseModel`s).
  - `Observation` fields: `url:str`, `title:str=""`, `viewport:Viewport`, `elements:list[Element]=[]`, `protocol_version:str` (alias `protocolVersion`), `screenshot_ref:str|None` (alias `screenshotRef`), `changed:str|None`, `dropped_count:int=0` (alias `droppedCount`).
  - `ActionCall`: `name:str`, `args:dict=...{}`. `ActionResult`: `success:bool`, `reason:str=""`, `error_code:str|None` (alias `errorCode`). `Envelope`: `protocol_version` (alias `protocolVersion`), `type:str`, `payload:dict={}`.

- [ ] **Step 1: Create the Python package config `packages/contracts/pyproject.toml`**

```toml
[project]
name = "browser-agent-contracts"
version = "0.1.0"
description = "Shared wire contracts (source of truth) for the browser agent."
requires-python = ">=3.12"
dependencies = ["pydantic>=2.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src_py/browser_agent_contracts"]

[dependency-groups]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
pythonpath = ["src_py"]
```

- [ ] **Step 2: Write the failing test `packages/contracts/tests/test_models.py`**

```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd packages/contracts && uv run --with pydantic --with pytest pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'browser_agent_contracts'`.

- [ ] **Step 4: Create `packages/contracts/src_py/browser_agent_contracts/version.py`**

```python
PROTOCOL_VERSION = "1.0.0"
```

- [ ] **Step 5: Create `packages/contracts/src_py/browser_agent_contracts/models.py`**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .version import PROTOCOL_VERSION

_CAMEL = ConfigDict(populate_by_name=True)


class Viewport(BaseModel):
    model_config = _CAMEL
    width: int
    height: int
    scroll_x: int = Field(default=0, alias="scrollX")
    scroll_y: int = Field(default=0, alias="scrollY")


class Element(BaseModel):
    index: int
    role: str
    name: str = ""
    value: str | None = None


class Observation(BaseModel):
    model_config = _CAMEL
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    url: str
    title: str = ""
    viewport: Viewport
    elements: list[Element] = Field(default_factory=list)
    screenshot_ref: str | None = Field(default=None, alias="screenshotRef")
    changed: str | None = None
    dropped_count: int = Field(default=0, alias="droppedCount")


class ActionCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    model_config = _CAMEL
    success: bool
    reason: str = ""
    error_code: str | None = Field(default=None, alias="errorCode")


class Envelope(BaseModel):
    model_config = _CAMEL
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 6: Create `packages/contracts/src_py/browser_agent_contracts/__init__.py`**

```python
from .models import ActionCall, ActionResult, Element, Envelope, Observation, Viewport
from .version import PROTOCOL_VERSION

__all__ = [
    "PROTOCOL_VERSION",
    "Observation",
    "ActionCall",
    "ActionResult",
    "Envelope",
    "Viewport",
    "Element",
]
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd packages/contracts && uv run --with pydantic --with pytest pytest tests/test_models.py -v`
Expected: PASS — 4 passed.

- [ ] **Step 8: Commit**

```bash
git add packages/contracts/pyproject.toml packages/contracts/src_py packages/contracts/tests/test_models.py
git commit -m "feat(contracts): Pydantic v2 wire models (source of truth)"
```

---

### Task 3: Contracts — Pydantic → JSON Schema generator (TDD)

**Files:**
- Create: `packages/contracts/scripts/gen.py`
- Create (generated, committed): `packages/contracts/schema/{observation,action_call,action_result,envelope}.schema.json`, `packages/contracts/src/generated/version.ts`
- Test: `packages/contracts/tests/test_gen.py`

**Interfaces:**
- Consumes: `browser_agent_contracts` models (Task 2).
- Produces: `schema/*.schema.json` (camelCase, `by_alias=True`, sorted keys) and `src/generated/version.ts` (`export const PROTOCOL_VERSION`). `scripts/gen.py` exposes `main()` and a `MODELS` dict mapping `snake_name → model`.

- [ ] **Step 1: Write the failing test `packages/contracts/tests/test_gen.py`**

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd packages/contracts && uv run --with pydantic --with pytest pytest tests/test_gen.py -v`
Expected: FAIL — `No such file or directory: 'scripts/gen.py'`.

- [ ] **Step 3: Create `packages/contracts/scripts/gen.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd packages/contracts && uv run --with pydantic --with pytest pytest tests/test_gen.py -v`
Expected: PASS — 1 passed; `schema/*.schema.json` and `src/generated/version.ts` now exist.

- [ ] **Step 5: Commit (including the generated artifacts)**

```bash
git add packages/contracts/scripts/gen.py packages/contracts/tests/test_gen.py \
        packages/contracts/schema packages/contracts/src/generated/version.ts
git commit -m "feat(contracts): generate JSON Schema + version.ts from Pydantic"
```

---

### Task 4: Contracts — JSON Schema → Zod package (TDD)

**Files:**
- Create: `packages/contracts/scripts/gen-zod.mjs`, `packages/contracts/package.json`, `packages/contracts/tsconfig.json`, `packages/contracts/src/index.ts`
- Create (generated, committed): `packages/contracts/src/generated/{observation,action_call,action_result,envelope}.ts`
- Test: `packages/contracts/tests/contracts.test.ts`

**Interfaces:**
- Consumes: `schema/*.schema.json` (Task 3).
- Produces: the `@browser-agent/contracts` workspace package exporting `ObservationSchema`, `ActionCallSchema`, `ActionResultSchema`, `EnvelopeSchema` (Zod) and `PROTOCOL_VERSION` (from `src/index.ts`). Consumed by frontend (Task 6) and extension (Task 7).

- [ ] **Step 1: Create `packages/contracts/package.json`**

```json
{
  "name": "@browser-agent/contracts",
  "version": "0.1.0",
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": { ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js" } },
  "files": ["dist"],
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run"
  },
  "dependencies": { "zod": "^3.23.0" },
  "devDependencies": {
    "json-schema-to-zod": "^2.4.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Create `packages/contracts/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "declaration": true,
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create `packages/contracts/scripts/gen-zod.mjs`**

```javascript
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { jsonSchemaToZod } from "json-schema-to-zod";

const here = dirname(fileURLToPath(import.meta.url));
const schemaDir = resolve(here, "..", "schema");
const outDir = resolve(here, "..", "src", "generated");
mkdirSync(outDir, { recursive: true });

const pascal = (s) =>
  s.split(/[_-]/).map((w) => w[0].toUpperCase() + w.slice(1)).join("");

for (const file of readdirSync(schemaDir).filter((f) => f.endsWith(".schema.json"))) {
  const base = file.replace(".schema.json", "");
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"));
  const name = `${pascal(base)}Schema`;
  const code = jsonSchemaToZod(schema, { name, module: "esm" });
  writeFileSync(join(outDir, `${base}.ts`), `${code}\n`);
  console.log(`gen-zod: wrote src/generated/${base}.ts`);
}
```

- [ ] **Step 4: Create `packages/contracts/src/index.ts`**

```typescript
export * from "./generated/version";
export * from "./generated/observation";
export * from "./generated/action_call";
export * from "./generated/action_result";
export * from "./generated/envelope";
```

- [ ] **Step 5: Install workspace deps and generate the Zod files**

Run: `pnpm install && node packages/contracts/scripts/gen-zod.mjs`
Expected: prints `gen-zod: wrote src/generated/observation.ts` (and the other three); files exist.

- [ ] **Step 6: Write the failing test `packages/contracts/tests/contracts.test.ts`**

```typescript
import { describe, it, expect } from "vitest";
import { ObservationSchema } from "../src/generated/observation";
import { PROTOCOL_VERSION } from "../src/generated/version";

describe("Observation contract", () => {
  it("parses a valid observation", () => {
    const ok = ObservationSchema.parse({
      protocolVersion: PROTOCOL_VERSION,
      url: "https://example.com",
      title: "Example",
      viewport: { width: 1280, height: 800, scrollX: 0, scrollY: 0 },
      elements: [{ index: 1, role: "button", name: "Login" }],
      droppedCount: 0,
    });
    expect(ok.url).toBe("https://example.com");
  });

  it("rejects an observation with a wrong-typed url", () => {
    expect(() => ObservationSchema.parse({ url: 123, viewport: {} })).toThrow();
  });
});
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `pnpm -C packages/contracts test`
Expected: PASS — 2 passed.

- [ ] **Step 8: Build the package and verify dist**

Run: `pnpm -C packages/contracts build`
Expected: `packages/contracts/dist/index.js` and `dist/index.d.ts` exist; no tsc errors.

- [ ] **Step 9: Commit (including generated Zod + dist is gitignored)**

```bash
git add packages/contracts/package.json packages/contracts/tsconfig.json \
        packages/contracts/scripts/gen-zod.mjs packages/contracts/src/index.ts \
        packages/contracts/src/generated packages/contracts/tests/contracts.test.ts \
        pnpm-lock.yaml
git commit -m "feat(contracts): generate Zod from JSON Schema; @browser-agent/contracts package"
```

---

### Task 5: Backend — uv project, app skeleton, /health (TDD)

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/api/__init__.py`, `backend/app/api/main.py`, `backend/app/config/__init__.py`, `backend/app/config/settings.py`
- Create (empty Phase B package dirs, each with `__init__.py`): `backend/app/{agent,tools,prompt,prompts,memory,events,browser,observation,actions,llm,telemetry}/__init__.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `browser_agent_contracts` (Task 2) via uv path dependency.
- Produces: an importable `app` package; `app.api.main:app` (FastAPI) with `GET /health` → `{"status": "ok"}`; `app.config.settings.Settings` (`openrouter_api_key`, `agent_model`, `openrouter_base_url`).

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "browser-agent-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.34",
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "python-dotenv>=1.0",
  "httpx>=0.27",
  "langgraph>=0.2",
  "langchain-core>=0.3",
  "langchain-openai>=0.2",
  "jinja2>=3.1",
  "aiofiles>=24.1",
  "playwright>=1.48",
  "browser-agent-contracts",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]

[tool.uv.sources]
browser-agent-contracts = { path = "../packages/contracts", editable = true }

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: Create the app package skeleton**

Run:
```bash
mkdir -p backend/app/api backend/app/config backend/tests
mkdir -p backend/app/{agent,tools,prompt,prompts,memory,events,browser,observation,actions,llm,telemetry}
touch backend/app/__init__.py
for d in agent tools prompt prompts memory events browser observation actions llm telemetry; do touch "backend/app/$d/__init__.py"; done
```
Expected: the directory tree exists with `__init__.py` files (these Phase B dirs stay empty for now).

- [ ] **Step 3: Create `backend/app/config/__init__.py` and `backend/app/config/settings.py`**

`backend/app/config/__init__.py`:
```python
from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
```

`backend/app/config/settings.py`:
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    agent_model: str = "anthropic/claude-sonnet-4.6"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write the failing test `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.api.main import app


def test_health_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Sync deps and run the test to verify it fails**

Run: `cd backend && uv sync && uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.main'`.

- [ ] **Step 6: Create `backend/app/api/__init__.py` and `backend/app/api/main.py`**

`backend/app/api/__init__.py`:
```python
```

`backend/app/api/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="browser-agent backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: PASS — 1 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests/test_health.py backend/uv.lock
git commit -m "feat(backend): uv project, app skeleton, /health endpoint"
```

---

### Task 6: Frontend — Vite + React + Tailwind v4 scaffold consuming contracts

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `@browser-agent/contracts` (Task 4) — imports `PROTOCOL_VERSION` to prove the workspace wiring.
- Produces: a buildable React app (scaffold only; the real cockpit is M2).

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "echo \"no frontend tests yet\" && exit 0"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zod": "^3.23.0",
    "@browser-agent/contracts": "workspace:*"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^4.0.0",
    "@tailwindcss/vite": "^4.0.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
});
```

- [ ] **Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Browser Agent — Cockpit</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create `frontend/src/index.css`**

```css
@import "tailwindcss";
```

- [ ] **Step 6: Create `frontend/src/App.tsx`**

```tsx
import { PROTOCOL_VERSION } from "@browser-agent/contracts";

export default function App() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-neutral-950 text-neutral-100">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Browser Agent — Cockpit</h1>
        <p className="mt-2 text-neutral-400">
          Scaffold. Protocol v{PROTOCOL_VERSION}.
        </p>
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Create `frontend/src/main.tsx`**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 8: Install and build to verify**

Run: `pnpm install && pnpm -C frontend build`
Expected: build succeeds; `frontend/dist/index.html` exists. (Requires the contracts package built — Task 4 Step 8 / `just gen-contracts`.)

- [ ] **Step 9: Commit**

```bash
git add frontend pnpm-lock.yaml
git commit -m "feat(frontend): Vite + React + Tailwind v4 scaffold consuming contracts"
```

---

### Task 7: Extension — MV3 + plain Vite scaffold consuming contracts

**Files:**
- Create: `bridge-extension/package.json`, `bridge-extension/vite.config.ts`, `bridge-extension/tsconfig.json`, `bridge-extension/public/manifest.json`, `bridge-extension/src/background/index.ts`

**Interfaces:**
- Consumes: `@browser-agent/contracts` (Task 4) — imports `PROTOCOL_VERSION` in the service-worker stub.
- Produces: a buildable MV3 extension (background SW stub only; the funnel + `chrome.debugger` dispatch are M3).

- [ ] **Step 1: Create `bridge-extension/package.json`**

```json
{
  "name": "bridge-extension",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "build": "vite build",
    "test": "echo \"no extension tests yet\" && exit 0"
  },
  "dependencies": {
    "@browser-agent/contracts": "workspace:*"
  },
  "devDependencies": {
    "@types/chrome": "^0.0.270",
    "typescript": "^5.6.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: Create `bridge-extension/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import { resolve } from "node:path";

// Plain Vite for the scaffold: build the SW entry, copy public/manifest.json to dist.
// @crxjs/vite-plugin (content scripts, HMR) arrives in M3.
export default defineConfig({
  publicDir: "public",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: { background: resolve(__dirname, "src/background/index.ts") },
      output: { entryFileNames: "[name].js", format: "es" },
    },
  },
});
```

- [ ] **Step 3: Create `bridge-extension/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM"],
    "types": ["chrome"],
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `bridge-extension/public/manifest.json`**

```json
{
  "manifest_version": 3,
  "name": "Browser Agent Bridge",
  "version": "0.0.1",
  "description": "Bridges the browser-agent backend to the user's Chrome (scaffold).",
  "background": { "service_worker": "background.js", "type": "module" },
  "permissions": ["debugger", "tabs"],
  "host_permissions": ["<all_urls>"]
}
```

- [ ] **Step 5: Create `bridge-extension/src/background/index.ts`**

```typescript
import { PROTOCOL_VERSION } from "@browser-agent/contracts";

// Scaffold service worker: confirms the contracts wiring loads in an MV3 context.
console.log(`[bridge] service worker loaded; wire protocol v${PROTOCOL_VERSION}`);
```

- [ ] **Step 6: Install and build to verify**

Run: `pnpm install && pnpm -C bridge-extension build`
Expected: build succeeds; `bridge-extension/dist/manifest.json` and `bridge-extension/dist/background.js` exist.

- [ ] **Step 7: Commit**

```bash
git add bridge-extension pnpm-lock.yaml
git commit -m "feat(extension): MV3 + Vite scaffold consuming contracts"
```

---

### Task 8: End-to-end verification + drift guard

**Files:**
- Modify (only if a command reveals a fix is needed): `justfile`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: a green `just setup`, `just gen-contracts`, `just check`, `just test` — the Phase A acceptance gate.

- [ ] **Step 1: Clean install everything**

Run: `just setup`
Expected: `uv sync` resolves; `playwright install chromium` downloads Chromium; `pnpm install` links the workspace; `just gen-contracts` regenerates + builds contracts. No errors.

- [ ] **Step 2: Verify the contracts drift guard is clean**

Run: `just check`
Expected: regenerates schema + Zod, then `git diff --exit-code` prints nothing and exits 0 (no drift). If it fails, the committed generated files are stale — run `just gen-contracts`, commit the regenerated files, and re-run.

- [ ] **Step 3: Run the full test suite**

Run: `just test`
Expected: backend `pytest` passes (`test_health`); the contracts Python tests pass (`test_models`: 4 passed, `test_gen`: 1 passed); `pnpm -r test` passes (contracts vitest: 2 passed; frontend/extension print their no-test stubs).

- [ ] **Step 4: Verify each unit builds**

Run: `pnpm -C packages/contracts build && pnpm -C frontend build && pnpm -C bridge-extension build`
Expected: all three succeed; `frontend/dist/index.html` and `bridge-extension/dist/manifest.json` exist.

- [ ] **Step 5: Sanity-check the backend boots**

Run: `cd backend && uv run python -c "from app.api.main import app; print('ok', [r.path for r in app.routes])"`
Expected: prints `ok` and a list including `/health`.

- [ ] **Step 6: Commit any justfile fixes (if Steps 1–5 required edits)**

```bash
git add justfile
git commit -m "chore: finalize justfile; Phase A acceptance green"
```

---

## Self-Review

**Spec coverage (against the design spec §2 Phase A, §4 layout, §5 contracts pipeline, §9 acceptance):**
- Scaffold all 4 units → Tasks 5 (backend), 6 (frontend), 7 (extension), 2–4 (contracts). ✓
- Base config per unit (pyproject/package.json/manifest/vite) → Tasks 5/6/7. ✓
- Contracts source of truth Pydantic→JSON Schema→Zod → Tasks 2/3/4. ✓
- Root tooling (pnpm-workspace, justfile, .env.example), promote CLAUDE.md → Task 1. ✓
- `just gen-contracts` + `just check` drift guard → Tasks 1 + 8. ✓
- Acceptance (`just setup`/`gen-contracts`/`check` clean; pytest green; FE/extension build) → Task 8. ✓
- Backend app skeleton dirs for Phase B (agent/tools/prompt/prompts/memory/events/browser/observation/actions/llm/telemetry) → Task 5 Step 2. ✓

**Placeholder scan:** No "TBD/TODO/handle errors/etc." — every code/command step is concrete. ✓

**Type consistency:** `PROTOCOL_VERSION`, model names (`Observation`/`ActionCall`/`ActionResult`/`Envelope`), generated Zod names (`<Pascal>Schema`), the `MODELS` keys (`observation`/`action_call`/`action_result`/`envelope`) and the resulting file names (`*.schema.json`, `src/generated/*.ts`) are consistent across gen.py (Task 3), gen-zod.mjs (Task 4), and the index/test imports. ✓

**Out of scope (correctly deferred to Phase B / later):** the agent loop, LocalCDPSession + funnel, tools/memory/prompts/events subsystems, the real cockpit, `@crxjs` extension build, CI drift gate.
