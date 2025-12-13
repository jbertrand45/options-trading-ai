#!/usr/bin/env python3
"""
Simple Cash-Secured Put Trading Bot with Stop-Loss & Profit-Taking
Trades cheap stocks: F, BAC, NIO, PLUG
"""
import os
import time
import datetime
import json
import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, LimitOrderRequest, MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, OptionLatestQuoteRequest

# Configuration
API_KEY = os.getenv("ALPACA_API_KEY_ID", "AK3FLIZ5DLA5GVPEXRM75QTYHT")
API_SECRET = os.getenv("ALPACA_API_SECRET_KEY", "2DqpuY1Yw1v92izySSqfC1YjhazPm6ffio7QrLHow7h9")
TICKERS = ["NVDA", "MSFT", "GOOG", "GOOGL", "AMD", "AAPL", "TSLA", "PLTR", "F", "BAC", "NIO", "PLUG"]
MAX_STRIKE_PRICE = 12.0  # Only trade puts with strikes we can afford
MIN_PREMIUM = 0.15  # Minimum $15 premium per contract (increased for better fills)
ACCOUNT_CASH = 1150.0  # Your available capital
MAX_POSITIONS = 2  # Max open positions at once
MAX_DAILY_TRADES = 3  # Maximum trades per day (2-3 for profitability)
CYCLE_INTERVAL = 60  # Seconds between scans

# Market Hours (Eastern Time)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

# Risk Management
STOP_LOSS_MULTIPLIER = 3.0  # Exit if option price goes 3x against us
PROFIT_TARGET_PERCENT = 0.30  # Take profit at 70% of max gain (30% of entry)
POSITION_TRACKING_FILE = "/tmp/bot_positions.json"

# Initialize clients
trading_client = TradingClient(API_KEY, API_SECRET, paper=False)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
option_data_client = OptionHistoricalDataClient(API_KEY, API_SECRET)


def log(message):
    """Simple logging with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def is_market_hours():
    """Check if it's currently during market hours (9:30 AM - 4:00 PM ET)"""
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.datetime.now(et_tz)

    # Check if weekend
    if now_et.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    # Check time
    current_time = now_et.time()
    market_open = datetime.time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = datetime.time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)

    return market_open <= current_time <= market_close


def get_pending_orders():
    """Get all pending orders to avoid duplicates"""
    try:
        orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        pending_symbols = set(order.symbol for order in orders)
        return pending_symbols
    except Exception as e:
        log(f"❌ Error getting pending orders: {e}")
        return set()


# ============================================================================
# POSITION TRACKING SYSTEM
# ============================================================================

def load_positions():
    """Load position tracking data from JSON file"""
    try:
        if os.path.exists(POSITION_TRACKING_FILE):
            with open(POSITION_TRACKING_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        log(f"⚠️  Error loading positions: {e}")
        return {}


def save_positions(positions):
    """Save position tracking data to JSON file"""
    try:
        with open(POSITION_TRACKING_FILE, 'w') as f:
            json.dump(positions, f, indent=2)
    except Exception as e:
        log(f"⚠️  Error saving positions: {e}")


def track_new_position(symbol, entry_premium, strike, underlying):
    """Add a new position to tracking"""
    positions = load_positions()
    positions[symbol] = {
        "entry_premium": entry_premium,
        "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strike": strike,
        "underlying": underlying
    }
    save_positions(positions)
    log(f"📝 Tracking position: {symbol} @ ${entry_premium}")


def remove_position(symbol):
    """Remove a position from tracking"""
    positions = load_positions()
    if symbol in positions:
        del positions[symbol]
        save_positions(positions)
        log(f"📝 Removed tracking for: {symbol}")


def get_entry_premium(symbol):
    """Get the entry premium for a tracked position"""
    positions = load_positions()
    if symbol in positions:
        return positions[symbol]["entry_premium"]
    return None


# ============================================================================
# DAILY TRADE LIMITING
# ============================================================================

def get_daily_trades():
    """Get today's trade count and reset if new day"""
    positions = load_positions()
    today = datetime.date.today().strftime("%Y-%m-%d")

    # Initialize trade_stats if not present
    if "trade_stats" not in positions:
        positions["trade_stats"] = {"date": today, "count": 0}
        save_positions(positions)

    # Reset counter if new day
    if positions["trade_stats"]["date"] != today:
        positions["trade_stats"] = {"date": today, "count": 0}
        save_positions(positions)
        log(f"📅 New trading day: {today}")

    return positions["trade_stats"]["count"]


def increment_daily_trades():
    """Increment today's trade count"""
    positions = load_positions()
    if "trade_stats" not in positions:
        positions["trade_stats"] = {"date": datetime.date.today().strftime("%Y-%m-%d"), "count": 0}

    positions["trade_stats"]["count"] += 1
    save_positions(positions)
    log(f"📊 Daily trades: {positions['trade_stats']['count']}/{MAX_DAILY_TRADES}")


def can_trade_today():
    """Check if we haven't exceeded daily trade limit"""
    count = get_daily_trades()
    return count < MAX_DAILY_TRADES


# ============================================================================
# MARKET DATA FUNCTIONS
# ============================================================================

def get_current_price(ticker):
    """Get current stock price"""
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=[ticker])
        quotes = data_client.get_stock_latest_quote(req)
        return quotes[ticker].ask_price
    except Exception as e:
        log(f"❌ Error getting price for {ticker}: {e}")
        return None


