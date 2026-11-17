import csv
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import httpx
import pytest

from main import BoltEngineOrchestrator
from src.config.settings import Settings
from src.domain.dtos import MarketAnomalyDTO
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType
from src.infrastructure.llm.router import XAIResponsesRouter


@pytest.mark.asyncio
async def test_full_paper_and_semi_auto_execution_pipeline(tmp_path: Path) -> None:
    db_path = tmp_path / "integration_bolt.db"
    csv_out_path = tmp_path / "reports" / "bolt_audit_report.csv"
    settings = Settings(
        EXECUTION_MODE=ExecutionMode.PAPER,
        PAPER_INITIAL_EQUITY_USD=Decimal("100.00"),
        INITIAL_ACCOUNT_EQUITY_USD=Decimal("100.00"),
        SQLITE_DB_PATH=str(db_path),
        XAI_API_KEY="test-xai-key",
        GEMINI_API_KEY="test-gemini-key",
    )

    orchestrator = BoltEngineOrchestrator(settings=settings)
    await orchestrator.initialize()

    init_ledger = await orchestrator.ledger_repo.get_ledger()
    assert init_ledger.equity_usd == Decimal("100.00")

    def llm_mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/v1/responses"):
            return httpx.Response(
                200,
                json={
                    "output_text": json.dumps(
                        {
                            "catalyst_found": True,
                            "primary_catalyst_summary": "Major L1 treasury burn announced 15m ago",
                            "bull_arguments": ["On-chain burn transaction verified"],
                            "bear_flaws_detected": ["Moderate funding rate"],
                            "audit_reasoning_trace": "Verified official protocol announcement and block explorer.",
                            "earliest_post_timestamp_utc": "2026-11-16T07:45:00Z",
                            "age_in_minutes": 15,
                            "verifiable_source_urls": ["https://x.com/official/status/999"],
                            "is_recycled_or_old_news": False,
                        }
                    )
                },
            )
        if url.endswith("/v1beta/decisions"):
            return httpx.Response(
                200,
                json={
                    "model": "gemini-decision-1",
                    "answers": {
                        "is_fresh_and_verifiable": {"probability": 0.92},
                        "is_bull_trap_or_manipulation": {"probability": 0.14},
                        "win_probability": {"probability": 0.75},
                        "thesis_quality_rubric": {"score": 92.0},
                    },
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(llm_mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_llm_http:
        orchestrator.llm_router = XAIResponsesRouter(
            settings=settings,
            http_client=mock_llm_http,
        )
        orchestrator.gate2._router = orchestrator.llm_router

        try:
            now_utc = datetime(2026, 11, 16, 8, 0, 0, tzinfo=timezone.utc)
            anomaly = MarketAnomalyDTO(
                anomaly_id="anom-int-hl-001",
                timestamp_utc=now_utc,
                venue=VenueType.HYPERLIQUID,
                symbol_or_market_id="HYPE",
                asset_name_or_question="HYPE Hyperliquid Perpetuals",
                sz_decimals_or_tick=Decimal("0.01"),
                current_price=Decimal("25.00"),
                rvol_ratio=3.5,
                oi_delta_1h_pct=0.09,
                funding_rate_hourly=0.00001,
                vwap_distance_pct=0.03,
                btc_1h_return_pct=0.01,
                atr_14=Decimal("1.00"),
                bid_ask_spread=Decimal("0.01"),
                proposed_direction=SignalDirection.LONG,
            )

            approved_order = await orchestrator.process_anomaly_through_funnel(anomaly)
            assert approved_order is not None
            assert approved_order.symbol_or_market_id == "HYPE"
            # Delta_SL = 1.8 * 1.00 = 1.80 -> SL = 23.20, TP = 25.00 + 5.40 = 30.40
            # Risk = 2% of $100.00 = $2.00 -> Q = 2.00 / 1.80 = 1.11 units -> Notional = $27.75 (>= $10.00 floor)
            assert approved_order.stop_loss_price == Decimal("23.200000")
            assert approved_order.take_profit_price == Decimal("30.400000")
            assert approved_order.position_size_usd == Decimal("27.75")

            open_trades = await orchestrator.trade_repo.list_open_trades()
            assert len(open_trades) == 1
            assert open_trades[0].fees_paid_usd > Decimal("0")

            # Step 0: Slight adverse excursion dip to $24.50 (-2.0% MAE)
            await orchestrator.portfolio.reconcile_open_positions(
                live_prices={"HYPE": Decimal("24.50")},
                atr_by_symbol={"HYPE": Decimal("1.00")},
                now_utc=now_utc + timedelta(minutes=5),
            )

            # Step 1: Price advances by +1.5 * Delta_SL (+2.70) to $27.80 (+11.2% MFE) -> moves SL to breakeven
            updated = await orchestrator.portfolio.reconcile_open_positions(
                live_prices={"HYPE": Decimal("27.80")},
                atr_by_symbol={"HYPE": Decimal("1.00")},
                now_utc=now_utc + timedelta(minutes=15),
            )
            assert len(updated) == 1
            assert updated[0].status == OrderStatus.OPEN
            assert updated[0].stop_loss_price > Decimal("25.00")
            assert updated[0].max_favorable_excursion_pct == pytest.approx(11.2)
            assert updated[0].max_adverse_excursion_pct == pytest.approx(2.0)

            # Step 2: Price reaches Take-Profit ($30.50 >= $30.40) -> closes trade, deducts fees/slippage, updates ledger & Brier
            closed = await orchestrator.portfolio.reconcile_open_positions(
                live_prices={"HYPE": Decimal("30.50")},
                atr_by_symbol={"HYPE": Decimal("1.00")},
                now_utc=now_utc + timedelta(minutes=30),
            )
            assert len(closed) == 1
            assert closed[0].status == OrderStatus.CLOSED_TP
            assert closed[0].close_reason == "TAKE_PROFIT_HIT"
            assert closed[0].realized_pnl_usd > Decimal("0")
            assert closed[0].fees_paid_usd > Decimal("0")
            assert closed[0].max_favorable_excursion_pct >= 21.6

            settled_ledger = await orchestrator.ledger_repo.get_ledger()
            assert settled_ledger.locked_margin_usd == Decimal("0.00")
            assert settled_ledger.equity_usd > Decimal("100.00")
            assert settled_ledger.total_fees_paid_usd > Decimal("0.00")

            mean_brier = await orchestrator.brier_repo.get_mean_brier_score()
            assert mean_brier is not None
            assert mean_brier == pytest.approx(0.0625)

            # Test Telegram C2 /status, /pnl, /export, /halt
            status_msg = await orchestrator.telegram_c2.handle_command(
                "/status", now_utc=now_utc
            )
            assert "[INFO] BOLT SYSTEM STATUS: ACTIVE" in status_msg
            assert "Equity USD: $" in status_msg

            pnl_msg = await orchestrator.telegram_c2.handle_command(
                "/pnl", now_utc=now_utc + timedelta(minutes=35)
            )
            assert "Mean Brier Score: 0.0625" in pnl_msg

            export_msg = await orchestrator.telegram_c2.handle_command(
                "/export",
                now_utc=now_utc + timedelta(minutes=36),
                export_csv_path=str(csv_out_path),
            )
            assert "[INFO] BOLT AUDIT REPORT EXPORTED" in export_msg
            assert csv_out_path.exists()

            with csv_out_path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == 1
            assert rows[0]["step2b_provider"] == "gemini-decision-1"
            assert rows[0]["is_fresh_and_verifiable_prob"] == "0.92"
            assert rows[0]["close_reason"] == "TAKE_PROFIT_HIT"

            halt_msg = await orchestrator.telegram_c2.handle_command(
                "/halt", now_utc=now_utc + timedelta(minutes=40)
            )
            assert "[VETO] EMERGENCY HALT ACTIVATED" in halt_msg
        finally:
            await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_pre_gate2_four_layer_cost_and_margin_shield(tmp_path: Path) -> None:
    """
    Verifies all 4 layers of the Pre-Gate-2 Cost & Margin Shield:
    1. Single trade margin never exceeds 35% of equity (~$35 locked on $100 equity, leaving ~$65 available).
    2. Layer 2: 180m per-symbol cooldown blocks repeated Gate 2 calls for the same symbol.
    3. Layer 3: Top-2 per scan cycle ranking caps concurrent Gate 1 candidates to the top 2 by RVOL * |OI_Delta|.
    4. Layer 4: Hard Daily AI Budget Cap (12/24h) blocks further paid AI calls once 12 evaluations are recorded.
    """
    db_path = tmp_path / "shield_bolt.db"
    settings = Settings(
        EXECUTION_MODE=ExecutionMode.PAPER,
        PAPER_INITIAL_EQUITY_USD=Decimal("100.00"),
        INITIAL_ACCOUNT_EQUITY_USD=Decimal("100.00"),
        MAX_MARGIN_ALLOCATION_PER_TRADE_PCT=Decimal("0.35"),
        MAX_CONCURRENT_OPEN_POSITIONS=3,
        ANOMALY_COOLDOWN_MINUTES=180,
        MAX_GATE2_CALLS_PER_SCAN=2,
        MAX_DAILY_AI_CALLS=12,
        SQLITE_DB_PATH=str(db_path),
        XAI_API_KEY="MOCK",
        GEMINI_API_KEY="",
    )

    orchestrator = BoltEngineOrchestrator(settings=settings)
    await orchestrator.initialize()

    try:
        now_utc = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)

        # 1. Verify single trade with tight ATR on $100 equity locks at most $35.00 margin ($70.00 notional)
        tight_btc = MarketAnomalyDTO(
            anomaly_id="anom-btc-tight",
            timestamp_utc=now_utc,
            venue=VenueType.HYPERLIQUID,
            symbol_or_market_id="BTC",
            asset_name_or_question="BTC Hyperliquid Perpetuals",
            sz_decimals_or_tick=Decimal("0.00001"),
            current_price=Decimal("65000.00"),
            rvol_ratio=3.5,
            oi_delta_1h_pct=0.08,
            funding_rate_hourly=0.00001,
            vwap_distance_pct=0.02,
            btc_1h_return_pct=0.01,
            atr_14=Decimal("200.00"),
            bid_ask_spread=Decimal("0.50"),
            proposed_direction=SignalDirection.LONG,
        )
        btc_order = await orchestrator.process_anomaly_through_funnel(tight_btc)
        assert btc_order is not None
        assert btc_order.position_size_usd <= Decimal("70.00")

        ledger_after_btc = await orchestrator.ledger_repo.get_ledger()
        assert ledger_after_btc.locked_margin_usd <= Decimal("35.00")
        assert ledger_after_btc.available_margin_usd >= Decimal("64.90")

        # 2. Layer 2: Same symbol ("BTC") 15 minutes later is blocked by 180m cooldown
        repeat_btc = tight_btc.model_copy(
            update={
                "anomaly_id": "anom-btc-repeat-15m",
                "timestamp_utc": now_utc + timedelta(minutes=15),
            }
        )
        shielded_repeat = await orchestrator.portfolio.filter_anomalies_pre_gate2(
            anomalies=[repeat_btc],
            risk_engine=orchestrator.gate3,
            now_utc=now_utc + timedelta(minutes=15),
        )
        assert len(shielded_repeat) == 0

        # 3. Layer 3: Pass 4 new symbols simultaneously -> only Top 2 by RVOL * |OI_Delta| survive
        candidates = [
            tight_btc.model_copy(
                update={
                    "anomaly_id": "c-eth",
                    "symbol_or_market_id": "ETH",
                    "rvol_ratio": 2.6,
                    "oi_delta_1h_pct": 0.05,  # score = 0.13
                }
            ),
            tight_btc.model_copy(
                update={
                    "anomaly_id": "c-sol",
                    "symbol_or_market_id": "SOL",
                    "rvol_ratio": 4.0,
                    "oi_delta_1h_pct": 0.10,  # score = 0.40 (Rank 1)
                }
            ),
            tight_btc.model_copy(
                update={
                    "anomaly_id": "c-sui",
                    "symbol_or_market_id": "SUI",
                    "rvol_ratio": 3.5,
                    "oi_delta_1h_pct": 0.08,  # score = 0.28 (Rank 2)
                }
            ),
            tight_btc.model_copy(
                update={
                    "anomaly_id": "c-avax",
                    "symbol_or_market_id": "AVAX",
                    "rvol_ratio": 2.8,
                    "oi_delta_1h_pct": 0.06,  # score = 0.168
                }
            ),
        ]
        top2 = await orchestrator.portfolio.filter_anomalies_pre_gate2(
            anomalies=candidates,
            risk_engine=orchestrator.gate3,
            now_utc=now_utc + timedelta(minutes=20),
        )
        assert [a.symbol_or_market_id for a in top2] == ["SOL", "SUI"]

        # 4. Layer 4: Record 12 paid AI verifications in rolling 24h -> 13th call is blocked
        for idx in range(12):
            paid_anom = tight_btc.model_copy(
                update={
                    "anomaly_id": f"paid-anom-{idx}",
                    "symbol_or_market_id": f"COIN{idx}",
                    "timestamp_utc": now_utc + timedelta(minutes=idx + 1),
                }
            )
            await orchestrator.anomaly_repo.save_anomaly(paid_anom, passed_gate2=False)
            verif_dto = orchestrator.gate2.build_fallback_quant_only_verification(paid_anom).model_copy(
                update={"primary_catalyst_summary": "Paid Gemini/Grok evaluation"}
            )
            await orchestrator.verification_repo.save_verification(
                verification=verif_dto,
                raw_json_response=json.dumps({"step2b_provider": "gemini-decision-1"}),
            )

        blocked_by_daily_cap = await orchestrator.portfolio.filter_anomalies_pre_gate2(
            anomalies=[
                tight_btc.model_copy(
                    update={
                        "anomaly_id": "c-link",
                        "symbol_or_market_id": "LINK",
                    }
                )
            ],
            risk_engine=orchestrator.gate3,
            now_utc=now_utc + timedelta(minutes=30),
        )
        assert len(blocked_by_daily_cap) == 0
    finally:
        await orchestrator.shutdown()


def test_clean_architecture_and_zero_emojis_policy() -> None:
    root = Path(__file__).resolve().parents[2]
    domain_dir = root / "src" / "domain"

    # 1. Clean Architecture: src/domain/ must have zero imports from src/infrastructure/
    for py_file in domain_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "src.infrastructure" not in content, (
            f"Clean Architecture violation in {py_file}"
        )

    # 2. Zero Emojis Policy across all Python files and docs
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002702-\U000027B0"
        "]+",
        flags=re.UNICODE,
    )
    all_checked_files = (
        list((root / "src").rglob("*.py"))
        + list((root / "tests").rglob("*.py"))
        + list((root / "scripts").rglob("*.py"))
        + [
            root / "main.py",
            root / "README.md",
            root / "docs" / "blueprint.md",
            root / "docs" / "gemini_decision_api.md",
        ]
    )
    todo_marker = "#" + " TODO"
    for checked_file in all_checked_files:
        text = checked_file.read_text(encoding="utf-8")
        assert emoji_pattern.search(text) is None, f"Emoji found in {checked_file}"
        if checked_file.suffix == ".py":
            assert todo_marker not in text, f"Placeholder marker found in {checked_file}"
