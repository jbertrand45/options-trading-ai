"""Risk manager tests."""

from trading_ai.risk.manager import PositionSizingInput, RiskManager


def test_risk_manager_sizes_position_with_confidence() -> None:
    manager = RiskManager(max_daily_loss_pct=0.05, min_confidence=0.2)
    params = PositionSizingInput(
        account_equity=150.0,
        trade_risk_fraction=0.02,
        contract_price=10.0,
        confidence=0.81,
        max_positions=2,
        spread=0.5,
        available_volume=100,
    )
    size = manager.size_position(params)
    assert size >= 0


def test_risk_manager_blocks_low_confidence() -> None:
    manager = RiskManager(min_confidence=0.3)
    params = PositionSizingInput(
        account_equity=150.0,
        trade_risk_fraction=0.02,
        contract_price=5.0,
        confidence=0.1,
    )
    assert manager.size_position(params) == 0


def test_risk_manager_blocks_wide_spreads() -> None:
    manager = RiskManager(max_spread_pct=0.1)
    params = PositionSizingInput(
        account_equity=1000.0,
        trade_risk_fraction=0.02,
        contract_price=1.0,
        confidence=0.9,
        spread=0.2,
        available_volume=100,
    )
    assert manager.size_position(params) == 0


def test_risk_manager_respects_liquidity() -> None:
    manager = RiskManager(min_liquidity=100.0, max_spread_pct=1.0)
    params = PositionSizingInput(
        account_equity=1000.0,
        trade_risk_fraction=0.02,
        contract_price=2.0,
        confidence=0.9,
        spread=0.05,
        available_volume=50.0,
        max_positions=5,
    )
    size = manager.size_position(params)
    assert size <= 5


def test_stop_and_take_profit_levels() -> None:
    manager = RiskManager()
    stop = manager.stop_loss_price(entry_price=5.0, risk_fraction=0.2)
    limit = manager.take_profit_price(entry_price=5.0, risk_fraction=0.2)
    assert stop < 5.0 < limit
