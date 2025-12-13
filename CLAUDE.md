# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

TradingAI is an options-trading signal generator powered by Python, targeting intraday call/put signals for liquid U.S. tech stocks (AAPL, MSFT, AMZN, GOOG, NVDA, META, TSLA, PLTR, OPEN, AMD, HOOD). The system operates on a $150 funded Alpaca account with strict capital controls, blending momentum indicators, implied volatility metrics, option Greeks, and multi-source news sentiment. All data flows through Alpaca Market Data v2 (with optional news aggregators).

**Capital constraints:** Small account size (~$150) requires selective contract choice, defined-risk strategies (cash-secured puts, covered calls), and strict position sizing limits (1–2 contracts max per trade). The system defaults to paper trading and dry-run mode until risk metrics hold.

## Development Commands

### Environment Setup
```bash
# Install Poetry dependencies
poetry install

# Activate virtual environment
poetry shell

# Check configuration
poetry run python -m trading_ai check-config
```

### Testing & Code Quality
```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_collector.py

# Run single test
poetry run pytest tests/test_collector.py::test_collect_market_snapshot -v

# Formatting & Linting
poetry run black src tests          # Format code
poetry run isort src tests           # Sort imports
poetry run ruff check src tests      # Lint
poetry run mypy src                  # Type checking
```

### Data Collection
```bash
# Collect a snapshot (use --skip-news if you lack news keys)
poetry run python -m trading_ai collect-snapshots \
  --output data/snapshots \
  --lookback-minutes 120 \
  --news-hours 3 \
  --timeframe 1Min

# Ingest snapshot into DuckDB
poetry run python scripts/ingest_snapshot.py data/snapshots/<file>.json

# Run backtest on a snapshot
poetry run python scripts/run_backtest.py data/snapshots/<file>.json
```

### AutoTrader (Signal Scoring + Order Execution)
```bash
# Dry-run cycle (logs to data/logs/auto_trader.log)
poetry run python -m trading_ai auto-trade \
  --lookback-minutes 120 \
  --news-hours 3 \
  --timeframe 1Min

# Continuous loop (dry-run)
poetry run python -m trading_ai auto-trade --loop

# Live orders (WARNING: real capital at risk)
poetry run python -m trading_ai auto-trade --live
```

**Key flags:**
- `--min-option-agg-bars N` – require N Alpaca option bars before trading
- `--min-option-agg-volume V` – minimum cumulative volume across option bars
- `--min-option-agg-vwap W` – minimum absolute VWAP trend (e.g., 0.02 = 2%)
- `--max-option-spread-pct S` – skip trades when bid/ask spread exceeds S fraction
- `--min-option-liquidity L` – minimum option volume for capital allocation
- `--use-snapshot-stream` – maintain rolling snapshot between cycles
- `--use-live-stream` – enable Alpaca live bar enrichment
- `--option-order-mode {long|cash_secured|auto}` – order style (short puts require collateral)

Most parameters have `.env` defaults (see `AUTO_*` variables in `.env.example`).

## Architecture

### Data Layer (`trading_ai.core`, `trading_ai.clients`)
- **MarketDataCollector** (`core/collector.py`): Orchestrates incremental data pulls from Alpaca and news feeds with local JSON/parquet caching. Collects:
  - Underlying bars (`collect_underlying_bars`) – equity intraday bars via Alpaca
  - Option chain/metrics (`collect_option_chain`, `collect_option_metrics`) – normalized Alpaca chain entries
  - Option quotes (`collect_option_quote`) – representative call/put contracts near spot
  - Option aggregates (`collect_option_aggregates`) – Alpaca option bars (enabled via `ENABLE_OPTION_AGGREGATES=1`)
  - News (`collect_news`) – Yahoo RSS + Alpha Vantage, Marketaux, NewsAPI (whichever keys are supplied)

- **AlpacaClient** (`clients/alpaca_client.py`): Handles Alpaca trading/data APIs with TLS/DNS overrides for corporate proxies (`ALPACA_CA_BUNDLE`, `ALPACA_VERIFY_TLS`, `ALPACA_DATA_OVERRIDE_IP`). Supports OAuth tokens via `ALPACA_OAUTH_TOKEN`.

- **AlpacaStream** (`clients/alpaca_stream.py`): Live bar streaming from Alpaca to enrich snapshots between cycles when `AUTO_USE_LIVE_STREAM=1`.

- **NewsAggregator** (`clients/news_aggregator.py`): Merges Yahoo Finance RSS, Alpha Vantage, Marketaux, and NewsAPI feeds into a unified story list.

