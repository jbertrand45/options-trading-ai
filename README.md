# TradingAI

Prototype workspace for an options-trading signal generator powered by Python.

## Getting Started
1. Install [Poetry](https://python-poetry.org/docs/#installation) if it is not already available.
2. Run `poetry install` to create the isolated virtual environment and install dependencies.
3. Copy `.env.example` to `.env` and populate Alpaca credentials plus any news API keys you have (`NEWS_API_KEY/SECRET`, `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_KEY` as available). If you are using Alpaca OAuth, set `ALPACA_OAUTH_TOKEN` to the bearer token returned from `https://authx.alpaca.markets/v1/oauth2/token`.
   - **IMPORTANT:** Defaults use paper trading (`ALPACA_PAPER_ACCOUNT=1` → Trading API host `https://paper-api.alpaca.markets/v2`). For live trading with real money, set `ALPACA_PAPER_ACCOUNT=0` to route orders to `https://api.alpaca.markets/v2`. **Always test with paper trading first!**
   - Set `ALPACA_DATA_FEED=SIP` if your account has SIP entitlements; the default `IEX` feed only returns bars during regular trading hours. If DNS to `data.alpaca.markets` is flaky on this host, set `ALPACA_DATA_OVERRIDE_IP=<known_ip>` to pin the resolver. Corporate proxies with custom CAs can be handled by pointing `ALPACA_CA_BUNDLE=/path/to/cacert.pem` or, as a last resort for debugging only, disabling verification via `ALPACA_VERIFY_TLS=0`.
   - Flip `ENABLE_OPTION_AGGREGATES=1` if you want Alpaca option bars captured alongside option chains (off by default to minimize API usage). `OPTION_METRICS_LIMIT` controls how many option contracts we normalize per ticker when building metrics (default 300).
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
AUTO_USE_SNAPSHOT_STREAM=1
AUTO_USE_LIVE_STREAM=0
AUTO_STREAM_INTERVAL_SECONDS=60
AUTO_STREAM_FORCE_REFRESH=0
AUTO_STOP_LOSS_FRACTION=0.03
AUTO_TAKE_PROFIT_REWARD=2.5
MIN_OPTION_AGG_BARS=20
MIN_OPTION_AGG_VOLUME=50
MIN_OPTION_AGG_VWAP=0.02
MAX_OPTION_SPREAD_PCT=0.25
MIN_OPTION_LIQUIDITY=50
MIN_OPTION_LIQUIDITY=25
ENABLE_OPTION_AGGREGATES=1
ENABLE_UNDERLYING_BARS=1
ALPACA_CA_BUNDLE=
ALPACA_VERIFY_TLS=1
```

These `MIN_OPTION_AGG_*` thresholds act as your default tape-health gate for AutoTrader; tweak them once in `.env` and every `auto-trade` invocation will inherit the filters unless you override them with CLI flags.

Set `ENABLE_UNDERLYING_BARS=0` if you want to run purely on option data without requesting Alpaca equity bars—useful when your data plan is delayed or you only want option-tape signals.

Use `MAX_OPTION_SPREAD_PCT` and `MIN_OPTION_LIQUIDITY` to define the default spread/liquidity gates for the risk manager; trades are skipped whenever the bid/ask is too wide or the recent option tape is too thin. Defaults are tightened for live trading (0.25 spread cap, 50 contracts liquidity floor).
AutoTrader also enforces a 3% stop-loss by default with a 2.5R take-profit target; adjust in code or via CLI flags if needed.

## Enabling Live Trading

**By default, AutoTrader runs in dry-run mode** (logs trade intents without submitting orders). To enable actual order submission:

### Step 1: Test with Paper Trading (REQUIRED)
```bash
# Ensure .env has ALPACA_PAPER_ACCOUNT=1
poetry run python -m trading_ai auto-trade --live --lookback-minutes 120 --news-hours 3 --timeframe 1Min
```

### Step 2: Verify Your Alpaca Account
- Ensure your Alpaca account is approved for **options trading** (check account settings)
- Verify you have sufficient **options buying power** (minimum $150 recommended)
- Confirm API keys have **trading permissions** (not just market data access)

### Step 3: Enable Live Trading (Use with Caution)
```bash
# Set ALPACA_PAPER_ACCOUNT=0 in .env for live trading
# Then run with --live flag
poetry run python -m trading_ai auto-trade --live --lookback-minutes 120 --news-hours 3 --timeframe 1Min
```

**⚠️ WARNING:** Live trading mode executes real orders with real money. Always:
- Test thoroughly with paper trading first
- Start with small position sizes (`AUTO_MAX_POSITIONS=1`)
- Monitor `data/logs/auto_trader.log` for errors
- Verify spread/liquidity filters are appropriate (`MAX_OPTION_SPREAD_PCT=0.25`, `MIN_OPTION_LIQUIDITY=50`)

## Architecture Snapshot
- `trading_ai.core`: orchestrates data collection via `MarketDataCollector` and `SignalPipeline`.
- `trading_ai.features`: intraday feature engineering helpers (momentum/volatility).
- `trading_ai.strategies`: pluggable signal generators (`MomentumIVStrategy` baseline).
- `trading_ai.risk`: position sizing, stop/target logic tuned for $150 accounts.
- `trading_ai.backtest`: lightweight `BacktestRunner` for rapid iteration on stored snapshots.
- `trading_ai.clients`: adapters for Alpaca plus a `NewsAggregator` that merges Yahoo RSS, Alpha Vantage, Marketaux, and NewsAPI feeds (whichever keys you supply). Live Alpaca bar streaming is exposed via `AlpacaStream`.
- `trading_ai.service.auto_trader`: snapshot→signal automation that can run once or in a loop and log every trade intent to `data/logs/auto_trader.log`. Enable live bar enrichment with `AUTO_USE_LIVE_STREAM=1` alongside `AUTO_USE_SNAPSHOT_STREAM=1` to keep snapshots fresh between cycles.

## Next Steps
- Finalize Alpaca API credentials (paper account first) and confirm news data feed access.
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
