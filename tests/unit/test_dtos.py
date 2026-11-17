from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.config.settings import Settings
from src.domain.dtos import (
    AIVerificationResultDTO,
    ApprovedOrderDTO,
    BrierTrackingDTO,
    MarketAnomalyDTO,
    OISnapshotDTO,
    TradeRecordDTO,
)
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType
from src.infrastructure.db.repositories import (
    AIVerificationRepository,
    AccountLedgerRepository,
    AnomalyRepository,
    BrierRepository,
    OISnapshotRepository,
    TradeRepository,
)
from src.infrastructure.db.sqlite_client import SQLiteClient


def test_dtos_immutability_and_validation() -> None:
    now = datetime.now(timezone.utc)
    anomaly = MarketAnomalyDTO(
        anomaly_id="anom-hl-001",
        timestamp_utc=now,
        venue=VenueType.HYPERLIQUID,
        symbol_or_market_id="HYPE",
        asset_name_or_question="HYPE",
        sz_decimals_or_tick=Decimal("0.01"),
        current_price=Decimal("25.50"),
        rvol_ratio=3.2,
        oi_delta_1h_pct=0.08,
        funding_rate_hourly=0.00002,
        vwap_distance_pct=0.03,
        btc_1h_return_pct=0.005,
        atr_14=Decimal("0.85"),
        bid_ask_spread=Decimal("0.01"),
        proposed_direction=SignalDirection.LONG,
    )
    assert anomaly.venue == VenueType.HYPERLIQUID
    assert anomaly.proposed_direction == SignalDirection.LONG

    with pytest.raises(ValidationError):
        anomaly.current_price = Decimal("30.00")  # type: ignore[misc]

    verification = AIVerificationResultDTO(
        anomaly_id="anom-hl-001",
        primary_catalyst_summary="Mainnet upgrade announced 30 minutes ago",
        source_timestamps_verified=True,
        bull_thesis_score=88,
        red_team_flaws_detected=["Minor short-term funding uptick"],
        red_team_veto=False,
        red_team_penalty=6,
        estimated_win_probability=0.72,
        final_confidence_score=82,
    )
    assert verification.final_confidence_score == 82

    with pytest.raises(ValidationError):
        AIVerificationResultDTO(
            anomaly_id="anom-hl-001",
            primary_catalyst_summary="Invalid score",
            source_timestamps_verified=True,
            bull_thesis_score=120,
            red_team_flaws_detected=[],
            red_team_veto=False,
            red_team_penalty=0,
            estimated_win_probability=0.5,
            final_confidence_score=100,
        )

    order = ApprovedOrderDTO(
        order_id="ord-001",
        anomaly_id="anom-hl-001",
        venue=VenueType.HYPERLIQUID,
        symbol_or_market_id="HYPE",
        direction=SignalDirection.LONG,
        entry_price_limit=Decimal("25.50"),
        stop_loss_price=Decimal("23.97"),
        take_profit_price=Decimal("30.09"),
        position_size_usd=Decimal("3333.33"),
        position_size_units=Decimal("130.72"),
        risk_amount_usd=Decimal("200.00"),
        expected_value_ratio=2.16,
    )
    assert order.position_size_usd == Decimal("3333.33")


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.execution_mode == ExecutionMode.PAPER
    assert settings.xai_model == "grok-4.7"
    assert settings.gemini_decision_model == "gemini-decision-1"
    assert settings.paper_initial_equity_usd == Decimal("100.00")
    assert settings.hl_taker_fee_bps == Decimal("3.5")
    assert settings.hl_min_order_usd == Decimal("10.00")
    assert settings.polymarket_min_shares == Decimal("5.0")
    assert settings.hyperliquid_allocation_pct == pytest.approx(0.70)
    assert settings.polymarket_allocation_pct == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_sqlite_wal_and_repositories(tmp_path: Path) -> None:
    db_file = tmp_path / "test_bolt.db"
    client = SQLiteClient(str(db_file))
    await client.initialize()

    try:
        journal_mode = await client.get_journal_mode()
        assert journal_mode == "wal"

        oi_repo = OISnapshotRepository(client)
        t0 = 1_760_000_000_000
        t_minus_2h = t0 - 2 * 3_600_000
        t_minus_1h = t0 - 3_600_000

        await oi_repo.insert_snapshots_bulk(
            [
                OISnapshotDTO(
                    coin="HYPE",
                    timestamp_epoch_ms=t_minus_2h,
                    open_interest=900.0,
                    mark_px=22.0,
                ),
                OISnapshotDTO(
                    coin="HYPE",
                    timestamp_epoch_ms=t_minus_1h,
                    open_interest=1000.0,
                    mark_px=24.0,
                ),
            ]
        )

        delta_1h = await oi_repo.calculate_oi_delta_1h_pct(
            coin="HYPE",
            current_oi=1080.0,
            current_epoch_ms=t0,
        )
        assert delta_1h is not None
        assert delta_1h == pytest.approx(0.08)

        pruned = await oi_repo.prune_old_snapshots(older_than_epoch_ms=t_minus_1h)
        assert pruned == 1

        anomaly_repo = AnomalyRepository(client)
        now = datetime.now(timezone.utc)
        anomaly = MarketAnomalyDTO(
            anomaly_id="anom-pm-001",
            timestamp_utc=now,
            venue=VenueType.POLYMARKET,
            symbol_or_market_id="mkt-100",
            asset_name_or_question="Will Fed cut rates this meeting?",
            target_token_id="tok-yes-100",
            current_price=Decimal("0.45"),
            rvol_ratio=2.8,
            hours_to_resolution=24.0,
            bid_ask_spread=Decimal("0.02"),
            proposed_direction=SignalDirection.BUY_YES,
        )
        await anomaly_repo.save_anomaly(anomaly, passed_gate2=False)
        await anomaly_repo.mark_passed_gate2("anom-pm-001", passed=True)

        loaded_anomaly = await anomaly_repo.get_anomaly("anom-pm-001")
        assert loaded_anomaly is not None
        assert loaded_anomaly.asset_name_or_question == "Will Fed cut rates this meeting?"

        ai_repo = AIVerificationRepository(client)
        verif = AIVerificationResultDTO(
            anomaly_id="anom-pm-001",
            primary_catalyst_summary="FOMC statement leaked early",
            source_timestamps_verified=True,
            bull_thesis_score=85,
            red_team_flaws_detected=["Low liquidity on NO side"],
            red_team_veto=False,
            red_team_penalty=5,
            estimated_win_probability=0.65,
            final_confidence_score=80,
        )
        await ai_repo.save_verification(verif, verif.model_dump_json())
        loaded_verif = await ai_repo.get_verification("anom-pm-001")
        assert loaded_verif is not None
        assert loaded_verif.final_confidence_score == 80
        assert loaded_verif.red_team_flaws_detected == ["Low liquidity on NO side"]

        trade_repo = TradeRepository(client)
        trade = TradeRecordDTO(
            order_id="ord-pm-001",
            anomaly_id="anom-pm-001",
            venue=VenueType.POLYMARKET,
            symbol_or_market_id="mkt-100",
            execution_mode=ExecutionMode.PAPER,
            direction=SignalDirection.BUY_YES,
            status=OrderStatus.OPEN,
            entry_price=Decimal("0.45"),
            stop_loss_price=Decimal("0.30"),
            take_profit_price=Decimal("0.75"),
            position_size_usd=Decimal("500.00"),
            position_size_units=Decimal("1111.11"),
            opened_at_utc=now,
        )
        await trade_repo.create_trade(trade)
        open_trades = await trade_repo.list_open_trades()
        assert len(open_trades) == 1

        await trade_repo.update_excursions("ord-pm-001", mfe_pct=12.5, mae_pct=2.1)
        await trade_repo.close_trade(
            order_id="ord-pm-001",
            status=OrderStatus.CLOSED_TP,
            exit_price=Decimal("0.75"),
            realized_pnl_usd=Decimal("333.33"),
            closed_at_utc_iso=now.isoformat(),
            fees_paid_usd=Decimal("0.35"),
            slippage_est_usd=Decimal("0.15"),
            close_reason="TAKE_PROFIT_HIT",
        )
        closed_trade = await trade_repo.get_trade("ord-pm-001")
        assert closed_trade is not None
        assert closed_trade.max_favorable_excursion_pct == pytest.approx(12.5)
        assert closed_trade.max_adverse_excursion_pct == pytest.approx(2.1)
        assert closed_trade.fees_paid_usd == Decimal("0.35")
        assert closed_trade.close_reason == "TAKE_PROFIT_HIT"

        ledger_repo = AccountLedgerRepository(client)
        ledger0 = await ledger_repo.initialize_ledger(Decimal("100.00"), now_utc=now)
        assert ledger0.equity_usd == Decimal("100.00")
        ledger1 = await ledger_repo.lock_margin_and_deduct_entry_fee(
            margin_to_lock_usd=Decimal("25.00"),
            entry_fee_usd=Decimal("0.04"),
            now_utc=now,
        )
        assert ledger1.equity_usd == Decimal("99.96")
        assert ledger1.locked_margin_usd == Decimal("25.00")
        ledger2 = await ledger_repo.release_margin_and_settle_pnl(
            margin_unlocked_usd=Decimal("25.00"),
            net_realized_pnl_usd=Decimal("4.92"),
            exit_fee_usd=Decimal("0.04"),
            entry_fee_already_deducted_usd=Decimal("0.04"),
            now_utc=now,
        )
        assert ledger2.locked_margin_usd == Decimal("0.00")
        assert ledger2.equity_usd == Decimal("104.92")
        assert ledger2.total_fees_paid_usd == Decimal("0.08")
        pnl_24h = await trade_repo.get_rolling_24h_realized_pnl(
            since_utc_iso=(now.replace(year=now.year - 1)).isoformat()
        )
        assert pnl_24h == Decimal("333.33")

        brier_repo = BrierRepository(client)
        await brier_repo.record_prediction(
            BrierTrackingDTO(
                prediction_id="pred-001",
                anomaly_id="anom-pm-001",
                predicted_prob=0.80,
                recorded_at_utc=now,
            )
        )
        resolved = await brier_repo.resolve_prediction("pred-001", actual_outcome=1)
        assert resolved is not None
        assert resolved.brier_score_component == pytest.approx(0.04)
        mean_brier = await brier_repo.get_mean_brier_score()
        assert mean_brier == pytest.approx(0.04)
    finally:
        await client.close()
