#!/bin/bash
# Live Trading Monitor Script

echo "======================================"
echo "🔴 LIVE TRADING MONITOR"
echo "======================================"
echo ""

# Watch logs in real-time with formatting
echo "Monitoring: data/logs/auto_trader.log"
echo "Press Ctrl+C to stop"
echo ""
echo "--------------------------------------"

tail -f data/logs/auto_trader.log | while read line; do
    # Check if it's a JSON line (order log)
    if echo "$line" | grep -q '"status"'; then
        echo ""
        echo "🔔 NEW TRADING EVENT:"
        echo "$line" | python3 -m json.tool 2>/dev/null || echo "$line"
        echo "--------------------------------------"
    else
        # Regular log line
        echo "$line"
    fi
done
