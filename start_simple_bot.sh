#!/bin/bash
# Start Simple Options Bot

cd /Users/joeybertrand/Desktop/tradingAI

echo "🚀 Starting Simple Options Auto-Trader..."

# Stop any existing bot
pkill -f "simple_options_bot.py" 2>/dev/null
sleep 2

# Start the bot in background
nohup python3 -u simple_options_bot.py > /tmp/simple_bot.log 2>&1 &

sleep 3

# Check if started
if pgrep -f "simple_options_bot.py" > /dev/null; then
    echo "✅ Bot started successfully!"
    echo "   PID: $(pgrep -f 'simple_options_bot.py')"
    echo ""
    echo "📊 Monitor with: tail -f /tmp/simple_bot.log"
    echo "🛑 Stop with: ./stop_simple_bot.sh"
else
    echo "❌ Failed to start bot"
    echo "Check logs: cat /tmp/simple_bot.log"
fi