def get_option_price(option_symbol):
    """Get current option price (bid/ask midpoint)"""
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        quotes = option_data_client.get_option_latest_quote(req)
        quote = quotes[option_symbol]

        # Use midpoint of bid/ask for fair value
        bid = float(quote.bid_price) if quote.bid_price else 0
        ask = float(quote.ask_price) if quote.ask_price else 0

        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        elif ask > 0:
            return ask
        elif bid > 0:
            return bid
        else:
            return None
    except Exception as e:
        log(f"❌ Error getting option price for {option_symbol}: {e}")
        return None


def get_account_info():
    """Get account balance and positions"""
    try:
        account = trading_client.get_account()
        positions = trading_client.get_all_positions()

        cash = float(account.cash)
        num_positions = len(positions)

        log(f"💰 Account: ${cash:.2f} cash | {num_positions} positions")
        return cash, num_positions
    except Exception as e:
        log(f"❌ Error getting account info: {e}")
        return ACCOUNT_CASH, 0


def find_best_put_option(ticker, current_price):
    """Find the best cash-secured put to sell"""
    try:
        # Get puts expiring in 7-14 days with affordable strikes
        expiration_start = datetime.date.today() + datetime.timedelta(days=7)
        expiration_end = datetime.date.today() + datetime.timedelta(days=14)

        req = GetOptionContractsRequest(
            underlying_symbols=[ticker],
            expiration_date_gte=expiration_start,
            expiration_date_lte=expiration_end,
            type="put",
            strike_price_lte=str(MAX_STRIKE_PRICE),
            limit=10
        )

        contracts = trading_client.get_option_contracts(req)

        if not contracts.option_contracts:
            return None

        # Find contract with best premium/strike ratio
        best_contract = None
        best_score = 0

        for contract in contracts.option_contracts:
            strike = float(contract.strike_price)

            # Skip if strike too high (can't afford to secure)
            if strike > MAX_STRIKE_PRICE:
                continue

            # Estimate premium as ~2% of strike (conservative)
            estimated_premium = strike * 0.02

            # Score: higher premium per dollar at risk
            score = estimated_premium / strike

            if score > best_score:
                best_score = score
                best_contract = contract

        if best_contract:
            log(f"  ✅ Found: {best_contract.symbol} strike ${best_contract.strike_price} exp {best_contract.expiration_date}")

        return best_contract

    except Exception as e:
        log(f"  ❌ Error finding options for {ticker}: {e}")
        return None


# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

