#!/usr/bin/env python3
"""
Simple Options Trading Bot - BUY calls/puts, SELL for profit
Strategy: Buy cheap options, sell when they go up
"""
import os
import time
import datetime
import json
import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, OptionLatestQuoteRequest

# Configuration
API_KEY = os.getenv("ALPACA_API_KEY_ID", "AK3FLIZ5DLA5GVPEXRM75QTYHT")
API_SECRET = os.getenv("ALPACA_API_SECRET_KEY", "2DqpuY1Yw1v92izySSqfC1YjhazPm6ffio7QrLHow7h9")
TICKERS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "F", "NIO", "BAC", "PLUG"]
MAX_OPTION_PRICE = 5.00  # Max $500 per contract
MIN_OPTION_PRICE = 0.05  # Min $5 per contract
ACCOUNT_CASH = 1150.0
MAX_POSITIONS = 3
MAX_DAILY_TRADES = 5
CYCLE_INTERVAL = 30

# Risk Management
PROFIT_TARGET = 0.20  # Sell at 20% profit
STOP_LOSS = 0.15  # Sell at 15% loss
POSITION_TRACKING_FILE = "/tmp/bot_positions.json"

# Market Hours
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

# Initialize clients
trading_client = TradingClient(API_KEY, API_SECRET, paper=False)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
option_data_client = OptionHistoricalDataClient(API_KEY, API_SECRET)


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


def get_option_price(symbol):
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = option_data_client.get_option_latest_quote(req)
        quote = quotes[symbol]
        ask = float(quote.ask_price) if quote.ask_price else 0
        return ask if ask > 0 else None
    except:
        return None


def find_cheap_option(ticker):
    """Find a cheap call or put option to buy"""
    try:
        # Get options expiring in 1-2 weeks
        exp_start = datetime.date.today() + datetime.timedelta(days=7)
        exp_end = datetime.date.today() + datetime.timedelta(days=14)

        # Try calls first, then puts
        for opt_type in ["call", "put"]:
            req = GetOptionContractsRequest(
                underlying_symbols=[ticker],
                expiration_date_gte=exp_start,
                expiration_date_lte=exp_end,
                type=opt_type,
                limit=30
            )

            contracts = trading_client.get_option_contracts(req)
            if not contracts.option_contracts:
                continue

            # Find cheapest option
            for contract in contracts.option_contracts:
                price = get_option_price(contract.symbol)
                if price and MIN_OPTION_PRICE <= price <= MAX_OPTION_PRICE:
                    log(f"  Found {opt_type.upper()}: {contract.symbol} @ ${price:.2f}")
                    return contract, price

        return None
    except Exception as e:
        log(f"  Error finding options: {e}")
        return None


def buy_option(contract, price):
    """BUY a call option"""
    try:
        cost = price * 100
        log(f"💰 BUYING CALL: {contract.symbol}")
        log(f"   Price: ${price:.2f} (${cost:.2f} total)")
        log(f"   Expiration: {contract.expiration_date}")

        order_req = MarketOrderRequest(
            symbol=contract.symbol,
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)
        log(f"✅ BUY ORDER SUBMITTED!")
        log(f"   Order ID: {order.id}")

        # Track position
        positions = load_positions()
        positions[contract.symbol] = {
            "entry_price": price,
            "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": contract.underlying_symbol
        }
        save_positions(positions)

        increment_daily_trades()
        return True

    except Exception as e:
        log(f"❌ Error buying: {e}")
        return False


def monitor_positions():
    """Monitor positions and sell for profit/loss"""
    try:
        positions = trading_client.get_all_positions()
        if not positions:
            return

        log(f"👁️  Monitoring {len(positions)} position(s)...")
        tracked = load_positions()

        for pos in positions:
            symbol = pos.symbol
            if symbol not in tracked:
                continue

            entry_price = tracked[symbol]["entry_price"]
            current_price = float(pos.current_price)
            pnl_pct = ((current_price - entry_price) / entry_price)

            log(f"  {symbol}:")
            log(f"    Entry: ${entry_price:.2f} | Current: ${current_price:.2f}")
            log(f"    P&L: {pnl_pct*100:+.1f}%")

            # TAKE PROFIT
            if pnl_pct >= PROFIT_TARGET:
                log(f"  💰 PROFIT TARGET HIT! Selling...")
                sell_option(symbol, current_price, "PROFIT")

            # STOP LOSS
            elif pnl_pct <= -STOP_LOSS:
                log(f"  🛑 STOP LOSS! Selling...")
                sell_option(symbol, current_price, "STOP-LOSS")

    except Exception as e:
        log(f"❌ Error monitoring: {e}")


def sell_option(symbol, price, reason):
    """SELL an option"""
    try:
        log(f"🔒 SELLING: {symbol} (Reason: {reason})")

        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=1,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)
        log(f"✅ SELL ORDER SUBMITTED!")

        # Remove from tracking
        positions = load_positions()
        if symbol in positions:
            del positions[symbol]
            save_positions(positions)

    except Exception as e:
        log(f"❌ Error selling: {e}")


def scan_for_trades():
    """Scan for buying opportunities"""
    log("🔍 Scanning for trades...")

    if not is_market_hours():
        log("⏸️  Market closed")
        return

    if not can_trade_today():
        log(f"⏸️  Daily limit reached: {get_daily_trades()}/{MAX_DAILY_TRADES}")
        return

    account = trading_client.get_account()
    cash = float(account.cash)
    positions = trading_client.get_all_positions()

    log(f"💰 Cash: ${cash:.2f} | Positions: {len(positions)}")

    if len(positions) >= MAX_POSITIONS:
        log(f"⏸️  Max positions reached: {len(positions)}/{MAX_POSITIONS}")
        return

    if cash < 200:
        log(f"⏸️  Low cash: ${cash:.2f}")
        return

    # Scan tickers
    for ticker in TICKERS:
        log(f"📊 Checking {ticker}...")
        result = find_cheap_option(ticker)
        if result:
            contract, price = result
            if buy_option(contract, price):
                log(f"✅ Trade placed for {ticker}!")
                return

    log("⏭️  No opportunities found")


def main():
    log("=" * 60)
    log("💰 OPTIONS BOT - BUY & SELL FOR PROFIT")
    log("=" * 60)
    log(f"Tickers: {', '.join(TICKERS)}")
    log(f"Profit target: {PROFIT_TARGET*100:.0f}%")
    log(f"Stop loss: {STOP_LOSS*100:.0f}%")
    log(f"Max daily trades: {MAX_DAILY_TRADES}")
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
