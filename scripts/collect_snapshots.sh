#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
poetry run python -m trading_ai collect-snapshots \
  --output "data/snapshots" \
  --lookback-minutes "${LOOKBACK_MINUTES:-120}" \
  --news-hours "${NEWS_HOURS:-6}" \
  --timeframe "${TIMEFRAME:-1Min}" \
  ${SKIP_NEWS:+--skip-news} \
  ${NO_CACHE:+--no-cache} \
  > "data/logs/snapshot_${TIMESTAMP}.log" 2>&1
