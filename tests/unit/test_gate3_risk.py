from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest

from src.domain.dtos import (
    AIVerificationResultDTO,
    MarketAnomalyDTO,
    TradeRecordDTO,
)
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType
from src.infrastructure.db.repositories import AnomalyRepository, TradeRepository
from src.infrastructure.db.sqlite_client import SQLiteClient
from src.use_cases.gate3_risk_engine import Gate3RiskEngine


def _make_hl_anomaly(
    price: Decimal = Decimal("100.0"),
    atr_14: Decimal = Decimal("2.0"),
    direction: SignalDirection = SignalDirection.LONG,
) -> MarketAnomalyDTO:
    return MarketAnomalyDTO(
        anomaly_id="anom-hl-risk-1",
        timestamp_utc=datetime(2026, 11, 16, 8, 0, 0, tzinfo=timezone.utc),
        venue=VenueType.HYPERLIQUID,
        symbol_or_market_id="SOL",
        asset_name_or_question="SOL Hyperliquid Perpetuals",
        sz_decimals_or_tick=Decimal("0.01"),
        current_price=price,
        rvol_ratio=3.1,
        oi_delta_1h_pct=0.07,
        funding_rate_hourly=0.00001,
        vwap_distance_pct=0.02,
        btc_1h_return_pct=0.01,
        atr_14=atr_14,
        bid_ask_spread=Decimal("0.01"),
        proposed_direction=direction,
    )


def _make_verification(
    anomaly_id: str = "anom-hl-risk-1",
    prob: float = 0.72,
    score: int = 84,
    veto: bool = False,
) -> AIVerificationResultDTO:
    return AIVerificationResultDTO(
        anomaly_id=anomaly_id,
        primary_catalyst_summary="Verified institutional inflow catalyst",
        source_timestamps_verified=True,
        bull_thesis_score=90,
        red_team_flaws_detected=[],
        red_team_veto=veto,
        red_team_penalty=90 - score,
        estimated_win_probability=prob,
        final_confidence_score=score,
    )


def test_hyperliquid_atr_sizing_and_2x_leverage_cap() -> None:
    engine = Gate3RiskEngine()
    equity = Decimal("10000.0")

    # Case 1: Normal ATR = $2.0 -> Delta_SL = 1.8 * 2.0 = $3.60
    # Risk = 2% of $10,000 = $200.0 -> Q = 200 / 3.60 = 55.55 units ($5,555.00 < $20,000 2x cap)
    anom = _make_hl_anomaly(price=Decimal("100.0"), atr_14=Decimal("2.0"))
    verif = _make_verification(prob=0.65, score=82)
    order = engine.size_hyperliquid_order(anom, verif, account_equity_usd=equity)

    assert order is not None
    assert order.stop_loss_price == Decimal("96.400000")
    assert order.take_profit_price == Decimal("110.800000")
    assert order.position_size_units == Decimal("55.55")
    assert order.position_size_usd == Decimal("5555.00")
    assert order.risk_amount_usd <= Decimal("200.00")

    # Case 2: Tight ATR = $0.10 -> Delta_SL = $0.18
    # Uncapped Q = 200 / 0.18 = 1111.11 units ($111,111).
    # With MAX_MARGIN_ALLOCATION_PER_TRADE_PCT = 35% ($3,500 margin on $10,000 equity) and 2.0x leverage,
    # max notional for a single trade is 2.0 * $3,500 = $7,000.00 (70.00 units).
    anom_tight = _make_hl_anomaly(price=Decimal("100.0"), atr_14=Decimal("0.10"))
    order_capped = engine.size_hyperliquid_order(
        anom_tight, verif, account_equity_usd=equity
    )
    assert order_capped is not None
    assert order_capped.position_size_usd == Decimal("7000.00")
    assert order_capped.position_size_units == Decimal("70.00")

    # On a $100.00 account, tight ATR caps single-trade notional at $70.00 ($35.00 margin locked, leaving ~$65.00 available)
    order_capped_100 = engine.size_hyperliquid_order(
        anom_tight, verif, account_equity_usd=Decimal("100.00")
    )
    assert order_capped_100 is not None
    assert order_capped_100.position_size_usd == Decimal("70.00")
    assert order_capped_100.position_size_units == Decimal("0.70")

    # If max_margin_allocation_per_trade_pct = 1.0 (100%), global 2.0x leverage cap ($20,000 on $10,000) applies
    engine_full_margin = Gate3RiskEngine(max_margin_allocation_per_trade_pct=Decimal("1.0"))
    order_2x_global = engine_full_margin.size_hyperliquid_order(
        anom_tight, verif, account_equity_usd=equity
    )
    assert order_2x_global is not None
    assert order_2x_global.position_size_usd == Decimal("20000.00")
    assert order_2x_global.position_size_units == Decimal("200.00")

    # Case 3: $100.00 small account where 2% risk ($2.00) yields < $10.00 notional,
    # e.g. Price = $100.00, ATR = $15.0 -> Delta_SL = $27.0 (27% stop distance).
    # At $10.00 minimum notional (0.10 units), risk is $2.70 <= 3.0% of $100.00 ($3.00), so it scales up safely to $10.00!
    anom_floor_ok = _make_hl_anomaly(price=Decimal("100.0"), atr_14=Decimal("15.0"))
    order_floor_ok = engine.size_hyperliquid_order(
        anom_floor_ok, verif, account_equity_usd=Decimal("100.00")
    )
    assert order_floor_ok is not None
    assert order_floor_ok.position_size_usd == Decimal("10.00")
    assert order_floor_ok.risk_amount_usd == Decimal("2.70")

    # Case 4: $100.00 account where scaling up to $10.00 minimum notional would risk > 3.0% ($3.00):
    # Price = $100.00, ATR = $25.0 -> Delta_SL = $45.0 -> at $10.00 notional (0.10 units), risk is $4.50 > $3.00 -> rejected!
    anom_floor_reject = _make_hl_anomaly(price=Decimal("100.0"), atr_14=Decimal("25.0"))
    order_floor_reject = engine.size_hyperliquid_order(
        anom_floor_reject, verif, account_equity_usd=Decimal("100.00")
    )
    assert order_floor_reject is None


