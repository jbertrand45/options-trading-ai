# TradingAI

Prototype workspace for an options-trading signal generator powered by Python.

## Getting Started
1. Install [Poetry](https://python-poetry.org/docs/#installation) if it is not already available.
2. Run `poetry install` to create the isolated virtual environment and install dependencies.
3. Copy `.env.example` to `.env` and populate Alpaca, Polygon, and news API credentials (`NEWS_API_KEY/SECRET`, `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_KEY` as available).
   - Set `ALPACA_DATA_FEED=SIP` if your account has SIP entitlements; the default `IEX` feed only returns bars during regular trading hours.
   - If you have Polygon/“Massive” intraday access, set `USE_POLYGON_BARS=1`, `POLYGON_BASE_URL=https://api.massive.com`, `POLYGON_API_OVERRIDE_IP=<known_ip_if_dns_is_flaky>`, and optionally tighten `OPTION_METRICS_LIMIT` to control how many option contracts we pull per ticker (default 300).
4. Review `projectdescription.md` and `docs/strategy_plan.md` for the roadmap and algorithm blueprint (default watchlist: AAPL, MSFT, AMZN, GOOG, NVDA, META, TSLA, PLTR, OPEN, AMD, HOOD).

```bash
poetry install
cp .env.example .env
poetry run python -m trading_ai check-config
poetry run python -m trading_ai collect-snapshots --output data/snapshots --lookback-minutes 60 --news-hours 3 --timeframe 1Min
poetry run pytest
# Run one automated signal scoring cycle (dry-run orders by default)
python3.11 -m poetry run python -m trading_ai auto-trade --lookback-minutes 120 --news-hours 3 --timeframe 1Min
```

> Tip: Use `poetry shell` for an interactive session, or prefix commands with `poetry run`.

Auto-trader defaults come from `.env` so you can tune once and reuse:

```env
AUTO_MIN_CONFIDENCE=0.55
AUTO_RISK_FRACTION=0.02
AUTO_MAX_POSITIONS=1
AUTO_ACCOUNT_EQUITY=150
AUTO_INTERVAL_SECONDS=60
AUTO_INCLUDE_NEWS=0
AUTO_USE_CACHE=0
```

## Architecture Snapshot
- `trading_ai.core`: orchestrates data collection via `MarketDataCollector` and `SignalPipeline`.
- `trading_ai.features`: intraday feature engineering helpers (momentum/volatility).
- `trading_ai.strategies`: pluggable signal generators (`MomentumIVStrategy` baseline).
- `trading_ai.risk`: position sizing, stop/target logic tuned for $150 accounts.
- `trading_ai.backtest`: lightweight `BacktestRunner` for rapid iteration on stored snapshots.
- `trading_ai.clients`: adapters for Alpaca/Polygon plus a `NewsAggregator` that merges Polygon, Yahoo RSS, Alpha Vantage, Marketaux, and NewsAPI feeds (whichever keys you supply).
- `trading_ai.service.auto_trader`: snapshot→signal automation that can run once or in a loop and log every trade intent to `data/logs/auto_trader.log`.

## Next Steps
- Finalize Alpaca and Polygon API credentials (paper account first) and confirm news data feed access.
- Refine target tickers, trading cadence, and risk constraints to match strategy focus.
- Extend the new signal framework:
  - `poetry run python -m trading_ai check-config` to confirm env setup
  - `poetry run python -m trading_ai collect-snapshots --output data/snapshots --lookback-minutes 120 --news-hours 6 --timeframe 1Min` to pull market data (append `--skip-news` if you lack premium keys; for automation schedule `scripts/collect_snapshots.sh`, logs live in `data/logs/`)
  - `poetry run pytest` covers cache/risk/feature scaffolding
  - Ingest JSON snapshots into DuckDB with `poetry run python scripts/ingest_snapshot.py data/snapshots/<file>.json`
  - Run `poetry run python scripts/run_backtest.py data/snapshots/<file>.json` to execute `MomentumIVStrategy` through `BacktestRunner` (trades will appear once snapshots contain intraday bars and option pricing info)
- Use `docs/scheduling.md` to wire `collect-snapshots` and `auto-trade --loop` so market-hours automation keeps data and signals fresh (flip `--live` only after paper trading passes review).
- Iteratively tune strategies (e.g., `MomentumIVStrategy`) and `RiskManager` parameters against realistic backtests; remember daily 10% targets at near-zero risk are aspirational and should be stress-tested heavily.

## License
TBD.
