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
