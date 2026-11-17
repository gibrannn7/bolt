import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

from src.config.settings import Settings
from src.domain.dtos import (
    AIVerificationResultDTO,
    ApprovedOrderDTO,
    BrierTrackingDTO,
    MarketAnomalyDTO,
    TradeRecordDTO,
)
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType
from src.domain.interfaces import (
    AIVerificationRepositoryProtocol,
    AccountLedgerRepositoryProtocol,
    AnomalyRepositoryProtocol,
    BrierRepositoryProtocol,
    HyperliquidVenueAdapter,
    PolymarketVenueAdapter,
    TradeRepositoryProtocol,
)
from src.use_cases.gate3_risk_engine import Gate3RiskEngine

logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Manages the 4-Layer Pre-Gate-2 Cost & Margin Shield, trade lifecycle,
    dynamic account_ledger updates, taker fee & half-spread slippage accounting,
    MFE/MAE excursion tracking, virtual SL/TP fills in PAPER mode, and Brier Score calibration.
    """

    def __init__(
        self,
        settings: Settings,
        trade_repo: TradeRepositoryProtocol,
        brier_repo: Optional[BrierRepositoryProtocol] = None,
        ledger_repo: Optional[AccountLedgerRepositoryProtocol] = None,
        anomaly_repo: Optional[AnomalyRepositoryProtocol] = None,
        verification_repo: Optional[AIVerificationRepositoryProtocol] = None,
        hyperliquid_client: Optional[HyperliquidVenueAdapter] = None,
        polymarket_client: Optional[PolymarketVenueAdapter] = None,
    ) -> None:
        self._settings = settings
        self._trade_repo = trade_repo
        self._brier_repo = brier_repo
        self._ledger_repo = ledger_repo
        self._anomaly_repo = anomaly_repo
        self._verification_repo = verification_repo
        self._hl_client = hyperliquid_client
        self._pm_client = polymarket_client

    @staticmethod
    def compute_candidate_priority_score(anomaly: MarketAnomalyDTO) -> float:
        """
        Layer 3 ranking metric: rvol_ratio * abs(oi_delta_1h_pct or 1.0).
        """
        oi_factor = (
            abs(anomaly.oi_delta_1h_pct)
            if anomaly.oi_delta_1h_pct is not None and anomaly.oi_delta_1h_pct != 0.0
            else 1.0
        )
        return float(anomaly.rvol_ratio) * float(oi_factor)

    async def filter_anomalies_pre_gate2(
        self,
        anomalies: Sequence[MarketAnomalyDTO],
        risk_engine: Optional[Gate3RiskEngine] = None,
        now_utc: Optional[datetime] = None,
    ) -> List[MarketAnomalyDTO]:
        """
        Enforces the 4-Layer Pre-Gate-2 Cost & Margin Shield in pure Python ($0 cost)
        before ANY Gate 1 anomaly is allowed to invoke Gate 2 AI models:
        1. Layer 1 — Pre-Gate-2 Margin & Circuit Breaker Guard
        2. Layer 2 — Per-Symbol Cooldown (ANOMALY_COOLDOWN_MINUTES = 180)
        3. Layer 3 — Top-K Ranking per Scan Cycle (MAX_GATE2_CALLS_PER_SCAN = 2)
        4. Layer 4 — Hard Daily AI Budget Cap (MAX_DAILY_AI_CALLS = 12)
        """
        if not anomalies:
            return []

        ref_now = now_utc or datetime.now(timezone.utc)

        # Layer 1: Margin, Position Slots, & Circuit Breaker Guard
        open_trades = await self._trade_repo.list_open_trades()
        cb_active = False
        if risk_engine is not None:
            cb_state = await risk_engine.check_circuit_breaker(now_utc=ref_now)
            cb_active = cb_state.is_active

        margin_insufficient = False
        if self._ledger_repo is not None:
            ledger = await self._ledger_repo.get_ledger(
                default_initial_equity_usd=self._settings.paper_initial_equity_usd
            )
            if ledger.available_margin_usd < self._settings.hl_min_order_usd:
                margin_insufficient = True

        if (
            cb_active
            or len(open_trades) >= self._settings.max_concurrent_open_positions
            or margin_insufficient
        ):
            logger.info(
                "[INFO] Pre-Gate-2 Shield: Skipping AI call (margin/position slots full or circuit breaker active)."
            )
            return []

        # Layer 2: Per-Symbol Cooldown (180 minutes)
        cooldown_cutoff_iso = (
            ref_now - timedelta(minutes=self._settings.anomaly_cooldown_minutes)
        ).isoformat()
        cooldown_passed: List[MarketAnomalyDTO] = []
        seen_symbols: set[str] = set()

        for anom in anomalies:
            sym = anom.symbol_or_market_id
            if sym in seen_symbols:
                continue
            if self._anomaly_repo is not None and hasattr(
                self._anomaly_repo, "has_recent_gate2_evaluation"
            ):
                recently_evaluated = await self._anomaly_repo.has_recent_gate2_evaluation(
                    symbol_or_market_id=sym,
                    since_utc_iso=cooldown_cutoff_iso,
                )
                if recently_evaluated:
                    logger.info(
                        "[INFO] Pre-Gate-2 Shield: Skipping %s (within %dm cooldown window).",
                        sym,
                        self._settings.anomaly_cooldown_minutes,
                    )
                    continue
            seen_symbols.add(sym)
            cooldown_passed.append(anom)

        if not cooldown_passed:
            return []

        # Layer 3: Top-K Ranking per Scan Cycle (MAX_GATE2_CALLS_PER_SCAN = 2)
        ranked = sorted(
            cooldown_passed,
            key=self.compute_candidate_priority_score,
            reverse=True,
        )
        top_k = ranked[: self._settings.max_gate2_calls_per_scan]

        # Layer 4: Hard Daily AI Budget Cap (MAX_DAILY_AI_CALLS = 12)
        if self._verification_repo is not None and hasattr(
            self._verification_repo, "count_rolling_24h_ai_calls"
        ):
            since_24h_iso = (ref_now - timedelta(hours=24)).isoformat()
            calls_last_24h = await self._verification_repo.count_rolling_24h_ai_calls(
                since_utc_iso=since_24h_iso,
                exclude_fallback_quant_only=True,
            )
            if calls_last_24h >= self._settings.max_daily_ai_calls:
                logger.warning(
                    "[WARN] Pre-Gate-2 Shield: Daily AI call cap (%d/24h) reached.",
                    self._settings.max_daily_ai_calls,
                )
                return []
            remaining_budget = self._settings.max_daily_ai_calls - calls_last_24h
            top_k = top_k[:remaining_budget]

        return top_k

    def compute_taker_fee_usd(
        self,
        venue: VenueType,
        notional_usd: Decimal,
    ) -> Decimal:
        """
        Computes venue taker fee in USD:
        - Hyperliquid: HL_TAKER_FEE_BPS (default 3.5 bps = 0.035% of notional)
        - Polymarket: 0 bps on standard CLOB limit orders
        """
        if venue == VenueType.HYPERLIQUID:
            fee_rate = self._settings.hl_taker_fee_bps / Decimal("10000")
            return (notional_usd * fee_rate).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        return Decimal("0.0000")

    @staticmethod
    def compute_half_spread_slippage_usd(
        bid_ask_spread: Decimal,
        units: Decimal,
        notional_usd: Decimal,
    ) -> Decimal:
        """
        Computes estimated half-spread execution slippage in USD.
        """
        if bid_ask_spread > Decimal("0"):
            return (Decimal("0.5") * bid_ask_spread * units).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        return (notional_usd * Decimal("0.0001")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def compute_locked_margin_usd(venue: VenueType, position_size_usd: Decimal) -> Decimal:
        if venue == VenueType.HYPERLIQUID:
            return (position_size_usd / Gate3RiskEngine.MAX_LEVERAGE_MULTIPLIER).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return position_size_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    async def execute_approved_order(
        self,
        order: ApprovedOrderDTO,
        verification: Optional[AIVerificationResultDTO] = None,
        execution_mode_override: Optional[ExecutionMode] = None,
        now_utc: Optional[datetime] = None,
    ) -> TradeRecordDTO:
        ref_now = now_utc or datetime.now(timezone.utc)
        mode = execution_mode_override or self._settings.execution_mode

        if order.venue == VenueType.HYPERLIQUID and self._hl_client is not None:
            await self._hl_client.place_order(order)
        elif order.venue == VenueType.POLYMARKET and self._pm_client is not None:
            await self._pm_client.place_order(order)

        entry_fee_usd = self.compute_taker_fee_usd(order.venue, order.position_size_usd)
        slippage_usd = self.compute_half_spread_slippage_usd(
            bid_ask_spread=order.bid_ask_spread,
            units=order.position_size_units,
            notional_usd=order.position_size_usd,
        )
        margin_to_lock = self.compute_locked_margin_usd(
            order.venue, order.position_size_usd
        )

        if self._ledger_repo is not None:
            await self._ledger_repo.lock_margin_and_deduct_entry_fee(
                margin_to_lock_usd=margin_to_lock,
                entry_fee_usd=entry_fee_usd,
                now_utc=ref_now,
            )

        trade_record = TradeRecordDTO(
            order_id=order.order_id,
            anomaly_id=order.anomaly_id,
            venue=order.venue,
            symbol_or_market_id=order.symbol_or_market_id,
            execution_mode=mode,
            direction=order.direction,
            status=OrderStatus.OPEN,
            entry_price=order.entry_price_limit,
            exit_price=None,
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            position_size_usd=order.position_size_usd,
            position_size_units=order.position_size_units,
            realized_pnl_usd=Decimal("0.0"),
            fees_paid_usd=entry_fee_usd,
            slippage_est_usd=slippage_usd,
            max_favorable_excursion_pct=0.0,
            max_adverse_excursion_pct=0.0,
            close_reason=None,
            opened_at_utc=ref_now,
            closed_at_utc=None,
        )
        await self._trade_repo.create_trade(trade_record)

        if self._brier_repo is not None and verification is not None:
            prob_for_direction = verification.estimated_win_probability
            if order.direction == SignalDirection.BUY_NO:
                prob_for_direction = 1.0 - verification.estimated_win_probability
            await self._brier_repo.record_prediction(
                BrierTrackingDTO(
                    prediction_id=f"brier-{order.order_id}",
                    anomaly_id=order.anomaly_id,
                    predicted_prob=max(0.0, min(1.0, prob_for_direction)),
                    actual_outcome=None,
                    brier_score_component=None,
                    recorded_at_utc=ref_now,
                )
            )

        logger.info(
            "[ORDER] Recorded open trade %s (%s %s) size_usd=%s entry=%s sl=%s tp=%s entry_fee=%s",
            trade_record.order_id,
            trade_record.venue.value,
            trade_record.symbol_or_market_id,
            trade_record.position_size_usd,
            trade_record.entry_price,
            trade_record.stop_loss_price,
            trade_record.take_profit_price,
            entry_fee_usd,
        )
        return trade_record

    @staticmethod
    def compute_position_pnl_usd(
        trade: TradeRecordDTO,
        mark_price: Decimal,
    ) -> Decimal:
        if trade.direction in (
            SignalDirection.LONG,
            SignalDirection.BUY_YES,
            SignalDirection.BUY_NO,
        ):
            raw_pnl = (mark_price - trade.entry_price) * trade.position_size_units
        elif trade.direction == SignalDirection.SHORT:
            raw_pnl = (trade.entry_price - mark_price) * trade.position_size_units
        else:
            raw_pnl = Decimal("0.0")
        return raw_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def compute_updated_excursions(
        trade: TradeRecordDTO,
        mark_price: Decimal,
    ) -> tuple[float, float]:
        """
        Computes updated (MFE %, MAE %) given current mark price.
        Both MFE and MAE are stored as non-negative percentages (>= 0.0).
        """
        if trade.entry_price <= Decimal("0"):
            return trade.max_favorable_excursion_pct, trade.max_adverse_excursion_pct

        if trade.direction in (
            SignalDirection.LONG,
            SignalDirection.BUY_YES,
            SignalDirection.BUY_NO,
        ):
            signed_pct = float((mark_price - trade.entry_price) / trade.entry_price) * 100.0
        elif trade.direction == SignalDirection.SHORT:
            signed_pct = float((trade.entry_price - mark_price) / trade.entry_price) * 100.0
        else:
            signed_pct = 0.0

        favorable = max(0.0, signed_pct)
        adverse = max(0.0, -signed_pct)
        new_mfe = round(max(trade.max_favorable_excursion_pct, favorable), 6)
        new_mae = round(max(trade.max_adverse_excursion_pct, adverse), 6)
        return new_mfe, new_mae

    async def calculate_unrealized_pnl(
        self,
        live_prices: Dict[str, Decimal],
    ) -> Decimal:
        open_trades = await self._trade_repo.list_open_trades()
        total_unrealized = Decimal("0.0")
        for trade in open_trades:
            px = live_prices.get(trade.symbol_or_market_id)
            if px is not None:
                total_unrealized += self.compute_position_pnl_usd(trade, px)
        return total_unrealized

    async def reconcile_open_positions(
        self,
        live_prices: Dict[str, Decimal],
        atr_by_symbol: Optional[Dict[str, Decimal]] = None,
        now_utc: Optional[datetime] = None,
    ) -> List[TradeRecordDTO]:
        """
        Monitors all OPEN positions against live prices:
        1. Updates MFE and MAE excursion percentages on every price tick.
        2. Updates Stop-Loss to Breakeven when unrealized profit reaches +1.5 * Delta_SL.
        3. Closes positions when Stop-Loss or Take-Profit is hit, deducts entry/exit taker fees
           and half-spread slippage from realized_pnl_usd, updates account_ledger, and resolves Brier Score.
        """
        ref_now = now_utc or datetime.now(timezone.utc)
        open_trades = await self._trade_repo.list_open_trades()
        closed_or_updated: List[TradeRecordDTO] = []

        for trade in open_trades:
            current_px = live_prices.get(trade.symbol_or_market_id)
            if current_px is None:
                continue

            new_mfe, new_mae = self.compute_updated_excursions(trade, current_px)
            if (
                new_mfe != trade.max_favorable_excursion_pct
                or new_mae != trade.max_adverse_excursion_pct
            ):
                await self._trade_repo.update_excursions(trade.order_id, new_mfe, new_mae)

            # Check TP / SL hits
            hit_status: Optional[OrderStatus] = None
            exit_px: Decimal = current_px

            if trade.direction in (
                SignalDirection.LONG,
                SignalDirection.BUY_YES,
                SignalDirection.BUY_NO,
            ):
                if current_px <= trade.stop_loss_price:
                    hit_status = OrderStatus.CLOSED_SL
                    exit_px = trade.stop_loss_price
                elif current_px >= trade.take_profit_price:
                    hit_status = OrderStatus.CLOSED_TP
                    exit_px = trade.take_profit_price
            elif trade.direction == SignalDirection.SHORT:
                if current_px >= trade.stop_loss_price:
                    hit_status = OrderStatus.CLOSED_SL
                    exit_px = trade.stop_loss_price
                elif current_px <= trade.take_profit_price:
                    hit_status = OrderStatus.CLOSED_TP
                    exit_px = trade.take_profit_price

            if hit_status is not None:
                gross_pnl = self.compute_position_pnl_usd(trade, exit_px)
                exit_notional = exit_px * trade.position_size_units
                exit_fee_usd = self.compute_taker_fee_usd(trade.venue, exit_notional)
                total_fees_usd = (trade.fees_paid_usd + exit_fee_usd).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                slippage_usd = trade.slippage_est_usd.quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                net_realized_pnl = (gross_pnl - total_fees_usd - slippage_usd).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                close_reason = (
                    "TAKE_PROFIT_HIT"
                    if hit_status == OrderStatus.CLOSED_TP
                    else "STOP_LOSS_HIT"
                )

                await self._trade_repo.close_trade(
                    order_id=trade.order_id,
                    status=hit_status,
                    exit_price=exit_px,
                    realized_pnl_usd=net_realized_pnl,
                    closed_at_utc_iso=ref_now.isoformat(),
                    fees_paid_usd=total_fees_usd,
                    slippage_est_usd=slippage_usd,
                    close_reason=close_reason,
                )

                if self._ledger_repo is not None:
                    margin_unlocked = self.compute_locked_margin_usd(
                        trade.venue, trade.position_size_usd
                    )
                    if hasattr(self._ledger_repo, "release_margin_and_settle_pnl"):
                        await self._ledger_repo.release_margin_and_settle_pnl(  # type: ignore[call-arg]
                            margin_unlocked_usd=margin_unlocked,
                            net_realized_pnl_usd=net_realized_pnl,
                            exit_fee_usd=exit_fee_usd,
                            entry_fee_already_deducted_usd=trade.fees_paid_usd,
                            now_utc=ref_now,
                        )

                if self._brier_repo is not None:
                    outcome = 1 if net_realized_pnl > Decimal("0") else 0
                    await self._brier_repo.resolve_prediction(
                        prediction_id=f"brier-{trade.order_id}",
                        actual_outcome=outcome,
                    )
                updated_trade = await self._trade_repo.get_trade(trade.order_id)
                if updated_trade is not None:
                    closed_or_updated.append(updated_trade)
                logger.info(
                    "[ORDER] Closed trade %s (%s) status=%s exit=%s net_pnl=%s fees=%s mfe=%.2f%% mae=%.2f%%",
                    trade.order_id,
                    trade.symbol_or_market_id,
                    hit_status.value,
                    exit_px,
                    net_realized_pnl,
                    total_fees_usd,
                    new_mfe,
                    new_mae,
                )
                continue

            # Check trailing stop to breakeven for Hyperliquid trades
            if trade.venue == VenueType.HYPERLIQUID:
                if atr_by_symbol and trade.symbol_or_market_id in atr_by_symbol:
                    atr_val = atr_by_symbol[trade.symbol_or_market_id]
                else:
                    initial_dist = abs(trade.entry_price - trade.stop_loss_price)
                    atr_val = initial_dist / Gate3RiskEngine.ATR_STOP_MULTIPLIER

                if atr_val > Decimal("0"):
                    new_sl = Gate3RiskEngine.compute_trailing_stop_breakeven(
                        entry_price=trade.entry_price,
                        current_price=current_px,
                        current_stop_loss=trade.stop_loss_price,
                        atr_14=atr_val,
                        direction=trade.direction,
                    )
                    if new_sl is not None:
                        await self._trade_repo.update_stop_loss(trade.order_id, new_sl)
                        updated_trade = await self._trade_repo.get_trade(trade.order_id)
                        if updated_trade is not None:
                            closed_or_updated.append(updated_trade)
                        logger.info(
                            "[ORDER] Trailing stop moved to breakeven for %s: new_sl=%s",
                            trade.order_id,
                            new_sl,
                        )

        return closed_or_updated