- **LocalDataCache** (`data/cache.py`): File-based cache keyed by provider, data type, ticker, and time bucket. Supports JSON and DataFrame serialization.

- **DuckDBStore** (`data/duckdb_store.py`): Persistent storage for snapshots; scripts/ingest_snapshot.py ingests JSON artifacts.

### Signal Pipeline (`trading_ai.core.pipeline`, `trading_ai.strategies`)
- **SignalPipeline** (`core/pipeline.py`): Thin facade over `MarketDataCollector` that wraps `collect_market_snapshot()` with strategy-agnostic feature computation (technicals module).

- **MomentumIVStrategy** (`strategies/momentum_iv.py`): Baseline strategy blending:
  - Intraday momentum (bars, features, option quotes, option aggregates)
  - IV crush detection (average IV, IV change from chain/metrics)
  - News sentiment (keyword matching)
  - Option flow (open interest, delta/theta/vega-weighted aggregates)
  - VWAP trends from option bars
  - Greek filters (vega bias, theta health)

  **Signal generation** (`generate_signal(context)`):
  1. Compute momentum from underlying bars, fallback to features or option quote skew
  2. Extract IV metrics from chain/metrics
  3. Aggregate option flow (call vs. put open interest, weighted delta/theta/vega)
  4. Determine direction (CALL/PUT/NONE) based on momentum + IV + flow thresholds
  5. Apply Greek filters (min vega bias, max theta magnitude)
  6. Score confidence using weighted blend of momentum, IV, news, flow, aggregates, Greeks
  7. Return `TradingSignal(ticker, direction, confidence, entry_price, target_price, metadata)`

- **StrategyContext** (`strategies/base.py`): Data container passed to strategies:
  - `underlying_bars` (DataFrame)
  - `option_chain`, `option_metrics`, `option_quote` (dicts)
  - `option_aggregates` (dict of bar series)
  - `news_items` (list)
  - `features` (dict, optional)

### Risk Management (`trading_ai.risk.manager`)
- **RiskManager** (`risk/manager.py`): Position sizing under strict capital constraints.
  - `size_position(params)` → int: Compute contract quantity using:
    - Risk capital = `account_equity * min(trade_risk_fraction, max_daily_loss_pct)`
    - Confidence scalar (sqrt dampening)
    - Spread penalty (0 if spread/price > `max_spread_pct`)
    - Liquidity penalty (0 if volume < `min_liquidity`)
    - Cap at `max_positions` (usually 1–2 contracts)
  - `stop_loss_price(entry, risk_fraction)` → float
  - `take_profit_price(entry, reward_multiplier, risk_fraction)` → float

### Backtesting (`trading_ai.backtest`)
- **BacktestRunner** (`backtest/engine.py`): Lightweight engine for rapid iteration on stored snapshots.
- **contexts_from_snapshot** (`backtest/data_loader.py`): Deserializes JSON snapshots into `StrategyContext` objects for backtesting.

Scripts: `scripts/run_backtest.py` executes `MomentumIVStrategy` on a snapshot file.

### AutoTrader Service (`trading_ai.service.auto_trader`)
- **AutoTrader** (`service/auto_trader.py`): Coordinates snapshot collection, signal scoring, and order placement.
  - `run_once()` → List[TradeIntent]: Single cycle
  - `run_loop()`: Continuous execution until interrupted
  - **Flow:**
    1. Refresh account equity (`_update_account_equity()`)
    2. Check exit conditions for open positions (`_maybe_close_positions()`)
    3. Fetch snapshot (via `SnapshotStream` if enabled, else fresh `collect_market_snapshot()`)
    4. Merge live bars if `AlpacaStream` is active (`_merge_live_bars()`)
    5. Build `StrategyContext` from snapshot
    6. Generate signal via strategy
    7. Size position via `RiskManager`
    8. For cash-secured puts: fallback to affordable strikes within collateral (`_maybe_select_affordable_put()`)
    9. Submit order (dry-run or live) and log intent to `data/logs/auto_trader.log`

- **TradeIntent**: Captures ticker, option_symbol, direction, quantity, entry_price, stop/target prices, confidence, metadata.

- **SnapshotStream** (`service/snapshot_stream.py`): Background thread that periodically refreshes snapshots (`AUTO_STREAM_INTERVAL_SECONDS`) so `AutoTrader` doesn't block on collection every cycle. Enable with `AUTO_USE_SNAPSHOT_STREAM=1`.

