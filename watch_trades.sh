#!/bin/bash
# Real-time trade monitoring script

echo "======================================"
echo "🔴 LIVE TRADING MONITOR"
echo "======================================"
echo "Watching: /tmp/auto_trader.log"
echo "Press Ctrl+C to stop"
echo ""

# Show current status first
echo "📊 Current Status:"
pgrep -f "trading_ai auto-trade" > /dev/null && echo "  ✅ Auto-trader: RUNNING" || echo "  ❌ Auto-trader: STOPPED"
echo ""
echo "📈 Recent Activity (last 5 events):"
tail -200 /tmp/auto_trader.log | grep -E "cycle completed|SUBMITTED|ERROR|confidence" | tail -5
echo ""
echo "--------------------------------------"
echo "🔔 Watching for new trades..."
echo "--------------------------------------"
echo ""

# Watch for important events
tail -f /tmp/auto_trader.log | while read line; do
    # Trading cycle completed
    if echo "$line" | grep -q "AutoTrader cycle completed"; then
        echo "⏱️  $(date '+%H:%M:%S') - Trading cycle completed"
    fi

    # Trade submitted
    if echo "$line" | grep -q "SUBMITTED"; then
        echo ""
        echo "🚀 TRADE EXECUTED!"
        echo "$line"
        echo ""
    fi

    # Trade error
    if echo "$line" | grep -q "ERROR.*order"; then
        echo ""
        echo "⚠️  TRADE ERROR:"
        echo "$line"
        echo ""
    fi

    # No trades met criteria
    if echo "$line" | grep -q "No trades met the criteria"; then
        echo "⏭️  $(date '+%H:%M:%S') - No opportunities found this cycle"
    fi

    # Signal analysis
    if echo "$line" | grep -q "confidence"; then
        echo "🎯 $(date '+%H:%M:%S') - Analyzing signal: $line"
    fi
done
