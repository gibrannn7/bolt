import argparse
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional

from src.config.settings import Settings, get_settings
from src.domain.dtos import AIVerificationResultDTO, ApprovedOrderDTO, MarketAnomalyDTO
from src.domain.enums import ExecutionMode, VenueType
from src.infrastructure.db.repositories import (
    AIVerificationRepository,
    AccountLedgerRepository,
    AnomalyRepository,
    BrierRepository,
    OISnapshotRepository,
    TradeRepository,
)
from src.infrastructure.db.sqlite_client import SQLiteClient
from src.infrastructure.llm.router import XAIResponsesRouter
from src.infrastructure.notifications.telegram_bot import TelegramBotC2
from src.infrastructure.venues.hyperliquid_client import HyperliquidClient
from src.infrastructure.venues.polymarket_client import PolymarketClient
from src.use_cases.gate1_quant_filter import Gate1QuantFilter
from src.use_cases.gate2_ai_verifier import Gate2AIVerifier
from src.use_cases.gate3_risk_engine import Gate3RiskEngine
from src.use_cases.portfolio_manager import PortfolioManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bolt.main")


class BoltEngineOrchestrator:
    """
    Master async orchestrator connecting the 3-Gate Quantitative & Adversarial AI Funnel:
    - Gate 1: Hyperliquid (5m scan) & Polymarket (10m scan) Deterministic Microstructure Filter
    - Gate 2: Hybrid xAI Grok-4.7 Live Search + Google Gemini Decision-1 Calibrated Judge
    - Gate 3: Volatility/Kelly Position Sizer, Exchange Floor Guard, & Automated 24h Circuit Breaker
    - Execution & Telemetry: Portfolio Manager (MFE/MAE + Fee Accounting) + SQLite WAL + Telegram C2
    """

    HYPERLIQUID_SCAN_INTERVAL_SEC: int = 300
    POLYMARKET_SCAN_INTERVAL_SEC: int = 600
    RECONCILE_INTERVAL_SEC: int = 60

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.db_client = SQLiteClient(self.settings.sqlite_db_path)

        self.ledger_repo = AccountLedgerRepository(self.db_client)
        self.oi_repo = OISnapshotRepository(self.db_client)
        self.anomaly_repo = AnomalyRepository(self.db_client)
        self.verification_repo = AIVerificationRepository(self.db_client)
        self.trade_repo = TradeRepository(self.db_client)
        self.brier_repo = BrierRepository(self.db_client)

        self.hl_client = HyperliquidClient(
            settings=self.settings,
            oi_repository=self.oi_repo,
        )
        self.pm_client = PolymarketClient(settings=self.settings)
        self.llm_router = XAIResponsesRouter(settings=self.settings)

        self.gate1 = Gate1QuantFilter(
            hyperliquid_client=self.hl_client,
            polymarket_client=self.pm_client,
        )
        self.gate2 = Gate2AIVerifier(
            llm_router=self.llm_router,
            anomaly_repo=self.anomaly_repo,
            verification_repo=self.verification_repo,
            execution_mode=self.settings.execution_mode,
            xai_api_key=self.settings.xai_api_key,
            gemini_api_key=self.settings.gemini_api_key,
        )
        self.gate3 = Gate3RiskEngine(
            trade_repo=self.trade_repo,
            ledger_repo=self.ledger_repo,
            starting_daily_equity_usd=self.settings.paper_initial_equity_usd,
            hl_min_order_usd=self.settings.hl_min_order_usd,
            polymarket_min_shares=self.settings.polymarket_min_shares,
            max_margin_allocation_per_trade_pct=self.settings.max_margin_allocation_per_trade_pct,
            max_concurrent_open_positions=self.settings.max_concurrent_open_positions,
        )
        self.portfolio = PortfolioManager(
            settings=self.settings,
            trade_repo=self.trade_repo,
            brier_repo=self.brier_repo,
            ledger_repo=self.ledger_repo,
            anomaly_repo=self.anomaly_repo,
            verification_repo=self.verification_repo,
            hyperliquid_client=self.hl_client,
            polymarket_client=self.pm_client,
        )

        async def _approve_callback(
            order: ApprovedOrderDTO,
            verification: AIVerificationResultDTO,
        ):
            return await self.portfolio.execute_approved_order(
                order=order,
                verification=verification,
            )

        self.telegram_c2 = TelegramBotC2(
            settings=self.settings,
            risk_engine=self.gate3,
            trade_repo=self.trade_repo,
            brier_repo=self.brier_repo,
            ledger_repo=self.ledger_repo,
            on_approve_order=_approve_callback,
        )

    async def initialize(self) -> None:
        await self.db_client.initialize()
        ledger = await self.ledger_repo.initialize_ledger(
            initial_equity_usd=self.settings.paper_initial_equity_usd
        )
        logger.info(
            "[INFO] BOLT Engine initialized (mode=%s, db=%s, equity=$%s, search_model=%s, judge_model=%s)",
            self.settings.execution_mode.value,
            self.settings.sqlite_db_path,
            ledger.equity_usd,
            self.settings.xai_model,
            self.settings.gemini_decision_model,
        )

    async def shutdown(self) -> None:
        await self.hl_client.close()
        await self.pm_client.close()
        await self.llm_router.close()
        await self.telegram_c2.close()
        await self.db_client.close()
        logger.info("[INFO] BOLT Engine shut down cleanly")

    def get_venue_equity_allocation(self, venue: VenueType) -> Decimal:
        total = self.settings.paper_initial_equity_usd
        if venue == VenueType.HYPERLIQUID:
            return total * Decimal(str(self.settings.hyperliquid_allocation_pct))
        return total * Decimal(str(self.settings.polymarket_allocation_pct))

    async def process_anomaly_through_funnel(
        self,
        anomaly: MarketAnomalyDTO,
        account_equity_usd: Optional[Decimal] = None,
        bypass_pre_gate2_shield: bool = False,
    ) -> Optional[ApprovedOrderDTO]:
        """
        Runs a Gate 1 MarketAnomalyDTO through the 4-Layer Pre-Gate-2 Cost & Margin Shield,
        Gate 2 (Grok-4.7 + Gemini Decision-1 Audit), and Gate 3 (Risk Sizing & Circuit Breaker),
        then dispatches to Execution/Telegram.
        """
        if not bypass_pre_gate2_shield:
            allowed = await self.portfolio.filter_anomalies_pre_gate2(
                anomalies=[anomaly],
                risk_engine=self.gate3,
                now_utc=anomaly.timestamp_utc,
            )
            if not allowed:
                return None

        verification, passed_gate2 = await self.gate2.verify_anomaly(anomaly)
        if not passed_gate2:
            return None

        approved_order = await self.gate3.evaluate_and_size(
            anomaly=anomaly,
            verification=verification,
            account_equity_usd=account_equity_usd,
        )
        if approved_order is None:
            return None

        if self.settings.execution_mode == ExecutionMode.SEMI_AUTO:
            await self.telegram_c2.queue_semi_auto_order(
                anomaly=anomaly,
                verification=verification,
                order=approved_order,
            )
        else:
            await self.portfolio.execute_approved_order(
                order=approved_order,
                verification=verification,
            )
            await self.telegram_c2.send_message(
                f"[ORDER] Executed {self.settings.execution_mode.value} trade: "
                f"{approved_order.order_id} {approved_order.venue.value} "
                f"{approved_order.symbol_or_market_id} {approved_order.direction.value} "
                f"size=${approved_order.position_size_usd}"
            )
        return approved_order

    async def process_anomalies_batch(
        self,
        anomalies: list[MarketAnomalyDTO],
    ) -> list[ApprovedOrderDTO]:
        """
        Applies the 4-Layer Pre-Gate-2 Shield (including Top-2 ranking per scan cycle)
        across a batch of Gate 1 anomalies and processes surviving candidates.
        """
        shielded = await self.portfolio.filter_anomalies_pre_gate2(
            anomalies=anomalies,
            risk_engine=self.gate3,
        )
        approved_orders: list[ApprovedOrderDTO] = []
        for anomaly in shielded:
            order = await self.process_anomaly_through_funnel(
                anomaly, bypass_pre_gate2_shield=False
            )
            if order is not None:
                approved_orders.append(order)
        return approved_orders

    async def run_single_scan_cycle(self) -> int:
        hl_anomalies = await self.gate1.scan_hyperliquid()
        pm_anomalies = await self.gate1.scan_polymarket()
        all_anomalies = hl_anomalies + pm_anomalies

        await self.process_anomalies_batch(all_anomalies)
        return len(all_anomalies)

    async def reconcile_positions_once(self) -> None:
        open_trades = await self.trade_repo.list_open_trades()
        if not open_trades:
            return

        live_prices: Dict[str, Decimal] = {}
        if any(t.venue == VenueType.HYPERLIQUID for t in open_trades):
            hl_ctxs = await self.hl_client.fetch_meta_and_asset_ctxs()
            for ctx in hl_ctxs:
                live_prices[ctx.coin] = (
                    ctx.mid_px if ctx.mid_px > Decimal("0") else ctx.mark_px
                )

        await self.portfolio.reconcile_open_positions(live_prices=live_prices)

    async def run_forever(self) -> None:
        await self.initialize()
        stop_event = asyncio.Event()

        async def _hl_loop() -> None:
            while not stop_event.is_set():
                try:
                    anomalies = await self.gate1.scan_hyperliquid()
                    await self.process_anomalies_batch(anomalies)
                except Exception as exc:
                    logger.error("[ERROR] Hyperliquid scan loop error: %s", exc)
                await asyncio.sleep(self.HYPERLIQUID_SCAN_INTERVAL_SEC)

        async def _pm_loop() -> None:
            while not stop_event.is_set():
                try:
                    anomalies = await self.gate1.scan_polymarket()
                    await self.process_anomalies_batch(anomalies)
                except Exception as exc:
                    logger.error("[ERROR] Polymarket scan loop error: %s", exc)
                await asyncio.sleep(self.POLYMARKET_SCAN_INTERVAL_SEC)

        async def _reconcile_loop() -> None:
            while not stop_event.is_set():
                try:
                    await self.reconcile_positions_once()
                except Exception as exc:
                    logger.error("[ERROR] Portfolio reconciliation error: %s", exc)
                await asyncio.sleep(self.RECONCILE_INTERVAL_SEC)

        try:
            await asyncio.gather(_hl_loop(), _pm_loop(), _reconcile_loop())
        finally:
            await self.shutdown()


async def async_main(run_once: bool = False) -> None:
    orchestrator = BoltEngineOrchestrator()
    await orchestrator.initialize()
    try:
        if run_once:
            count = await orchestrator.run_single_scan_cycle()
            logger.info("[INFO] Single scan cycle completed. Anomalies found: %d", count)
        else:
            await orchestrator.run_forever()
    finally:
        await orchestrator.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="BOLT Quantitative Trading Engine")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit",
    )
    args = parser.parse_args()
    asyncio.run(async_main(run_once=args.once))


if __name__ == "__main__":
    main()