def test_trailing_stop_to_breakeven() -> None:
    # Entry = 100, ATR = 2.0 -> Delta_SL = 3.60 -> +1.5 * Delta_SL = +5.40 -> trigger at 105.40
    no_trigger = Gate3RiskEngine.compute_trailing_stop_breakeven(
        entry_price=Decimal("100.0"),
        current_price=Decimal("104.0"),
        current_stop_loss=Decimal("96.4"),
        atr_14=Decimal("2.0"),
        direction=SignalDirection.LONG,
    )
    assert no_trigger is None

    triggered = Gate3RiskEngine.compute_trailing_stop_breakeven(
        entry_price=Decimal("100.0"),
        current_price=Decimal("105.50"),
        current_stop_loss=Decimal("96.4"),
        atr_14=Decimal("2.0"),
        direction=SignalDirection.LONG,
    )
    assert triggered is not None
    assert triggered > Decimal("100.0")


def test_polymarket_dual_sided_quarter_kelly_and_5pct_cap() -> None:
    engine = Gate3RiskEngine()
    equity = Decimal("10000.0")

    pm_anomaly = MarketAnomalyDTO(
        anomaly_id="anom-pm-kelly",
        timestamp_utc=datetime(2026, 11, 16, 8, 0, 0, tzinfo=timezone.utc),
        venue=VenueType.POLYMARKET,
        symbol_or_market_id="mkt-500",
        asset_name_or_question="Will CPI print below 2.5% tomorrow?",
        target_token_id="yes-tok-500",
        no_token_id="no-tok-500",
        sz_decimals_or_tick=Decimal("0.01"),
        current_price=Decimal("0.50"),
        rvol_ratio=2.8,
        hours_to_resolution=16.0,
        bid_ask_spread=Decimal("0.02"),
        proposed_direction=SignalDirection.BUY_YES,
    )

    # 1. BUY_YES edge = 0.66 - 0.50 = 0.16 (>= 0.12)
    # f = 0.25 * (0.16 / (1 - 0.50)) = 0.25 * 0.32 = 0.08 -> capped at 5% ($500.00)
    verif_yes = _make_verification(anomaly_id="anom-pm-kelly", prob=0.66, score=85)
    order_yes = engine.size_polymarket_order(
        pm_anomaly, verif_yes, account_equity_usd=equity
    )
    assert order_yes is not None
    assert order_yes.direction == SignalDirection.BUY_YES
    assert order_yes.target_token_id == "yes-tok-500"
    assert order_yes.position_size_usd == Decimal("500.00")

    # 2. BUY_NO when P_model = 0.25 (so 1 - P_model = 0.75 vs P_no = 0.50 -> edge = 0.25 >= 0.12)
    # Moderate edge: P_model = 0.36 -> 1 - P_model = 0.64, P_no = 0.50 -> edge = 0.14
    # f = 0.25 * (0.14 / 0.50) = 0.07 -> capped at $500; let's test uncapped: P_yes = 0.30, P_no = 0.70
    # Wait: if P_yes = 0.60, P_no = 0.40, P_model = 0.45 -> (1 - P_model) = 0.55 -> Edge_NO = 0.15
    # f = 0.25 * (0.15 / (1 - 0.40)) = 0.25 * (0.15 / 0.60) = 0.0625 -> capped at $500
    # For uncapped Kelly < 5%: P_yes = 0.60, P_no = 0.40, P_model = 0.48 -> Edge_NO = 0.52 - 0.40 = 0.12
    # f = 0.25 * (0.12 / 0.60) = 0.05 -> $500.00
    pm_anomaly_no = pm_anomaly.model_copy(update={"current_price": Decimal("0.70")})
    # P_yes = 0.70, P_no = 0.30. Let P_model = 0.56 -> 1 - P_model = 0.44 -> Edge_NO = 0.44 - 0.30 = 0.14
    # f = 0.25 * (0.14 / (1 - 0.30)) = 0.25 * 0.20 = 0.05 -> if Edge_NO = 0.126 (P_model = 0.574):
    # f = 0.25 * (0.126 / 0.70) = 0.045 -> $450.00 (< $500 cap)
    verif_no = _make_verification(anomaly_id="anom-pm-kelly", prob=0.574, score=84)
    order_no = engine.size_polymarket_order(
        pm_anomaly_no, verif_no, account_equity_usd=equity
    )
    assert order_no is not None
    assert order_no.direction == SignalDirection.BUY_NO
    assert order_no.target_token_id == "no-tok-500"
    assert order_no.position_size_usd == Decimal("450.00")

    # 3. Reject when Edge < 0.12
    verif_low_edge = _make_verification(anomaly_id="anom-pm-kelly", prob=0.55, score=84)
    assert (
        engine.size_polymarket_order(
            pm_anomaly, verif_low_edge, account_equity_usd=equity
        )
        is None
    )


