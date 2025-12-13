#!/bin/bash
# Check Current Trades and Orders

cd /Users/joeybertrand/Desktop/tradingAI

python3 << 'EOF'
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

API_KEY = "AK3FLIZ5DLA5GVPEXRM75QTYHT"
API_SECRET = "2DqpuY1Yw1v92izySSqfC1YjhazPm6ffio7QrLHow7h9"

client = TradingClient(API_KEY, API_SECRET, paper=False)

print("=" * 60)
print("💰 ACCOUNT STATUS")
print("=" * 60)

account = client.get_account()
print(f"Cash: ${float(account.cash):.2f}")
print(f"Buying Power: ${float(account.buying_power):.2f}")

print("\n" + "=" * 60)
print("📋 OPEN ORDERS")
print("=" * 60)

req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=20)
orders = client.get_orders(filter=req)

if orders:
    for order in orders:
        print(f"\n{order.symbol}")
        print(f"  Side: {order.side.value.upper()}")
        print(f"  Qty: {order.qty}")
        print(f"  Limit Price: ${order.limit_price}")
        print(f"  Status: {order.status}")
        print(f"  Potential: ${float(order.limit_price) * 100:.2f}")
else:
    print("\nNo open orders")

print("\n" + "=" * 60)
print("📊 POSITIONS")
print("=" * 60)

positions = client.get_all_positions()

if positions:
    for pos in positions:
        pnl = float(pos.unrealized_pl)
        pnl_pct = float(pos.unrealized_plpc) * 100
        print(f"\n{pos.symbol}")
        print(f"  Qty: {pos.qty}")
        print(f"  Entry: ${pos.avg_entry_price}")
        print(f"  Current: ${pos.current_price}")
        print(f"  P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
else:
    print("\nNo open positions")

print("\n" + "=" * 60)

EOF
