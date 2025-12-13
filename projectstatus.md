## Project Status – 2025-11-06

### Update – Alpaca-only data path (2025-11-12)
- Removed Polygon/Massive dependency across collectors, clients, and CLI. Market snapshots now rely solely on Alpaca plus optional news feeds.
- Option metrics are normalized from Alpaca option chains, while optional option aggregates come from Alpaca option bars when `ENABLE_OPTION_AGGREGATES=1`.
- TLS/DNS overrides remain available (`ALPACA_CA_BUNDLE`, `ALPACA_VERIFY_TLS`, `ALPACA_DATA_OVERRIDE_IP`) for environments with corporate CAs or flaky resolvers.
- AutoTrader loop and SnapshotStream continue to run in dry-run or paper/live modes using Alpaca execution only; intents still log to `data/logs/auto_trader.log`.
- Added `AlpacaStream` helper and `AUTO_USE_LIVE_STREAM` flag so snapshots can be enriched with live Alpaca bars between refreshes when desired.

### Data & Infrastructure
- Snapshot collection (`python -m trading_ai collect-snapshots`) caches Alpaca equity bars, option chains/metrics, optional option bars, and news; artifacts stay in JSON and ingest into DuckDB via `scripts/ingest_snapshot.py`.
- `.env.example` is trimmed to Alpaca + news keys. `OPTION_METRICS_LIMIT` caps how many chain entries are normalized per ticker to keep payloads manageable.
- `ENABLE_UNDERLYING_BARS` still gates whether equity bars are requested; keep it enabled for feature generation unless you intentionally want an option-only tape.

### Modeling & Backtesting
- Strategy stack (`MomentumIVStrategy` + `RiskManager` + `BacktestRunner`) is unchanged but now leans on Alpaca option chain/quotes/bars for liquidity, IV flow, and VWAP momentum.
- News aggregation covers Yahoo RSS plus optional Alpha Vantage, Marketaux, and NewsAPI feeds (whichever credentials you supply).

### Pending Work
1. Collect fresh market-hours snapshots via the cron/launchd helpers in `docs/scheduling.md`, ingest them into DuckDB, and rerun backtests.
2. Tune thresholds and `RiskManager` using the Alpaca-only data flow; review `data/logs/auto_trader.log` from dry-run cycles before enabling live orders.
3. Layer on monitoring/analytics once Alpaca option bar data is flowing consistently.
