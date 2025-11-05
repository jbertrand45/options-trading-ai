## TradingAI Concept Overview

### 1. Product Goal
- Deliver actionable call/put entry signals and exit targets for a curated list of liquid underlyings (e.g., SPY, QQQ, AAPL).
- Generate signals with configurable holding periods (intraday vs. swing) and risk controls (max capital allocation, stop-loss, profit-taking triggers).
- Support paper trading first, with a path to broker integration for live execution once models mature.

### 2. Data Strategy
- **Core provider (recommended):** Polygon.io for historical + real-time equity and options chains, implied volatility, and Greeks. Offers coherent REST + WebSocket APIs and extensive coverage.
- **Broker-compatible alternative:** Tradier for options chain data plus native paper/live trading API. Paper account for prototyping; upgrade to live when ready.
- **Supplemental data (optional):** FRED macro series, VIX futures (CBOE) for regime features, alternative sentiment feeds if needed.
- Secure API credentials management via `.env` + secrets manager for production deployments.

### 3. Execution Path
- **Phase 1:** Paper trading through Tradier (dummy account) or a simulated broker abstraction. Validate fills against historical data.
- **Phase 2:** Live deployment behind manual confirmation (human-in-the-loop). Gradually enable auto-execution once risk metrics stay within guardrails.
- Implement broker-agnostic OrderManager interface so switching providers only requires adapter modules.

### 4. Technical Stack
- **Language:** Python 3.11+
- **Core libraries:** pandas, numpy, scipy, scikit-learn, statsmodels, torch/lightning (for deep models), ta (technical indicators), backtrader / vectorbt for backtesting.
- **Infrastructure:** Poetry or Hatch for dependency management, pytest for testing, pre-commit hooks for lint/format (black, isort, ruff).
- **Persistence/cache:** Local parquet/duckdb for historical storage; optional Redis for live signal caching.
- **Dashboards:** Streamlit or FastAPI + React for signal visualization and monitoring.

### 5. Modeling Approach
- **Feature pipeline:** Blend price/volume technicals, options chain Greeks, implied/realized vol spreads, term-structure features, macro overlays.
- **Models to evaluate:**
  - Gradient boosted trees (LightGBM, XGBoost) for fast prototyping.
  - Recurrent/temporal CNN models for sequential patterns in IV/skew.
  - Regime classifiers (HMM, clustering) to gate which strategy activates.
- **Signal logic:** Convert model outputs to probability/expected value estimates, then map to actionable trades using position sizing + risk constraints.
- Integrate Bayesian calibration or Platt scaling to maintain well-behaved probabilities for decision thresholds.

### 6. Risk & Monitoring
- Daily VaR/expected shortfall reporting from backtest distribution.
- Real-time stop-loss and take-profit checkpoints derived from underlying price + option delta/gamma.
- Drift detection (Kolmogorov-Smirnov or PSI) on live features vs. training distributions.
- Comprehensive logging + alerting (Slack/email) for execution failures or anomalous performance.

### 7. Development Roadmap
1. Confirm market universe, trade cadence, and initial budget constraints.
2. Set up Python project scaffold (Poetry env, linting, CI hooks). Document secrets handling.
3. Build data ingestion adapters (Polygon/Tradier) with local caching and schema validation.
4. Assemble exploratory notebooks to profile options chains and target labels (entry/exit).
5. Implement baseline models + backtest harness; iterate on features and thresholds.
6. Add risk metrics, walk-forward validation, and scenario testing.
7. Stand up signal service (API or job) plus simple monitoring dashboard.
8. Connect to paper trading broker; run shadow trades against live market for burn-in.
9. Harden deployment, add alerting, and prep for live capital.

### 8. Open Questions
- Preferred provider combo (Polygon + Tradier, or alternatives)?
- Exact instrument list and holding period targets?
- Capital/risk constraints per trade and aggregate drawdown tolerance?
- Deployment environment (local workstation, cloud VM, containerized service)?

Capturing these answers will let us lock requirements and prioritize the build sequence.
