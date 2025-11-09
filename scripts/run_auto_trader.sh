#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

ARGS=(
  --lookback-minutes "${LOOKBACK_MINUTES:-120}"
  --news-hours "${NEWS_HOURS:-3}"
  --timeframe "${TIMEFRAME:-1Min}"
)

if [[ "${AUTO_LOOP:-0}" == "1" ]]; then
  ARGS+=(--loop)
fi

if [[ "${AUTO_INCLUDE_NEWS:-0}" == "1" ]]; then
  ARGS+=(--include-news)
fi

if [[ "${AUTO_USE_CACHE:-0}" == "1" ]]; then
  ARGS+=(--use-cache)
fi

if [[ "${AUTO_LIVE:-0}" == "1" ]]; then
  ARGS+=(--live)
fi

python3.11 -m poetry run python -m trading_ai auto-trade "${ARGS[@]}" \
  >> "${AUTO_TRADER_LOG:-data/logs/auto_trader_service.log}" 2>&1