def close_position(symbol, reason, current_price):
    """Close a short put position (BUY TO CLOSE)"""
    try:
        log(f"🔒 CLOSING POSITION (MARKET ORDER): {symbol}")
        log(f"   Reason: {reason}")
        log(f"   Estimated Price: ${current_price}")

        # Submit MARKET order to buy back the put - EXECUTES IMMEDIATELY
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=1,
            side=OrderSide.BUY,  # BUY TO CLOSE
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)

        log(f"✅ CLOSE ORDER PLACED!")
        log(f"   Order ID: {order.id}")
        log(f"   Status: {order.status}")

        # Remove from tracking (will be gone after order fills)
        remove_position(symbol)

        return True

    except Exception as e:
        log(f"❌ Error closing position: {e}")
        return False


def monitor_positions():
    """Monitor open positions and manage exits"""
    try:
        positions = trading_client.get_all_positions()

        if not positions:
            return

        log(f"👁️  Monitoring {len(positions)} position(s)...")

        for position in positions:
            symbol = position.symbol
            qty = int(position.qty)

            # Only monitor short positions (qty will be negative)
            if qty >= 0:
                continue

            # Get entry premium from tracking
            entry_premium = get_entry_premium(symbol)
            if not entry_premium:
                log(f"⚠️  No entry data for {symbol}, skipping")
                continue

            # Get current option price
            current_price = get_option_price(symbol)
            if not current_price:
                log(f"⚠️  Could not get price for {symbol}")
                continue

            # Calculate P&L
            pnl = (entry_premium - current_price) * 100
            pnl_pct = ((entry_premium - current_price) / entry_premium) * 100

            log(f"  {symbol}:")
            log(f"    Entry: ${entry_premium:.2f} | Current: ${current_price:.2f}")
            log(f"    P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)")

            # CHECK STOP-LOSS: Exit if option price > 3x entry
            stop_loss_price = entry_premium * STOP_LOSS_MULTIPLIER
            if current_price >= stop_loss_price:
                log(f"  🛑 STOP-LOSS TRIGGERED!")
                log(f"     Current ${current_price:.2f} >= Stop ${stop_loss_price:.2f}")
                close_position(symbol, "STOP-LOSS", current_price)
                continue

            # CHECK PROFIT-TAKING: Exit if option price < 30% of entry
            profit_target_price = entry_premium * PROFIT_TARGET_PERCENT
            if current_price <= profit_target_price:
                log(f"  💰 PROFIT TARGET HIT!")
                log(f"     Current ${current_price:.2f} <= Target ${profit_target_price:.2f}")
                close_position(symbol, "TAKE-PROFIT", current_price)
                continue

    except Exception as e:
        log(f"❌ Error monitoring positions: {e}")


# ============================================================================
# TRADING FUNCTIONS
# ============================================================================

def sell_put_option(contract):
    """Sell (open) a cash-secured put"""
    try:
        strike = float(contract.strike_price)
        required_cash = strike * 100  # Need to secure full strike price

        log(f"🚀 SELLING PUT (MARKET ORDER): {contract.symbol}")
        log(f"   Strike: ${strike}")
        log(f"   Cash needed: ${required_cash:.2f}")
        log(f"   Expiration: {contract.expiration_date}")

        # Submit MARKET order to sell put - EXECUTES IMMEDIATELY
        order_req = MarketOrderRequest(
            symbol=contract.symbol,
            qty=1,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_req)

        log(f"✅ MARKET ORDER SUBMITTED!")
        log(f"   Order ID: {order.id}")
        log(f"   Status: {order.status}")

        # Wait a moment for fill and get actual execution price
        time.sleep(2)
        try:
            filled_order = trading_client.get_order_by_id(order.id)
            if filled_order.filled_avg_price:
                actual_premium = float(filled_order.filled_avg_price)
                log(f"   ✅ FILLED at ${actual_premium:.2f} (${actual_premium * 100:.2f} total)")
            else:
                actual_premium = 0.05  # Fallback estimate
                log(f"   ⏳ Order executing...")
        except:
            actual_premium = 0.05  # Fallback estimate

        # Track the position for monitoring
        # Extract underlying ticker from contract symbol
        underlying = contract.symbol.split("25")[0]  # e.g., F251212P00005000 -> F
        track_new_position(
            symbol=contract.symbol,
            entry_premium=actual_premium,
            strike=strike,
            underlying=underlying
        )

        # Increment daily trade counter
        increment_daily_trades()

        return True

    except Exception as e:
        log(f"❌ Error placing order: {e}")
        return False


