#!/usr/bin/env python3
"""
Simple Stock Day Trading Bot
Strategy: Buy stocks on momentum, sell on profit/loss targets
"""
import os
import time
import datetime
import json
import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Configuration
API_KEY = os.getenv("ALPACA_API_KEY_ID", "AK3FLIZ5DLA5GVPEXRM75QTYHT")
API_SECRET = os.getenv("ALPACA_API_SECRET_KEY", "2DqpuY1Yw1v92izySSqfC1YjhazPm6ffio7QrLHow7h9")

# Stock Selection - Mix of volatile and liquid stocks
TICKERS = ["F", "NIO", "PLUG", "SOFI", "AMD", "NVDA", "TSLA", "PLTR", "RIVN"]
MAX_POSITION_SIZE = 600.0  # Max $600 per position (can buy TSLA)
MIN_POSITION_SIZE = 50.0   # Min $50 per position
MAX_POSITIONS = 3
MAX_DAILY_TRADES = 5
CYCLE_INTERVAL = 60  # Seconds

# Risk Management
PROFIT_TARGET = 0.03  # Sell at 3% profit
STOP_LOSS = 0.02      # Sell at 2% loss
POSITION_TRACKING_FILE = "/tmp/stock_positions.json"

# Market Hours
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 45  # Close positions before 4pm

# Initialize clients
trading_client = TradingClient(API_KEY, API_SECRET, paper=False)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)


def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def is_market_hours():
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.datetime.now(et_tz)
    if now_et.weekday() >= 5:
        return False
    current_time = now_et.time()
    market_open = datetime.time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = datetime.time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    return market_open <= current_time <= market_close


def load_positions():
    try:
        if os.path.exists(POSITION_TRACKING_FILE):
            with open(POSITION_TRACKING_FILE, 'r') as f:
                return json.load(f)
        return {}
    except:
        return {}


def save_positions(positions):
    try:
        with open(POSITION_TRACKING_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
    except Exception as e:
        log(f"Error saving positions: {e}")


def get_daily_trades():
    positions = load_positions()
    today = datetime.date.today().strftime("%Y-%m-%d")
    if "trade_stats" not in positions:
        positions["trade_stats"] = {"date": today, "count": 0}
        save_positions(positions)
    if positions["trade_stats"]["date"] != today:
        positions["trade_stats"] = {"date": today, "count": 0}
        save_positions(positions)
    return positions["trade_stats"]["count"]


def increment_daily_trades():
    positions = load_positions()
    if "trade_stats" not in positions:
        positions["trade_stats"] = {"date": datetime.date.today().strftime("%Y-%m-%d"), "count": 0}
    positions["trade_stats"]["count"] += 1
    save_positions(positions)


def can_trade_today():
    return get_daily_trades() < MAX_DAILY_TRADES


def get_stock_price(ticker):
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=[ticker])
        quotes = data_client.get_stock_latest_quote(req)
        quote = quotes[ticker]
        return float(quote.ask_price) if quote.ask_price else float(quote.bid_price)
    except Exception as e:
        log(f"  Error getting price for {ticker}: {e}")
        return None


def check_momentum(ticker):
    """ULTRA AGGRESSIVE: Buy on ANY upward movement"""
    try:
        end = datetime.datetime.now(pytz.UTC)
        start = end - datetime.timedelta(minutes=2)  # Just last 2 minutes

        req = StockBarsRequest(
            symbol_or_symbols=[ticker],
            timeframe=TimeFrame.Minute,
            start=start,
            end=end
        )

        bars = data_client.get_stock_bars(req)
        if ticker not in bars:
            return False

        bars_list = list(bars[ticker])
        if len(bars_list) < 2:
            return False

        # Just check if price went up AT ALL
        recent_close = float(bars_list[-1].close)
        older_close = float(bars_list[0].close)
        change_pct = (recent_close - older_close) / older_close

        log(f"    Change: {change_pct*100:+.3f}%")

        # Buy if price went up AT ALL (even 0.001%)
        return change_pct > 0

    except Exception as e:
        log(f"  Error checking momentum for {ticker}: {e}")
        return False


def buy_stock(ticker, price):
    """Buy stock with market order"""
    try:
        # Calculate quantity
        position_size = MAX_POSITION_SIZE  # Use full max position size
        qty = int(position_size / price)

        if qty < 1:
            log(f"  ⏭️  {ticker} too expensive: ${price:.2f}")
            return False

        cost = qty * price

        log(f"💰 BUYING: {ticker}")
        log(f"   Price: ${price:.2f}")
        log(f"   Qty: {qty} shares")
        log(f"   Cost: ${cost:.2f}")

        order_req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)
        log(f"✅ BUY ORDER SUBMITTED!")
        log(f"   Order ID: {order.id}")

        # Track position
        positions = load_positions()
        positions[ticker] = {
            "entry_price": price,
            "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "qty": qty
        }
        save_positions(positions)

        increment_daily_trades()
        return True

    except Exception as e:
        log(f"❌ Error buying {ticker}: {e}")
        return False


