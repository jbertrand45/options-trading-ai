## Project Status – 2025-11-06

### Data & Infrastructure
- Snapshot collection CLI (`python -m trading_ai collect-snapshots`) supports `--skip-news`/`--no-cache`; scheduling via `scripts/collect_snapshots.sh` with logs in `data/logs/`.
- Snapshots store intraday data as JSON; DuckDB ingestion (`scripts/ingest_snapshot.py`, `src/trading_ai/data/duckdb_store.py`) prepares them for analysis/backtests.
- `USE_POLYGON_BARS` flag controls whether we attempt Polygon equity bars (falls back to Alpaca IEX feed if plan limited). Current snapshots were collected after-hours, so `underlying_bars` is empty until we run during market hours or upgrade Polygon.

### Modeling & Backtesting
- Strategy stack: `MomentumIVStrategy` + `RiskManager` + `BacktestRunner` (invoked via `scripts/run_backtest.py`). Baseline run produced zero trades due to missing bars; once populated, results will flow to DuckDB for calibration.
- Multi-source news ingestion via `NewsAggregator`: Polygon reference news, Yahoo RSS (no key), and optional Alpha Vantage / Marketaux / NewsAPI.

### Pending Work
1. Run the snapshot script during market hours (manually or via the scheduling instructions in `docs/scheduling.md`) so `underlying_bars` is populated with real intraday data.
2. Ingest each captured JSON into DuckDB (`scripts/ingest_snapshot.py`) and run `scripts/run_backtest.py` to begin calibrating `MomentumIVStrategy`.
3. Once trades start appearing, tune thresholds/RiskManager toward the 10%+/day target and wire paper execution with bracket orders + circuit breakers.
