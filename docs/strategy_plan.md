## Strategy Blueprint: $150 Intraday Options Account

### Objectives
- Target: 10% daily return objective while capping daily drawdown to ≤5%.
- Capital: $150 starting equity (Alpaca paper/live), limited to 1–2 contracts per trade or defined-risk spreads.
- Products: Liquid tech options (AAPL, MSFT, AMZN, GOOG, NVDA, META, TSLA, PLTR, OPEN, AMD, HOOD).
- Direction: Long calls or puts depending on regime; no short naked options to avoid unlimited risk.

### Data Inputs
| Source  | Purpose | Notes |
|---------|---------|-------|
| Alpaca  | Execution, option chains, latest quotes | Live/paper trading and baseline data. |
| Polygon/Massive | Historical chains, Greeks, intraday bars, open interest | Options Developer tier now wired in; cache aggressively and leverage new greeks/OI payload. |
| Polygon News + Yahoo RSS + Alpha Vantage + Marketaux + NewsAPI | Intraday catalysts & sentiment ensemble | Aggregated to boost coverage and reduce dependency on any single feed (resolve DNS/auth for Massive/NewsAPI before enabling). |

### Signal Stack
1. **Feature extraction** (`trading_ai.features`):
   - Intraday momentum (15/60 minute),
   - Realized volatility estimate,
   - Placeholder for future Greeks/skew features.
2. **Strategy layer** (`strategies.momentum_iv.MomentumIVStrategy`):
   - Combines price momentum, IV change, and news sentiment.
   - Emits `TradingSignal` with direction/confidence metadata.
   - Modular so additional strategies can plug in.
3. **Risk controls** (`risk.manager.RiskManager`):
   - Dynamic position sizing based on equity, confidence, and per-trade risk fraction (~2% default).
   - Daily loss cap (5%) and stop/target scaffolding.
4. **Backtesting harness** (`backtest.engine.BacktestRunner`):
   - Simulates trades over stored `StrategyContext` snapshots.
   - Tracks equity curve, trades, drawdown, and return statistics.

### Development Roadmap
1. **Data readiness**
   - Finish robust Alpaca/Polygon connectors with retry, rate-limit awareness, and DuckDB/Parquet storage (if quotas allow).
   - Expand `compute_intraday_features` to include Greeks skew, VWAP deviations, and volume imbalance.
2. **Model iterations**
   - Prototype `MomentumIVStrategy` on cached data; calibrate thresholds to achieve win-rate >=60% and avg R:R ≥1.5.
   - Layer additional strategies (e.g., news shock, gap fade) and aggregate signals using ensemble weights calibrated via cross-validation.
3. **Risk & execution**
   - Tighten `RiskManager` sizing for fractional contracts (or micro options when available).
   - Implement execution adapter that transforms `TradingSignal` + risk output into Alpaca orders with stop/target OCO brackets.
   - Add intraday monitoring + circuit breaker triggered by cumulative loss >5% or low confidence regime detection.
4. **Evaluation**
   - Run walk-forward backtests covering various regimes (bullish/bearish/high-vol).
   - Stress test via Monte Carlo resampling: confirm probability of daily loss <20% while keeping upside high.
   - Track metrics: daily return distribution, Sharpe, Sortino, max drawdown, percent of sessions hitting target.

### Reality Check
Achieving a consistent 10% daily return with near-zero risk is extremely ambitious—expect drawdowns and losing trades. The framework above enforces discipline (position sizing, stops, daily loss cap) while chasing upside through selective, high-confidence setups. Continuous monitoring, data validation, and conservative execution safeguards are critical before moving any strategy to live capital.
