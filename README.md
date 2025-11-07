# TradingAI

Prototype workspace for an options-trading signal generator powered by Python.

## Getting Started
1. Install [Poetry](https://python-poetry.org/docs/#installation) if it is not already available.
2. Run `poetry install` to create the isolated virtual environment and install dependencies.
3. Copy `.env.example` to `.env` and populate Alpaca, Polygon, and news API credentials (`NEWS_API_KEY/SECRET`, `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_KEY` as available).
4. Review `projectdescription.md` and `docs/strategy_plan.md` for the roadmap and algorithm blueprint (default watchlist: AAPL, MSFT, AMZN, GOOG, NVDA, META, TSLA, PLTR, OPEN, AMD, HOOD).

```bash
poetry install
cp .env.example .env
poetry run python -m trading_ai check-config
poetry run python -m trading_ai collect-snapshots --output data/snapshots --lookback-minutes 60 --news-hours 3 --timeframe 1Min
poetry run pytest
```

> Tip: Use `poetry shell` for an interactive session, or prefix commands with `poetry run`.

## Architecture Snapshot
- `trading_ai.core`: orchestrates data collection via `MarketDataCollector` and `SignalPipeline`.
- `trading_ai.features`: intraday feature engineering helpers (momentum/volatility).
- `trading_ai.strategies`: pluggable signal generators (`MomentumIVStrategy` baseline).
- `trading_ai.risk`: position sizing, stop/target logic tuned for $150 accounts.
- `trading_ai.backtest`: lightweight `BacktestRunner` for rapid iteration on stored snapshots.
- `trading_ai.clients`: adapters for Alpaca/Polygon plus a `NewsAggregator` that merges Polygon, Yahoo RSS, Alpha Vantage, Marketaux, and NewsAPI feeds (whichever keys you supply).

## Next Steps
- Finalize Alpaca and Polygon API credentials (paper account first) and confirm news data feed access.
- Refine target tickers, trading cadence, and risk constraints to match strategy focus.
- Extend the new signal framework:
  - `poetry run python -m trading_ai check-config` to confirm env setup
  - `poetry run python -m trading_ai collect-snapshots --output data/snapshots --lookback-minutes 120 --news-hours 6 --timeframe 1Min` to pull market data (append `--skip-news` if you lack premium keys; for automation schedule `scripts/collect_snapshots.sh`, logs live in `data/logs/`)
  - `poetry run pytest` covers cache/risk/feature scaffolding
  - Ingest JSON snapshots into DuckDB with `poetry run python scripts/ingest_snapshot.py data/snapshots/<file>.json`
  - Run `poetry run python scripts/run_backtest.py data/snapshots/<file>.json` to execute `MomentumIVStrategy` through `BacktestRunner` (trades will appear once snapshots contain intraday bars and option pricing info)
- Iteratively tune strategies (e.g., `MomentumIVStrategy`) and `RiskManager` parameters against realistic backtests; remember daily 10% targets at near-zero risk are aspirational and should be stress-tested heavily.

## License
TBD.
