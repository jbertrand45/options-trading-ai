## TradingAI Concept Overview

### 1. Product Goal
- Deliver actionable call/put entry signals and exit targets for a curated list of liquid underlyings (e.g., SPY, QQQ, AAPL).
- Generate signals with configurable holding periods (intraday vs. swing) and risk controls (max capital allocation, stop-loss, profit-taking triggers).
- Support paper trading first, with a path to broker integration for live execution once models mature.
- **Performance reality check:** Market noise, slippage, and structural uncertainty make 100% win rates unattainable. The system will instead optimize for high risk-adjusted returns, strict drawdown limits, and capital preservation while monitoring for model drift.
- Current mandate: U.S. tech focus (AAPL, MSFT, AMZN, GOOG, NVDA, META, TSLA, PLTR, OPEN, AMD, HOOD) with intraday holding periods and flexibility to go long calls or puts based on regime shifts.
- Capital baseline: $150 funded Alpaca account targeting aggressive 10% daily growth while keeping per-trade drawdowns under tight control; expectation is to minimize loss probability but remain realistic about unavoidable losing trades.

### 2. Data Strategy
- **Core provider:** Alpaca Market Data v2 (options beta) for historical and streaming options chains, implied volatility, and underlying prices. Implement rate-limit-aware caching to stay within free-tier quotas.
- **Supplemental market data:** Polygon.io for extended historical coverage, Greeks, and intraday bars; FRED macro series and VIX futures (CBOE) for regime features; curated news sentiment aggregated from Polygon reference news, Yahoo Finance RSS, Alpha Vantage, Marketaux, and NewsAPI (whichever keys are supplied).
- Secure API credentials via `.env` during development and a secrets manager in production deployments.

### 3. Execution Path
- **Phase 1:** Paper trading through Alpaca’s paper account to validate order routing and fills without risking capital.
- **Phase 2:** Live deployment behind manual confirmation (human-in-the-loop). Gradually enable auto-execution once risk metrics stay within guardrails.
- Implement a broker-agnostic `OrderManager` interface so switching providers (or adding redundancies) only requires adapter modules.
- Starting capital of ~$150 requires selective contract choice (low-premium contracts, defined-risk spreads), strict position sizing, and adherence to PDT/settlement constraints.

### 4. Technical Stack
- **Language:** Python 3.11+
- **Core libraries:** pandas, numpy, scipy, scikit-learn, statsmodels, torch/lightning (for deep models), ta (technical indicators), backtrader / vectorbt for backtesting.
- **Infrastructure:** Poetry or Hatch for dependency management, pytest for testing, pre-commit hooks for lint/format (black, isort, ruff).
- **Persistence/cache:** Local parquet/duckdb for historical storage; optional Redis for live signal caching.
- **Dashboards:** Streamlit or FastAPI + lightweight frontend for signal visualization and monitoring.

### 5. Modeling Approach
- **Feature pipeline:** Blend price/volume technicals, options chain Greeks, implied/realized volatility spreads, term-structure features, macro overlays, and news-derived sentiment/event indicators.
- **Models to evaluate:**
  - Gradient boosted trees (LightGBM, XGBoost) for fast prototyping.
  - Temporal deep nets (LSTM/Temporal CNN/Transformer) to capture sequential patterns in IV/skew.
  - Regime classifiers (HMM, clustering) to gate which strategy activates under different market states.
- **Signal logic:** Convert model outputs to probability/expected value estimates, then map to actionable trades using position sizing + risk constraints. Apply calibration (Platt scaling, isotonic) to keep probabilities well-behaved.
- Directional decisioning (call vs. put) will combine short-horizon momentum/reversal signals, volatility crush detection, and multi-source news sentiment while biasing toward contracts with favorable risk/reward given limited buying power.
- **Risk controls:** dynamic position sizing capped at 1–2 contracts (or defined-risk spreads) per trade, Kelly-fraction adjustments based on confidence, break-even stop-loss, and intraday portfolio drawdown circuit-breakers (~5% of equity).

### 6. Risk & Monitoring
- Daily VaR/expected shortfall reporting sourced from backtest distribution and live performance.
- Real-time stop-loss and take-profit checkpoints derived from underlying price, Greeks (delta/gamma), and volatility forecasts.
- Drift detection (Kolmogorov-Smirnov, Population Stability Index) on live features vs. training distributions.
- Comprehensive logging + alerting (Slack/email) for execution failures, data gaps, or anomalous performance.

### 7. Development Roadmap
1. Confirm market universe, trade cadence, capital allocation, and acceptable drawdown thresholds.
2. Set up Python project scaffold (Poetry env, linting, CI hooks). Document secrets handling.
3. Build Alpaca/Polygon/news ingestion module with local caching, schema validation, and fallback to secondary feeds.
4. Assemble exploratory notebooks to profile options chains, feature distributions, and label definitions (entry/exit, expected value).
5. Implement baseline models + backtest harness; iterate on features, calibration, and decision thresholds.
6. Add risk metrics, walk-forward validation, and scenario testing (stress, Monte Carlo, tail risk).
7. Stand up signal service (API or scheduled job) plus simple monitoring dashboard.
8. Connect to Alpaca paper trading; run shadow trades against live market for burn-in.
9. Harden deployment, add alerting, integrate with live Alpaca account once performance targets hold.

**Immediate engineering milestones**
- Expand Alpaca/Polygon/news ingestion workflow with retry logic, smarter cache invalidation, and schema normalization tuned to intraday horizons.
- Implement modular strategy framework (feature extraction, signal scoring, risk manager, execution policy) and integrate with a lightweight backtester calibrated to $150 initial capital.
- Develop simulation scenarios (Monte Carlo path resampling, stress tests) to gauge probability of hitting 10% daily targets under realistic slippage/commission assumptions.
- Stand up feature store scaffolding (DuckDB/Parquet) and baseline technical indicator generation.
- Define modular modeling interface (training, evaluation, signal scoring) with pluggable strategy experiments.

### 8. Open Questions
- Target instrument list and holding period preferences?
- Capital/risk constraints per trade and aggregate drawdown tolerance?
- Required latency (intraday signals, end-of-day rebalances, etc.)?
- Deployment environment (local workstation, cloud VM, containerized service)?

Capturing these answers will let us lock requirements and prioritize the build sequence.
