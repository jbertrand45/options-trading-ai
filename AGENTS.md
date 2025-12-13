# Repository Guidelines

## Project Structure & Module Organization
- `src/trading_ai/`: application code (clients, core collector/pipeline, risk, strategies, services). Key files: `service/auto_trader.py`, `core/collector.py`, `clients/alpaca_client.py`, `clients/alpaca_stream.py`.
- `tests/`: pytest suite mirroring src modules; fixtures/dummies live alongside each test file.
- `docs/`: operational notes and scheduling/strategy plans.
- `data/`: runtime artifacts (snapshots, logs, DuckDB). Avoid committing.
- `scripts/`: helper entrypoints for collection/backtests.

## Build, Test, and Development Commands
- Install deps (Poetry): `poetry install` (uses `poetry.lock`; Python 3.11 recommended).
- Run all tests: `python3.11 -m pytest` (or `poetry run pytest`).
- Check config quickly: `python3.11 -m trading_ai.cli check-config`.
- Collect snapshots: `python3.11 -m trading_ai.cli collect-snapshots --output data/snapshots ...`.
- Auto-trader (dry-run by default): `python3.11 -m trading_ai.cli auto-trade --lookback-minutes 120 --news-hours 3`.

## Coding Style & Naming Conventions
- Python 3.11; follow PEP8 with 4-space indents.
- Typing is expected; prefer explicit types on public functions.
- Keep modules cohesive (clients/* for API adapters, core/* for orchestration, service/* for long-running flows).
- Config via `Settings` in `src/trading_ai/settings.py`; env keys use uppercase snake case.

## Testing Guidelines
- Framework: pytest. Name tests `test_*.py`; functions `test_*`.
- Favor fast, isolated unit tests with dummies/mocks; network access should be mocked.
- Run `python3.11 -m pytest` before pushing; new features should include coverage in `tests/`.

## Commit & Pull Request Guidelines
- Keep commits focused; use clear, imperative messages (e.g., “Add Alpaca OAuth support”).
- PRs should describe scope, key changes, and testing performed; link issues if applicable.
- Include screenshots/log snippets only when they clarify behavior (UI/logging changes).

## Security & Configuration Tips
- For live trading: set `ALPACA_PAPER_ACCOUNT=0`; for safety/testing use `=1`.
- Never commit secrets; use `.env` (see `.env.example`). OAuth tokens go in `ALPACA_OAUTH_TOKEN`.
- Risk defaults are intentionally strict (3% stop, 2.5R TP, tight spreads/liquidity); adjust via env/CLI, not code, unless changing defaults.