@pytest.mark.asyncio
async def test_circuit_breaker_consecutive_losses_and_daily_drawdown(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "test_cb.db"
    client = SQLiteClient(str(db_file))
    await client.initialize()

    try:
        anom_repo = AnomalyRepository(client)
        trade_repo = TradeRepository(client)
        now = datetime(2026, 11, 16, 10, 0, 0, tzinfo=timezone.utc)

        base_anom = _make_hl_anomaly()
        await anom_repo.save_anomaly(base_anom, passed_gate2=True)

        # Insert 3 consecutive losing trades (small loss -$50 each = -$150 total, -1.5% drawdown)
        for i in range(3):
            t_id = f"loss-ord-{i}"
            await trade_repo.create_trade(
                TradeRecordDTO(
                    order_id=t_id,
                    anomaly_id=base_anom.anomaly_id,
                    venue=VenueType.HYPERLIQUID,
                    symbol_or_market_id="SOL",
                    execution_mode=ExecutionMode.PAPER,
                    direction=SignalDirection.LONG,
                    status=OrderStatus.CLOSED_SL,
                    entry_price=Decimal("100.0"),
                    exit_price=Decimal("98.0"),
                    stop_loss_price=Decimal("98.0"),
                    take_profit_price=Decimal("106.0"),
                    position_size_usd=Decimal("2500.0"),
                    position_size_units=Decimal("25.0"),
                    realized_pnl_usd=Decimal("-50.0"),
                    opened_at_utc=now,
                    closed_at_utc=now,
                )
            )

        engine_rule1 = Gate3RiskEngine(
            trade_repo=trade_repo,
            starting_daily_equity_usd=Decimal("10000.0"),
        )
        cb1 = await engine_rule1.check_circuit_breaker(now_utc=now)
        assert cb1.is_active is True
        assert cb1.consecutive_losses == 3
        assert "3 consecutive losses" in cb1.reason

        # Rule 2: Daily drawdown <= -5.0% cancels open trades and triggers circuit breaker
        await trade_repo.create_trade(
            TradeRecordDTO(
                order_id="open-ord-to-cancel",
                anomaly_id=base_anom.anomaly_id,
                venue=VenueType.HYPERLIQUID,
                symbol_or_market_id="SOL",
                execution_mode=ExecutionMode.PAPER,
                direction=SignalDirection.LONG,
                status=OrderStatus.OPEN,
                entry_price=Decimal("100.0"),
                stop_loss_price=Decimal("96.4"),
                take_profit_price=Decimal("110.8"),
                position_size_usd=Decimal("5000.0"),
                position_size_units=Decimal("50.0"),
                opened_at_utc=now,
            )
        )

        engine_rule2 = Gate3RiskEngine(
            trade_repo=trade_repo,
            starting_daily_equity_usd=Decimal("10000.0"),
        )
        # Realized PnL is -$150, pass unrealized PnL = -$400 -> Total = -$550 (-5.5% <= -5.0%)
        cb2 = await engine_rule2.check_circuit_breaker(
            unrealized_pnl_usd=Decimal("-400.0"),
            now_utc=now,
        )
        assert cb2.is_active is True
        assert "Daily drawdown" in cb2.reason
        open_remaining = await trade_repo.list_open_trades()
        assert len(open_remaining) == 0
    finally:
        await client.close()
