set dotenv-load := false

python := "python"
export PYTHONPATH := "packages/contracts-python/src:packages/runtime-python/src:services/event-hub:services/fusion-runtime:services/safety-gateway:services/robot-simulator:services/session-recorder:services/console-api:services/ganglion-adapter:services/audio-adapter:services/vision-adapter"

bootstrap:
    {{python}} -m pip install -e ".[dev]"
    pnpm install

contracts-test:
    {{python}} -m pytest tests/contract -q
    pnpm --filter @intent/contracts test

preflight:
    {{python}} scripts/preflight.py

run-mocks:
    {{python}} scripts/run_stack.py --mock

demo *args:
    {{python}} scripts/demo_mvp.py {{args}}

soak-biosignals *args:
    {{python}} scripts/soak_biosignals.py {{args}}

run-hardware:
    {{python}} scripts/run_stack.py --hardware --confirm

test:
    {{python}} -m pytest tests -q
    pnpm -r test

replay SESSION:
    {{python}} -m session_recorder.replay --session {{SESSION}}

lint:
    {{python}} -m ruff check packages services tests scripts
    pnpm -r lint

format:
    {{python}} -m ruff format packages services tests scripts