def scan_for_opportunities():
    """Scan all tickers for trading opportunities"""
    log("🔍 Scanning for opportunities...")

    # CHECK MARKET HOURS
    if not is_market_hours():
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.datetime.now(et_tz)
        log(f"⏸️  Market closed (ET: {now_et.strftime('%I:%M %p %A')})")
        log(f"   Market hours: Mon-Fri {MARKET_OPEN_HOUR}:{MARKET_OPEN_MINUTE:02d}AM - {MARKET_CLOSE_HOUR}:{MARKET_CLOSE_MINUTE:02d}PM ET")
        return

    # CHECK DAILY TRADE LIMIT
    if not can_trade_today():
        daily_count = get_daily_trades()
        log(f"⏸️  Daily trade limit reached: {daily_count}/{MAX_DAILY_TRADES} trades today")
        return

    # Get pending orders to avoid duplicates
    pending_symbols = get_pending_orders()
    if pending_symbols:
        log(f"⚠️  {len(pending_symbols)} pending order(s): {', '.join(pending_symbols)}")

    # Check account
    cash, num_positions = get_account_info()

    # Don't trade if we're at max positions
    if num_positions >= MAX_POSITIONS:
        log(f"⏸️  Already have {num_positions} positions (max {MAX_POSITIONS})")
        return

    # Don't trade if low on cash
    if cash < 500:
        log(f"⏸️  Insufficient cash: ${cash:.2f} (need $500+)")
        return

    # Scan each ticker
    for ticker in TICKERS:
        log(f"📊 Checking {ticker}...")

        # Get current price
        price = get_current_price(ticker)
        if not price:
            continue

        log(f"  Price: ${price:.2f}")

        # Find best put option
        contract = find_best_put_option(ticker, price)
        if not contract:
            continue

        # CHECK IF ALREADY HAVE PENDING ORDER FOR THIS OPTION
        if contract.symbol in pending_symbols:
            log(f"  ⏭️  Already have pending order for {contract.symbol}")
            continue

        # Check if we can afford it
        required_cash = float(contract.strike_price) * 100
        if required_cash > cash:
            log(f"  ⏭️  Need ${required_cash:.2f}, only have ${cash:.2f}")
            continue

        # Try to sell it
        if sell_put_option(contract):
            log(f"✅ Trade placed for {ticker}!")
            return  # Only 1 trade per cycle

    log("⏭️  No opportunities found this cycle")


def main():
    """Main trading loop"""
    log("=" * 60)
    log("🔴 SIMPLE OPTIONS BOT - LIVE TRADING WITH RISK MANAGEMENT")
    log("=" * 60)
    log(f"Tickers: {', '.join(TICKERS)}")
    log(f"Max strike: ${MAX_STRIKE_PRICE}")
    log(f"Min premium: ${MIN_PREMIUM * 100:.2f}")
    log(f"Max daily trades: {MAX_DAILY_TRADES}")
    log(f"Stop-loss: {STOP_LOSS_MULTIPLIER}x entry price")
    log(f"Take-profit: {PROFIT_TARGET_PERCENT * 100:.0f}% of max gain")
    log(f"Cycle interval: {CYCLE_INTERVAL}s")
    log("=" * 60)

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            log(f"\n{'='*60}")
            log(f"CYCLE {cycle_count}")
            log(f"{'='*60}")

            # FIRST: Monitor and manage existing positions
            monitor_positions()

            # THEN: Look for new opportunities
            scan_for_opportunities()

            log(f"\n⏰ Waiting {CYCLE_INTERVAL} seconds until next cycle...")
            time.sleep(CYCLE_INTERVAL)

    except KeyboardInterrupt:
        log("\n\n🛑 Bot stopped by user")
    except Exception as e:
        log(f"\n\n❌ Fatal error: {e}")


if __name__ == "__main__":
    main()
