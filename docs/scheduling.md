## Scheduling Snapshot + Auto-Trader Jobs

### 1. Collecting Snapshots During Market Hours
Use the existing helper script to capture data every 15 minutes (example cron entry):

```cron
# Run from Monday–Friday, 9:30am‑4:00pm ET
*/15 13-20 * * 1-5 cd /Users/joeybertrand/Desktop/tradingAI && \
  LOOKBACK_MINUTES=120 NEWS_HOURS=3 TIMEFRAME=1Min \
  bash scripts/collect_snapshots.sh
```

The script logs to `data/logs/snapshot_<timestamp>.log` so you can tail the output or pipe it into your monitoring stack. Adjust the cron window to match your local timezone or use `launchd` on macOS (see below).

### 2. Running AutoTrader in a Loop
For unattended signal scoring (dry-run orders by default) invoke:

```bash
python3.11 -m poetry run python -m trading_ai auto-trade \
  --loop \
  --lookback-minutes 120 \
  --news-hours 3 \
  --timeframe 1Min
```

Environment variables in `.env` (e.g., `AUTO_MIN_CONFIDENCE`, `AUTO_RISK_FRACTION`, `AUTO_INTERVAL_SECONDS`) act as defaults, so tune them once and omit the CLI flags.

macOS launchd example (`~/Library/LaunchAgents/tradingai.autotrader.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>tradingai.autotrader</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/python3.11</string>
    <string>-m</string>
    <string>poetry</string>
    <string>run</string>
    <string>python</string>
    <string>-m</string>
    <string>trading_ai</string>
    <string>auto-trade</string>
    <string>--loop</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/joeybertrand/Desktop/tradingAI</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

Load it via `launchctl load ~/Library/LaunchAgents/tradingai.autotrader.plist`. Logs flow to `data/logs/auto_trader.log`.

### 3. Integrating Backtests
After each collection, optionally trigger a short backtest using the newest file (example shell snippet):

```bash
LATEST=$(ls -t data/snapshots/*.json | head -n 1)
python3.11 -m poetry run python scripts/run_backtest.py "$LATEST" >> data/logs/backtests.log
```

This keeps the calibration loop running so you can spot degradations before enabling live orders.