### Configuration (`trading_ai.settings`)
- **Settings** (Pydantic): Loads from `.env` with typed fields:
  - Alpaca credentials (`ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_OAUTH_TOKEN`)
  - Account mode (`ALPACA_PAPER_ACCOUNT` → paper vs. live API host)
  - Data feed (`ALPACA_DATA_FEED=SIP|IEX`)
  - News keys (NewsAPI, Alpha Vantage, Marketaux)
  - Target tickers (comma-separated or list)
  - AutoTrader defaults (`AUTO_MIN_CONFIDENCE`, `AUTO_RISK_FRACTION`, `AUTO_MAX_POSITIONS`, etc.)
  - Option aggregate gates (`MIN_OPTION_AGG_BARS`, `MIN_OPTION_AGG_VOLUME`, `MIN_OPTION_AGG_VWAP`)
  - Spread/liquidity filters (`MAX_OPTION_SPREAD_PCT`, `MIN_OPTION_LIQUIDITY`)

Use `get_settings()` to retrieve the cached singleton.

### CLI (`trading_ai.cli`)
- **Commands:**
  - `check-config`: Print active configuration
  - `collect-snapshots`: Collect and persist market snapshots to JSON
  - `auto-trade`: Score signals and submit orders (once or loop)

Entry point: `python -m trading_ai <command> [args]`

## Key Data Flows

### Snapshot Collection
1. `MarketDataCollector.collect_market_snapshot(lookback, news_lookback, timeframe)`
2. For each ticker:
   - Fetch underlying bars (Alpaca) → cache as parquet
   - Fetch option chain → cache as JSON
   - Normalize chain into option metrics (limit to `OPTION_METRICS_LIMIT` entries)
   - Select representative call/put quotes near spot
   - Fetch option bars for selected contracts (if `ENABLE_OPTION_AGGREGATES=1`)
   - Gather news from aggregators
3. Return dict: `{ticker: {underlying_bars, option_chain, option_metrics, option_quote, option_aggregates, news}}`
4. Serialize to `data/snapshots/snapshots_<timestamp>.json`

### Signal Scoring → Order Placement
1. `AutoTrader.run_once()` fetches snapshot (fresh or from `SnapshotStream`)
2. `contexts_from_snapshot(snapshot)` → `List[StrategyContext]`
3. For each context:
   - `strategy.generate_signal(context)` → `TradingSignal`
   - `RiskManager.size_position(...)` → contract quantity
   - `_build_intent(context)` → `TradeIntent` (with stop/target prices)
   - `_execute_intent(intent)` → submit to Alpaca (or dry-run log)
   - `_record_intent(intent, result)` → append JSON line to `data/logs/auto_trader.log`

### Alpaca TLS/DNS Workarounds
Corporate proxies with custom CAs or flaky DNS can block Alpaca data fetches:
- `ALPACA_CA_BUNDLE=/path/to/cacert.pem` → inject custom CA bundle
- `ALPACA_VERIFY_TLS=0` → disable SSL verification (debug only, unsafe for production)
- `ALPACA_DATA_OVERRIDE_IP=<ip>` → pin `data.alpaca.markets` to a known IP

See `trading_ai.utils.dns` for IP override logic.

## Important Constraints & Patterns

### Capital Limits
- **$150 account** → max 1–2 contracts per trade, cash-secured puts require strike ≤ $150, covered calls require owning 100 shares.
- **Cash-secured put collateral:** `strike * 100` per contract must fit within `account_equity`.
- **Covered call shares:** Need 100 shares per contract; checked via `_get_underlying_shares(ticker)`.
- AutoTrader falls back to "long" mode if coverage check fails (`_coverage_limit()`).

### Option Symbol Format
- **OCC-style:** `AAPL250117C00150000` → AAPL, exp=2025-01-17, C=CALL, strike=150.00
- Parsing: `_parse_option_symbol(symbol)` → (expiration, option_type, strike)
- Construction: `_occ_symbol(ticker, expiration, contract_type, strike)` → OCC string

### Alpaca Tradability
Before submitting orders, always check `alpaca_client.option_is_tradable(symbol)`. AutoTrader includes fallback logic to pick the first tradable contract from the chain if the selected one is blocked.

### Exit Monitoring
When `ENABLE_EXIT_MONITOR=1`, AutoTrader scans open positions and closes them if:
- Long position: `mid >= take_profit_price` OR `mid <= stop_price`
- Short position: `mid <= take_profit_price` OR `mid >= stop_price`

Stop/target levels are recovered from `data/logs/auto_trader.log` (last `EXIT_LOG_SCAN_LINES` entries).

### Snapshot Streaming
Enable `AUTO_USE_SNAPSHOT_STREAM=1` to avoid blocking on collection every cycle:
- `SnapshotStream` runs a background thread that refreshes snapshots every `AUTO_STREAM_INTERVAL_SECONDS`.
- `AutoTrader` calls `snapshot_stream.latest_snapshot()` for instant access.
- Force refresh: `AUTO_STREAM_FORCE_REFRESH=1` → always collect fresh snapshot each cycle.

