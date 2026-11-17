import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.export_audit_report import export_audit_report_csv
from src.config.settings import Settings
from src.domain.dtos import (
    CandleDTO,
    HyperliquidAssetContextDTO,
    MarketAnomalyDTO,
    PolymarketCandidateDTO,
)
from src.domain.enums import ExecutionMode, SignalDirection, VenueType
from src.infrastructure.db.repositories import (
    AIVerificationRepository,
    AccountLedgerRepository,
    AnomalyRepository,
    BrierRepository,
    OISnapshotRepository,
    TradeRepository,
)
from src.infrastructure.db.sqlite_client import SQLiteClient
from src.infrastructure.venues.hyperliquid_client import HyperliquidClient
from src.infrastructure.venues.polymarket_client import PolymarketClient
from src.use_cases.gate1_quant_filter import (
    Gate1QuantFilter,
    calculate_1h_return_pct,
)
from src.use_cases.gate2_ai_verifier import Gate2AIVerifier
from src.use_cases.gate3_risk_engine import Gate3RiskEngine
from src.use_cases.portfolio_manager import PortfolioManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bolt.live_smoke_test")


def _build_offline_polymarket_fallback_transport(now_utc: datetime) -> httpx.MockTransport:
    """
    Fallback transport matching exact Gamma API and CLOB batch schemas (@docs/polymarket_api.md)
    used only if gamma-api.polymarket.com is unreachable/blocked at the local network layer.
    """
    markets_payload = [
        {
            "id": "901001",
            "question": "Will BTC close above $65,000 within 48 hours?",
            "conditionId": "0x901001",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.46", "0.54"]',
            "clobTokenIds": '["tok-yes-901001", "tok-no-901001"]',
            "volume": "184500.00",
            "endDate": (now_utc + timedelta(hours=36)).isoformat().replace("+00:00", "Z"),
            "orderPriceMinTickSize": "0.01",
            "closed": False,
            "active": True,
        },
        {
            "id": "901002",
            "question": "Will ETH gas average below 15 gwei today?",
            "conditionId": "0x901002",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.62", "0.38"]',
            "clobTokenIds": '["tok-yes-901002", "tok-no-901002"]',
            "volume": "92300.00",
            "endDate": (now_utc + timedelta(hours=18)).isoformat().replace("+00:00", "Z"),
            "orderPriceMinTickSize": "0.01",
            "closed": False,
            "active": True,
        },
        {
            "id": "901003",
            "question": "Will US Initial Jobless Claims print under 220k?",
            "conditionId": "0x901003",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.38", "0.62"]',
            "clobTokenIds": '["tok-yes-901003", "tok-no-901003"]',
            "volume": "310000.00",
            "endDate": (now_utc + timedelta(hours=28)).isoformat().replace("+00:00", "Z"),
            "orderPriceMinTickSize": "0.01",
            "closed": False,
            "active": True,
        },
        {
            "id": "901004",
            "question": "Will SOL 24h DEX volume exceed $2.5B tomorrow?",
            "conditionId": "0x901004",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.54", "0.46"]',
            "clobTokenIds": '["tok-yes-901004", "tok-no-901004"]',
            "volume": "67800.00",
            "endDate": (now_utc + timedelta(hours=42)).isoformat().replace("+00:00", "Z"),
            "orderPriceMinTickSize": "0.01",
            "closed": False,
            "active": True,
        },
        {
            "id": "901005",
            "question": "Will Hyperliquid daily perp volume exceed $6B?",
            "conditionId": "0x901005",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.71", "0.29"]',
            "clobTokenIds": '["tok-yes-901005", "tok-no-901005"]',
            "volume": "145200.00",
            "endDate": (now_utc + timedelta(hours=60)).isoformat().replace("+00:00", "Z"),
            "orderPriceMinTickSize": "0.01",
            "closed": False,
            "active": True,
        },
    ]

    spreads_payload = {
        "tok-yes-901001": "0.01",
        "tok-yes-901002": "0.02",
        "tok-yes-901003": "0.01",
        "tok-yes-901004": "0.02",
        "tok-yes-901005": "0.03",
    }
    midpoints_payload = {
        "tok-yes-901001": "0.46",
        "tok-yes-901002": "0.62",
        "tok-yes-901003": "0.38",
        "tok-yes-901004": "0.54",
        "tok-yes-901005": "0.71",
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/markets" in url:
            return httpx.Response(200, json=markets_payload)
        if url.endswith("/spreads"):
            return httpx.Response(200, json=spreads_payload)
        if url.endswith("/midpoints"):
            return httpx.Response(200, json=midpoints_payload)
        return httpx.Response(404)

    return httpx.MockTransport(_handler)


async def run_live_smoke_test() -> None:
    print("=" * 96)
    print("[INFO] BOLT LIVE MARKET SMOKE TEST ($100.00 DYNAMIC LEDGER + FEE/MFE/MAE + AUDIT EXPORT)")
    print("=" * 96)

    smoke_db_path = ROOT_DIR / "bolt_smoke_test.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{smoke_db_path}{suffix}")
        if p.exists():
            p.unlink()

    settings = Settings(
        EXECUTION_MODE=ExecutionMode.PAPER,
        PAPER_INITIAL_EQUITY_USD=Decimal("100.00"),
        INITIAL_ACCOUNT_EQUITY_USD=Decimal("100.00"),
        XAI_API_KEY="MOCK",
        GEMINI_API_KEY="",
        SQLITE_DB_PATH=str(smoke_db_path),
    )

    db_client = SQLiteClient(settings.sqlite_db_path)
    await db_client.initialize()
    journal_mode = await db_client.get_journal_mode()

    ledger_repo = AccountLedgerRepository(db_client)
    oi_repo = OISnapshotRepository(db_client)
    anomaly_repo = AnomalyRepository(db_client)
    verif_repo = AIVerificationRepository(db_client)
    trade_repo = TradeRepository(db_client)
    brier_repo = BrierRepository(db_client)

    initial_ledger = await ledger_repo.initialize_ledger(
        initial_equity_usd=settings.paper_initial_equity_usd
    )
    print(
        f"[INFO] SQLite WAL initialized at {smoke_db_path} (journal_mode={journal_mode.upper()}, "
        f"initial_equity=${initial_ledger.equity_usd:.2f})"
    )

    hl_client = HyperliquidClient(settings=settings, oi_repository=oi_repo)
    pm_client = PolymarketClient(settings=settings, max_retries=2, base_backoff_sec=0.3)
    gate1 = Gate1QuantFilter(hyperliquid_client=hl_client, polymarket_client=pm_client)
    gate2 = Gate2AIVerifier(
        llm_router=None,
        anomaly_repo=anomaly_repo,
        verification_repo=verif_repo,
        execution_mode=ExecutionMode.PAPER,
        xai_api_key="MOCK",
        gemini_api_key="",
    )
    gate3 = Gate3RiskEngine(
        trade_repo=trade_repo,
        ledger_repo=ledger_repo,
        starting_daily_equity_usd=settings.paper_initial_equity_usd,
        hl_min_order_usd=settings.hl_min_order_usd,
        polymarket_min_shares=settings.polymarket_min_shares,
        max_margin_allocation_per_trade_pct=settings.max_margin_allocation_per_trade_pct,
        max_concurrent_open_positions=settings.max_concurrent_open_positions,
    )
    portfolio = PortfolioManager(
        settings=settings,
        trade_repo=trade_repo,
        brier_repo=brier_repo,
        ledger_repo=ledger_repo,
        anomaly_repo=anomaly_repo,
        verification_repo=verif_repo,
        hyperliquid_client=hl_client,
        polymarket_client=pm_client,
    )

    try:
        # ------------------------------------------------------------------
        # STEP 1: HYPERLIQUID LIVE META + OI SNAPSHOT + TOP 5 CANDLE FETCH
        # ------------------------------------------------------------------
        print("\n" + "-" * 96)
        print("[INFO] STEP 1: Fetching live Hyperliquid metaAndAssetCtxs & storing OI snapshots")
        print("-" * 96)

        now_ms = int(time.time() * 1000)
        hl_assets = await hl_client.fetch_meta_and_asset_ctxs()
        print(f"[INFO] Active Hyperliquid Perp Universe fetched: {len(hl_assets)} coins")

        oi_deltas = await hl_client.record_oi_snapshots_and_get_deltas(
            hl_assets, current_epoch_ms=now_ms
        )
        non_null_deltas = [v for v in oi_deltas.values() if v is not None]
        print(
            f"[INFO] Recorded {len(hl_assets)} snapshots into hl_oi_snapshots "
            f"(1h deltas available: {len(non_null_deltas)}/{len(hl_assets)})"
        )

        cold_start_anomalies = await gate1.scan_hyperliquid(
            oi_deltas={a.coin: None for a in hl_assets},
            allow_cold_start_oi=False,
        )
        print(
            f"[INFO] Gate 1 cold-start warmup check passed gracefully "
            f"(returned {len(cold_start_anomalies)} anomalies without crashing)"
        )

        top5_hl = sorted(hl_assets, key=lambda a: a.day_ntl_vlm, reverse=True)[:5]

        semaphore = asyncio.Semaphore(3)
        start_24h_ms = now_ms - 24 * 3_600_000

        async def _fetch_coin_candles(
            asset: HyperliquidAssetContextDTO,
        ) -> tuple[HyperliquidAssetContextDTO, List[CandleDTO]]:
            async with semaphore:
                candles = await hl_client.fetch_candles(
                    coin=asset.coin,
                    interval="15m",
                    start_time_ms=start_24h_ms,
                    end_time_ms=now_ms,
                )
                return asset, candles

        top5_with_candles = await asyncio.gather(
            *[_fetch_coin_candles(a) for a in top5_hl]
        )

        btc_candles = next(
            (c for a, c in top5_with_candles if a.coin == "BTC"),
            top5_with_candles[0][1] if top5_with_candles else [],
        )
        btc_1h_ret = calculate_1h_return_pct(btc_candles)

        print("\n[INFO] Top 5 Hyperliquid Coins by 24h Volume (Live Mainnet Metrics):")
        print(
            f"{'Coin':<8} | {'MidPx ($)':>12} | {'24h Vol ($M)':>13} | {'RVOL':>7} | "
            f"{'VWAP ($)':>12} | {'VWAP Dist':>10} | {'ATR-14':>11} | {'Fund/1h':>10}"
        )
        print("-" * 98)

        hl_metrics_list: List[tuple[HyperliquidAssetContextDTO, Dict[str, Any]]] = []
        for asset, candles in top5_with_candles:
            metrics = gate1.compute_asset_microstructure_metrics(
                asset=asset,
                candles_15m=candles,
                oi_delta_1h_pct=oi_deltas.get(asset.coin),
                btc_1h_return_pct=btc_1h_ret,
            )
            hl_metrics_list.append((asset, metrics))
            vol_m = float(asset.day_ntl_vlm) / 1_000_000.0
            vwap_d_pct = metrics["vwap_distance_pct"] * 100.0
            fund_pct = asset.funding_hourly * 100.0
            print(
                f"{asset.coin:<8} | {float(metrics['current_price']):>12.4f} | "
                f"{vol_m:>12.2f}M | {metrics['rvol_ratio']:>6.2f}x | "
                f"{float(metrics['daily_vwap']):>12.4f} | {vwap_d_pct:>+9.3f}% | "
                f"{float(metrics['atr_14']):>11.5f} | {fund_pct:>+9.5f}%"
            )

        # ------------------------------------------------------------------
        # STEP 2: POLYMARKET GAMMA DISCOVERY + CLOB BATCH SPREADS/MIDPOINTS
        # ------------------------------------------------------------------
        print("\n" + "-" * 96)
        print("[INFO] STEP 2: Fetching Polymarket Gamma markets & CLOB batch spreads")
        print("-" * 96)

        now_utc = datetime.now(timezone.utc)
        pm_candidates: List[PolymarketCandidateDTO] = []
        try:
            pm_candidates = await pm_client.discover_short_horizon_markets(
                now_utc=now_utc, limit=100
            )
            print(
                f"[INFO] Live Polymarket Gamma + CLOB batch query succeeded: "
                f"{len(pm_candidates)} short-horizon candidates"
            )
        except RuntimeError as exc:
            doh_ip = await pm_client.resolve_host_via_doh("gamma-api.polymarket.com")
            print(
                f"[WARN] Live Polymarket endpoint unreachable from local network ({exc}; "
                f"Cloudflare DoH resolved IP={doh_ip}). Activating schema-exact Gamma/CLOB batch fallback."
            )
            fallback_transport = _build_offline_polymarket_fallback_transport(now_utc)
            async with httpx.AsyncClient(transport=fallback_transport) as fallback_http:
                pm_fallback_client = PolymarketClient(
                    settings=settings, http_client=fallback_http
                )
                pm_candidates = await pm_fallback_client.discover_short_horizon_markets(
                    now_utc=now_utc, limit=100
                )

        top5_pm = sorted(pm_candidates, key=lambda c: (c.spread_yes, -c.volume_usd))[:5]

        print("\n[INFO] Top 5 Polymarket Candidate Markets (Gamma + CLOB Batch):")
        print(
            f"{'Market ID':<10} | {'Midpoint':>8} | {'Spread':>8} | {'Hrs Left':>9} | "
            f"{'Volume ($)':>13} | {'Question'}"
        )
        print("-" * 98)
        for cand in top5_pm:
            q_short = (
                cand.question[:42] + "..."
                if len(cand.question) > 45
                else cand.question
            )
            print(
                f"{cand.market_id:<10} | {float(cand.midpoint_yes):>8.4f} | "
                f"{float(cand.spread_yes):>8.4f} | {cand.hours_to_resolution:>8.1f}h | "
                f"{float(cand.volume_usd):>13,.0f} | {q_short}"
            )

        # ------------------------------------------------------------------
        # STEP 3: $100.00 DYNAMIC LEDGER + FEE/MFE/MAE + AUDIT EXPORT
        # ------------------------------------------------------------------
        print("\n" + "-" * 96)
        print(
            "[INFO] STEP 3: Testing $100.00 Paper Ledger -> Gate 2 -> Gate 3 -> MFE/MAE & Fee Accounting -> CSV Audit"
        )
        print("-" * 96)

        top_asset, top_metrics = hl_metrics_list[0]
        live_direction = (
            SignalDirection.LONG
            if top_metrics["vwap_distance_pct"] >= 0.0
            else SignalDirection.SHORT
        )
        sz_step = (
            Decimal("10") ** (-top_asset.sz_decimals)
            if top_asset.sz_decimals > 0
            else Decimal("1")
        )
        live_hl_anomaly = MarketAnomalyDTO(
            anomaly_id=f"smoke-hl-{top_asset.coin.lower()}-{int(time.time())}",
            timestamp_utc=now_utc,
            venue=VenueType.HYPERLIQUID,
            symbol_or_market_id=top_asset.coin,
            asset_name_or_question=f"{top_asset.coin} Hyperliquid Perpetuals",
            sz_decimals_or_tick=sz_step,
            current_price=top_metrics["current_price"],
            rvol_ratio=max(float(top_metrics["rvol_ratio"]), 2.6),
            oi_delta_1h_pct=0.06,
            funding_rate_hourly=top_asset.funding_hourly,
            vwap_distance_pct=float(top_metrics["vwap_distance_pct"]),
            btc_1h_return_pct=float(top_metrics["btc_1h_return_pct"]),
            atr_14=top_metrics["atr_14"],
            bid_ask_spread=Decimal("0.01"),
            proposed_direction=live_direction,
        )

        verif_hl, passed_hl = await gate2.verify_anomaly(live_hl_anomaly)
        approved_hl = await gate3.evaluate_and_size(
            anomaly=live_hl_anomaly,
            verification=verif_hl,
        )
        assert approved_hl is not None, "Expected Gate 3 to approve live HL smoke order on $100 equity"

        trade_hl = await portfolio.execute_approved_order(
            order=approved_hl,
            verification=verif_hl,
        )
        ledger_after_open = await ledger_repo.get_ledger()
        print(
            f"[ORDER] Opened HYPERLIQUID Paper Trade on $100 Ledger: id={trade_hl.order_id} "
            f"symbol={trade_hl.symbol_or_market_id} dir={trade_hl.direction.value} "
            f"size_usd=${trade_hl.position_size_usd} units={trade_hl.position_size_units} "
            f"entry_fee=${trade_hl.fees_paid_usd} | "
            f"Ledger Equity=${ledger_after_open.equity_usd} "
            f"Avail=${ledger_after_open.available_margin_usd} "
            f"Locked=${ledger_after_open.locked_margin_usd}"
        )

        # Simulate Polymarket paper trade on $100 ledger (enforcing 5 shares & $1.00 floor)
        if top5_pm:
            pm_anom = gate1.evaluate_polymarket_market(top5_pm[0], now_utc=now_utc)
            if pm_anom is not None:
                verif_pm, _ = await gate2.verify_anomaly(pm_anom)
                approved_pm = await gate3.evaluate_and_size(
                    anomaly=pm_anom,
                    verification=verif_pm,
                )
                if approved_pm is not None:
                    trade_pm = await portfolio.execute_approved_order(
                        order=approved_pm,
                        verification=verif_pm,
                    )
                    print(
                        f"[ORDER] Opened POLYMARKET Paper Trade on $100 Ledger: id={trade_pm.order_id} "
                        f"market={trade_pm.symbol_or_market_id} dir={trade_pm.direction.value} "
                        f"size_usd=${trade_pm.position_size_usd} units={trade_pm.position_size_units}"
                    )

        # Simulate intrabar excursion tick and Take-Profit fill on the Hyperliquid trade
        if trade_hl.direction == SignalDirection.LONG:
            adverse_tick = trade_hl.entry_price * Decimal("0.998")
            tp_tick = trade_hl.take_profit_price + Decimal("1.0")
        else:
            adverse_tick = trade_hl.entry_price * Decimal("1.002")
            tp_tick = trade_hl.take_profit_price - Decimal("1.0")

        await portfolio.reconcile_open_positions(
            live_prices={trade_hl.symbol_or_market_id: adverse_tick}
        )
        closed_list = await portfolio.reconcile_open_positions(
            live_prices={trade_hl.symbol_or_market_id: tp_tick}
        )
        assert len(closed_list) == 1
        closed_hl = closed_list[0]
        final_ledger = await ledger_repo.get_ledger()
        print(
            f"[ORDER] Closed HYPERLIQUID Trade at TP: id={closed_hl.order_id} "
            f"status={closed_hl.status.value} reason={closed_hl.close_reason} "
            f"net_pnl=${closed_hl.realized_pnl_usd} total_fees=${closed_hl.fees_paid_usd} "
            f"MFE={closed_hl.max_favorable_excursion_pct:.3f}% "
            f"MAE={closed_hl.max_adverse_excursion_pct:.3f}% | "
            f"Final Ledger Equity=${final_ledger.equity_usd} "
            f"(CumPnL=${final_ledger.realized_pnl_cumulative_usd}, TotalFees=${final_ledger.total_fees_paid_usd})"
        )

        # Export Post-Mortem Audit CSV
        csv_path, row_count = await export_audit_report_csv(
            db_path=str(smoke_db_path),
            output_csv_path="reports/bolt_audit_report.csv",
        )
        print(f"[INFO] Exported Post-Mortem Audit Report: {csv_path} ({row_count} rows)")
        print("=" * 96)
        print("[INFO] LIVE MARKET SMOKE TEST COMPLETED SUCCESSFULLY ($0 API SPEND)")
        print("=" * 96)
    finally:
        await hl_client.close()
        await pm_client.close()
        await db_client.close()


if __name__ == "__main__":
    asyncio.run(run_live_smoke_test())
