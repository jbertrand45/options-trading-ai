#!/bin/bash
# Stop Simple Options Bot

echo "🛑 Stopping Simple Options Bot..."

if pgrep -f "simple_options_bot.py" > /dev/null; then
    pkill -f "simple_options_bot.py"
    sleep 2

    if pgrep -f "simple_options_bot.py" > /dev/null; then
        echo "⚠️  Bot still running, force killing..."
        pkill -9 -f "simple_options_bot.py"
    fi

    echo "✅ Bot stopped"
else
    echo "ℹ️  Bot was not running"
fi
