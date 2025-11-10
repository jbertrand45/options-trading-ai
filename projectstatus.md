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

### Update – UTC snapshots + fallback quotes (2025‑11‑06)
- Implemented robust snapshot capture: Alpaca latest trades now synthesize single-bar windows when standard 1‑min history is unavailable, while Polygon fallback attempts are logged when the current plan blocks intraday data.
- Added `ALPACA_DATA_FEED` config knob so SIP subscribers can pull full-session minute bars; default remains `IEX` (RTH only). Polygon Options Developer subscribers can now set `USE_POLYGON_BARS=1` to pull equity aggregates directly from Polygon.
- Added optional `POLYGON_API_OVERRIDE_IP` support and `POLYGON_BASE_URL`, so we can point the client at `https://api.massive.com` (Massive rebrand) while pinning to a known IP if DNS is unstable. After updating `.env` with the Massive host/key, rerun `USE_POLYGON_BARS=1 poetry run python -m trading_ai collect-snapshots … --skip-news` to confirm minute bars before backtesting.
- Option contract greeks/open-interest are now ingested via Polygon/Massive’s `list_options_contracts`. Snapshots include an `option_metrics` block per ticker, DuckDB persists it, and `MomentumIVStrategy` uses those greeks/IVs when Alpaca’s chain lacks the data. Tune `OPTION_METRICS_LIMIT` in `.env` if you need tighter limits to stay under API quotas.
- Latest snapshot runs (`snapshots_20251107_153403.json`, `154548.json`) confirm minute aggregates are flowing, but news arrays remain empty because external news providers (newsapi.org/Massive) still hit DNS/permission errors on this machine. To re-enable news, supply valid NEWS_API credentials or resolve outbound DNS to `newsapi.org`/`api.massive.com`. In the meantime, Yahoo RSS + cached stories continue to work from `data/cache/news/...`.
- Backtester now consumes nine trades with real minute bars + greeks, but P&L remains negative due to placeholder exit logic. Next work session: (1) fix news provider DNS/keys, (2) leverage the new `option_metrics` data in additional features (vega/theta filters), and (3) refine the exit/PNL model so trades reflect realistic fills.

**Next up**
1. Resolve outbound DNS/auth for Massive news endpoints (or provide working credentials) so `news` arrays populate again.
2. Extend the feature pipeline/strategy to consume `option_metrics` (e.g., screen contracts by IV, open interest, greeks) when generating signals.
3. Replace the backtester’s placeholder exit logic with a model driven by actual underlying movement or option quotes now that full minute bars are available.
- Option reference quotes persist ATM strikes, bid/ask, and implied metadata for both CALL/PUT legs, enabling the backtester to price trades from actual spreads.
- `MomentumIVStrategy` relaxed thresholds and added feature/quote fallbacks plus baseline confidence, so signals fire even when IV deltas are missing.
- DuckDB ingestion coerces timestamps and uses registered DataFrames to accept both full bar sets and synthetic single-bar rows.
- Latest snapshot (`data/snapshots/snapshots_20251107_012059.json`) ingested successfully; backtest now produces 3 trades (call-heavy, currently negative P&L due to placeholder exit assumptions). Need real intraday bars (Polygon upgrade or market-hours Alpaca SIP) and refined exit logic for meaningful calibration.

### Update – Automation loop + execution plumbing (2025‑11‑08)
- Built `trading_ai.service.auto_trader.AutoTrader` plus CLI/subcommand + shell wrapper so snapshots, signal scoring, and (dry-run) option order intents can run continuously; every intent is logged to `data/logs/auto_trader.log` for review and downstream analytics.
- Alpaca client now exposes `submit_option_order`, unlocking paper-option entries once we enable `auto-trade --live`. Strategy thresholds/risk knobs can be tuned from `.env` via new `AUTO_*` variables so confidence and sizing stay configurable without code edits.
- Added `docs/scheduling.md` with cron/launchd examples linking `scripts/collect_snapshots.sh` and `scripts/run_auto_trader.sh`, making it straightforward to keep both collectors and the automation loop running during market hours. Next milestone: run the dry-run loop on live data, inspect the log outputs, then flip to paper execution once metrics look healthy.

### Update – Polygon option aggregates + VWAP-aware automation (2025‑11‑10)
- Snapshot collector now pulls Polygon minute option aggregates (CALL/PUT) alongside option chains/quotes/news. Aggregates are cached, stored in snapshot JSON, and ingested into DuckDB for backtesting. `StrategyContext` exposes `option_aggregates` everywhere.
- `MomentumIVStrategy` expands confidence scoring with option-tape momentum and VWAP trends, enriching `signal.metadata` (`option_agg_momentum`, `option_agg_vwap`) so we can audit how the tape influenced each recommendation.
- `BacktestRunner` skips low-confidence/sub‑$0.30 fills and prefers aggregate closes for exit prices, producing realistic option P&L. Tests cover collector/strategy/backtester behavior with the new data.
- AutoTrader now enforces tape-health filters before sizing trades. Config/CLI flags (`--min-option-agg-bars`, `--min-option-agg-volume`, `--min-option-agg-vwap`) plus logging ensure we only trade liquid contracts with constructive VWAP drift. The helper script and scheduling docs were updated so cron/launchd jobs pass these thresholds automatically.
- `.env.example` includes the new knobs; run snapshot + auto-trader loops with the suggested defaults (20 bars, 50 contracts of volume, ≥2% VWAP trend) for best results.
