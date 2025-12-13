#!/bin/bash
# Start Live Trading Bot

cd /Users/joeybertrand/Desktop/tradingAI

echo "🔴 Starting Live Options Auto-Trader..."

# Stop any existing instance
pkill -f "trading_ai auto-trade" 2>/dev/null
sleep 2

# Start new instance
nohup env PYTHONPATH=src python3 -m trading_ai auto-trade --live --loop --lookback-minutes 30 --news-hours 0 --timeframe 5Min --option-order-mode cash_secured > /tmp/auto_trader.log 2>&1 &

sleep 3

# Verify it started
if pgrep -f "trading_ai auto-trade" > /dev/null; then
    echo "✅ Auto-trader started successfully!"
    echo "   PID: $(pgrep -f 'trading_ai auto-trade')"
    echo ""
    echo "Monitor with: tail -f /tmp/auto_trader.log"
else
    echo "❌ Failed to start auto-trader"
    echo "Check logs: cat /tmp/auto_trader.log"
fi
