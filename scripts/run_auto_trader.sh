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

if [[ "${AUTO_USE_SNAPSHOT_STREAM:-0}" == "1" ]]; then
  ARGS+=(--use-snapshot-stream)
fi

if [[ "${AUTO_STREAM_FORCE_REFRESH:-0}" == "1" ]]; then
  ARGS+=(--stream-force-refresh)
fi

if [[ -n "${AUTO_STREAM_INTERVAL_SECONDS:-}" ]]; then
  ARGS+=(--stream-interval "${AUTO_STREAM_INTERVAL_SECONDS}")
fi

if [[ "${AUTO_LIVE:-0}" == "1" ]]; then
  ARGS+=(--live)
fi

if [[ -n "${MIN_OPTION_AGG_BARS:-}" ]]; then
  ARGS+=(--min-option-agg-bars "${MIN_OPTION_AGG_BARS}")
fi

if [[ -n "${MIN_OPTION_AGG_VOLUME:-}" ]]; then
  ARGS+=(--min-option-agg-volume "${MIN_OPTION_AGG_VOLUME}")
fi

if [[ -n "${MIN_OPTION_AGG_VWAP:-}" ]]; then
  ARGS+=(--min-option-agg-vwap "${MIN_OPTION_AGG_VWAP}")
fi

if [[ -n "${MAX_OPTION_SPREAD_PCT:-}" ]]; then
  ARGS+=(--max-option-spread-pct "${MAX_OPTION_SPREAD_PCT}")
fi

if [[ -n "${MIN_OPTION_LIQUIDITY:-}" ]]; then
  ARGS+=(--min-option-liquidity "${MIN_OPTION_LIQUIDITY}")
fi

python3.11 -m poetry run python -m trading_ai auto-trade "${ARGS[@]}" \
  >> "${AUTO_TRADER_LOG:-data/logs/auto_trader_service.log}" 2>&1