Combine with `AUTO_USE_LIVE_STREAM=1` to merge Alpaca live bars into snapshots between refreshes.

## Scheduling & Automation

See `docs/scheduling.md` for cron/launchd examples. Common setup:
- **Snapshot collection:** `scripts/collect_snapshots.sh` every 15 minutes during market hours
- **AutoTrader loop:** `poetry run python -m trading_ai auto-trade --loop` in a launchd/systemd service
- **Logs:** `data/logs/snapshot_*.log`, `data/logs/auto_trader.log`

## Environment Variables Reference

Critical `.env` settings:
- `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` or `ALPACA_OAUTH_TOKEN`
- `ALPACA_PAPER_ACCOUNT` (0=live, 1=paper)
- `ALPACA_DATA_FEED` (IEX=regular hours only, SIP=extended hours)
- `ENABLE_OPTION_AGGREGATES` (0=skip option bars, 1=fetch)
- `ENABLE_UNDERLYING_BARS` (0=option-only tape, 1=fetch equity bars)
- `AUTO_MIN_CONFIDENCE`, `AUTO_RISK_FRACTION`, `AUTO_MAX_POSITIONS`, `AUTO_ACCOUNT_EQUITY`
- `MIN_OPTION_AGG_BARS`, `MIN_OPTION_AGG_VOLUME`, `MIN_OPTION_AGG_VWAP`
- `MAX_OPTION_SPREAD_PCT`, `MIN_OPTION_LIQUIDITY`
- `AUTO_STOP_LOSS_FRACTION`, `AUTO_TAKE_PROFIT_REWARD`

## Testing Strategy

- **Unit tests** cover cache, feature engineering, risk sizing, strategy signal generation.
- **Integration tests** mock Alpaca API responses to validate collector/pipeline flows.
- **Backtest validation:** After collecting snapshots, run `scripts/run_backtest.py` to verify strategy logic against real market data.
- Test files: `tests/test_*.py`; use `pytest -v` for verbose output.

## Code Style

- **Formatter:** black (line length 100)
- **Import sorter:** isort (black-compatible)
- **Linter:** ruff (Python 3.11+, strict rules)
- **Type hints:** mypy (strict optional, exclude tests/)
- Line endings: LF (Unix)
- Avoid pytest S101 suppression; tests are exempt from security linter rules.

## Common Pitfalls

1. **IEX feed limitations:** Default `ALPACA_DATA_FEED=IEX` only returns bars during regular trading hours (9:30am–4pm ET). Switch to `ALPACA_DATA_FEED=SIP` if your account has entitlements.
2. **DNS flakiness:** If `data.alpaca.markets` resolution fails, pin the IP via `ALPACA_DATA_OVERRIDE_IP`.
3. **Custom CA bundles:** Corporate proxies may block TLS; point `ALPACA_CA_BUNDLE` to your cert bundle.
4. **Insufficient collateral:** Cash-secured puts require `strike * 100 ≤ account_equity`. AutoTrader will fallback to the highest affordable strike or skip the trade.
5. **Non-tradable options:** Always check `option_is_tradable(symbol)` before submitting orders. Alpaca may block certain contracts.
6. **Empty aggregates:** If `ENABLE_OPTION_AGGREGATES=0` or Alpaca option bars are unavailable, strategies fall back to chain/quote data. Ensure `MIN_OPTION_AGG_BARS=0` if you want to trade without aggregates.
7. **Stale snapshots:** When using `SnapshotStream`, verify `AUTO_STREAM_INTERVAL_SECONDS` is appropriate for your trading cadence. Too long → stale data; too short → API rate limits.

## Project Status (2025-11-12)

- **Data path:** Alpaca-only (Polygon/Massive removed)
- **Option metrics:** Normalized from Alpaca option chains (limit: `OPTION_METRICS_LIMIT=300`)
- **AutoTrader:** Dry-run and paper/live modes operational; intents logged to `data/logs/auto_trader.log`
- **Live bar streaming:** `AlpacaStream` + `AUTO_USE_LIVE_STREAM=1` enriches snapshots between cycles
- **Next steps:** Collect market-hours snapshots, tune thresholds, review dry-run logs before enabling live orders

## Additional Documentation

- **Strategy blueprint:** `docs/strategy_plan.md`
- **Scheduling examples:** `docs/scheduling.md`
- **Project description:** `projectdescription.md`, `projectstatus.md`
- **README:** `README.md` (quickstart, architecture overview)