def monitor_positions():
    """Monitor positions and sell for profit/loss"""
    try:
        positions = trading_client.get_all_positions()
    except Exception as e:
        log(f"⚠️  Network error monitoring positions, will retry: {e}")
        return

    if not positions:
        return

    log(f"👁️  Monitoring {len(positions)} position(s)...")
    tracked = load_positions()

    for pos in positions:
        ticker = pos.symbol
        if ticker not in tracked:
            continue

        entry_price = tracked[ticker]["entry_price"]
        current_price = float(pos.current_price)
        pnl_pct = ((current_price - entry_price) / entry_price)
        pnl_dollars = float(pos.unrealized_pl)

        log(f"  {ticker}:")
        log(f"    Entry: ${entry_price:.2f} | Current: ${current_price:.2f}")
        log(f"    P&L: {pnl_pct*100:+.1f}% (${pnl_dollars:+.2f})")

        # TAKE PROFIT
        if pnl_pct >= PROFIT_TARGET:
            log(f"  💰 PROFIT TARGET HIT! Selling...")
            sell_stock(ticker, current_price, "PROFIT")

        # STOP LOSS
        elif pnl_pct <= -STOP_LOSS:
            log(f"  🛑 STOP LOSS! Selling...")
            sell_stock(ticker, current_price, "STOP-LOSS")


def sell_stock(ticker, price, reason):
    """Sell stock with market order"""
    try:
        log(f"🔒 SELLING: {ticker} (Reason: {reason})")

        # Get position qty
        position = trading_client.get_open_position(ticker)
        qty = abs(int(float(position.qty)))

        order_req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)
        log(f"✅ SELL ORDER SUBMITTED!")

        # Remove from tracking
        positions = load_positions()
        if ticker in positions:
            del positions[ticker]
            save_positions(positions)

        increment_daily_trades()

    except Exception as e:
        log(f"❌ Error selling {ticker}: {e}")


def scan_for_trades():
    """Scan for buying opportunities"""
    log("🔍 Scanning for trades...")

    if not is_market_hours():
        log("⏸️  Market closed")
        return

    if not can_trade_today():
        log(f"⏸️  Daily limit reached: {get_daily_trades()}/{MAX_DAILY_TRADES}")
        return

    try:
        account = trading_client.get_account()
        cash = float(account.cash)
        positions = trading_client.get_all_positions()
    except Exception as e:
        log(f"⚠️  Network error, will retry next cycle: {e}")
        return

    log(f"💰 Cash: ${cash:.2f} | Positions: {len(positions)}")

    if len(positions) >= MAX_POSITIONS:
        log(f"⏸️  Max positions reached: {len(positions)}/{MAX_POSITIONS}")
        return

    if cash < MIN_POSITION_SIZE:
        log(f"⏸️  Low cash: ${cash:.2f}")
        return

    # Scan tickers for momentum
    for ticker in TICKERS:
        log(f"📊 Checking {ticker}...")

        price = get_stock_price(ticker)
        if not price:
            continue

        log(f"  Price: ${price:.2f}")

        # Check if we can afford it with max position size
        qty = int(MAX_POSITION_SIZE / price)
        if qty < 1:
            log(f"  ⏭️  Too expensive")
            continue

        # Check momentum
        if check_momentum(ticker):
            log(f"  ✅ Momentum detected!")
            if buy_stock(ticker, price):
                log(f"✅ Trade placed for {ticker}!")
                return
        else:
            log(f"  ⏭️  No momentum")

    log("⏭️  No opportunities found")


def main():
    log("=" * 60)
    log("📈 STOCK DAY TRADING BOT")
    log("=" * 60)
    log(f"Tickers: {', '.join(TICKERS)}")
    log(f"Profit target: {PROFIT_TARGET*100:.1f}%")
    log(f"Stop loss: {STOP_LOSS*100:.1f}%")
    log(f"Max daily trades: {MAX_DAILY_TRADES}")
    log(f"Position size: ${MIN_POSITION_SIZE:.0f}-${MAX_POSITION_SIZE:.0f}")
    log("=" * 60)

    cycle = 0
    try:
        while True:
            cycle += 1
            log(f"\n{'='*60}")
            log(f"CYCLE {cycle}")
            log(f"{'='*60}")

            monitor_positions()
            scan_for_trades()

            log(f"\n⏰ Waiting {CYCLE_INTERVAL}s...")
            time.sleep(CYCLE_INTERVAL)

    except KeyboardInterrupt:
        log("\n🛑 Bot stopped")


if __name__ == "__main__":
    main()
