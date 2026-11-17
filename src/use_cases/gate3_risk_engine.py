import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from typing import Optional

from src.domain.dtos import (
    AIVerificationResultDTO,
    ApprovedOrderDTO,
    CircuitBreakerStateDTO,
    MarketAnomalyDTO,
)
from src.domain.enums import SignalDirection, VenueType
from src.domain.interfaces import AccountLedgerRepositoryProtocol, TradeRepositoryProtocol
from src.use_cases.gate2_ai_verifier import Gate2AIVerifier

logger = logging.getLogger(__name__)


class Gate3RiskEngine:
    """
    Gate 3 Pure Python Mathematical Risk Engine & Automated Circuit Breaker.
    Strictly implements Section 6.4 of @docs/blueprint.md plus exchange minimum
    order notional guardrails:
    - Hyperliquid: 2% equity risk at 1.8x ATR-14 stop distance, 1:3 R:R TP, 2.0x max leverage cap,
      $10.00 minimum notional floor (scales up only if risk at SL <= 3.0% of equity and margin suffices),
      and +1.5x stop-distance trailing stop to breakeven.
    - Polymarket: Symmetric BUY_YES / BUY_NO Quarter-Kelly sizing (min 0.12 edge, 5% max bankroll cap,
      minimum 5 shares and $1.00 notional floor).
    - Circuit Breaker: 3 consecutive closed losses OR <= -5.0% rolling 24h drawdown locks trading for 24h
      and cancels open entry orders.
    """

    RISK_PER_TRADE_PCT: Decimal = Decimal("0.02")
    MAX_FLOOR_SCALED_RISK_PCT: Decimal = Decimal("0.03")
    MAX_MARGIN_ALLOCATION_PER_TRADE_PCT: Decimal = Decimal("0.35")
    MAX_CONCURRENT_OPEN_POSITIONS: int = 3
    ATR_STOP_MULTIPLIER: Decimal = Decimal("1.8")
    TP_R_MULTIPLIER: Decimal = Decimal("3.0")
    TRAILING_BE_MULTIPLIER: Decimal = Decimal("1.5")
    MAX_LEVERAGE_MULTIPLIER: Decimal = Decimal("2.0")

    MIN_POLYMARKET_EDGE: float = 0.12
    KELLY_FRACTION: Decimal = Decimal("0.25")
    MAX_POLYMARKET_BANKROLL_PCT: Decimal = Decimal("0.05")
    POLYMARKET_MIN_ORDER_USD: Decimal = Decimal("1.00")

    MAX_CONSECUTIVE_LOSSES: int = 3
    MAX_DAILY_DRAWDOWN_PCT: float = -0.05
    LOCKOUT_DURATION_HOURS: int = 24

    def __init__(
        self,
        trade_repo: Optional[TradeRepositoryProtocol] = None,
        ledger_repo: Optional[AccountLedgerRepositoryProtocol] = None,
        starting_daily_equity_usd: Decimal = Decimal("100.00"),
        hl_min_order_usd: Decimal = Decimal("10.00"),
        polymarket_min_shares: Decimal = Decimal("5.0"),
        max_margin_allocation_per_trade_pct: Decimal = Decimal("0.35"),
        max_concurrent_open_positions: int = 3,
    ) -> None:
        self._trade_repo = trade_repo
        self._ledger_repo = ledger_repo
        self._starting_daily_equity_usd = starting_daily_equity_usd
        self._hl_min_order_usd = hl_min_order_usd
        self._polymarket_min_shares = polymarket_min_shares
        self._max_margin_allocation_per_trade_pct = max_margin_allocation_per_trade_pct
        self._max_concurrent_open_positions = max_concurrent_open_positions
        self._circuit_breaker_until_utc: Optional[datetime] = None
        self._circuit_breaker_reason: str = ""

    def trigger_manual_halt(
        self,
        now_utc: Optional[datetime] = None,
        reason: str = "MANUAL_HALT_COMMAND",
    ) -> CircuitBreakerStateDTO:
        ref_now = now_utc or datetime.now(timezone.utc)
        self._circuit_breaker_until_utc = ref_now + timedelta(
            hours=self.LOCKOUT_DURATION_HOURS
        )
        self._circuit_breaker_reason = reason
        logger.warning("[VETO] Circuit breaker manually halted: %s", reason)
        return CircuitBreakerStateDTO(
            is_active=True,
            reason=reason,
            consecutive_losses=0,
            rolling_24h_pnl_usd=Decimal("0.0"),
            daily_drawdown_pct=0.0,
            triggered_at_utc=ref_now,
        )

    async def check_circuit_breaker(
        self,
        current_equity_usd: Optional[Decimal] = None,
        unrealized_pnl_usd: Decimal = Decimal("0.0"),
        now_utc: Optional[datetime] = None,
    ) -> CircuitBreakerStateDTO:
        """
        Evaluates Automated Circuit Breaker Rules (Section 6.4):
        - Rule 1 (Consecutive Losses): Last 3 closed trades resulted in net losses (< 0).
        - Rule 2 (Daily Drawdown Limit): Rolling 24h realized + unrealized PnL <= -5.0% of starting daily equity.
        """
        ref_now = now_utc or datetime.now(timezone.utc)
        base_equity = current_equity_usd or self._starting_daily_equity_usd

        if (
            self._circuit_breaker_until_utc is not None
            and ref_now < self._circuit_breaker_until_utc
        ):
            return CircuitBreakerStateDTO(
                is_active=True,
                reason=self._circuit_breaker_reason or "CIRCUIT_BREAKER_ACTIVE",
                consecutive_losses=0,
                rolling_24h_pnl_usd=Decimal("0.0"),
                daily_drawdown_pct=0.0,
                triggered_at_utc=ref_now,
            )

        if self._trade_repo is None:
            return CircuitBreakerStateDTO(
                is_active=False,
                reason="OK",
                consecutive_losses=0,
                rolling_24h_pnl_usd=unrealized_pnl_usd,
                daily_drawdown_pct=0.0,
                triggered_at_utc=None,
            )

        since_24h_iso = (ref_now - timedelta(hours=24)).isoformat()
        realized_24h = await self._trade_repo.get_rolling_24h_realized_pnl(since_24h_iso)
        total_24h_pnl = realized_24h + unrealized_pnl_usd

        drawdown_pct = (
            float(total_24h_pnl / self._starting_daily_equity_usd)
            if self._starting_daily_equity_usd > Decimal("0")
            else 0.0
        )

        recent_closed = await self._trade_repo.get_recent_closed_trades(
            limit=self.MAX_CONSECUTIVE_LOSSES
        )
        consecutive_losses = 0
        for t in recent_closed:
            if t.realized_pnl_usd < Decimal("0"):
                consecutive_losses += 1
            else:
                break

        # Rule 2 check first: Daily Drawdown <= -5.0% cancels all open orders and locks for 24h
        if drawdown_pct <= self.MAX_DAILY_DRAWDOWN_PCT:
            await self._trade_repo.cancel_all_open_trades(ref_now.isoformat())
            self._circuit_breaker_until_utc = ref_now + timedelta(
                hours=self.LOCKOUT_DURATION_HOURS
            )
            self._circuit_breaker_reason = (
                f"CIRCUIT_BREAKER_ACTIVE: Daily drawdown {drawdown_pct * 100.0:.2f}% <= -5.0%"
            )
            logger.warning("[VETO] %s", self._circuit_breaker_reason)
            return CircuitBreakerStateDTO(
                is_active=True,
                reason=self._circuit_breaker_reason,
                consecutive_losses=consecutive_losses,
                rolling_24h_pnl_usd=total_24h_pnl,
                daily_drawdown_pct=drawdown_pct,
                triggered_at_utc=ref_now,
            )

        # Rule 1 check: 3 consecutive closed losses locks for 24h
        if consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            self._circuit_breaker_until_utc = ref_now + timedelta(
                hours=self.LOCKOUT_DURATION_HOURS
            )
            self._circuit_breaker_reason = (
                f"CIRCUIT_BREAKER_ACTIVE: {consecutive_losses} consecutive losses"
            )
            logger.warning("[VETO] %s", self._circuit_breaker_reason)
            return CircuitBreakerStateDTO(
                is_active=True,
                reason=self._circuit_breaker_reason,
                consecutive_losses=consecutive_losses,
                rolling_24h_pnl_usd=total_24h_pnl,
                daily_drawdown_pct=drawdown_pct,
                triggered_at_utc=ref_now,
            )

        _ = base_equity
        return CircuitBreakerStateDTO(
            is_active=False,
            reason="OK",
            consecutive_losses=consecutive_losses,
            rolling_24h_pnl_usd=total_24h_pnl,
            daily_drawdown_pct=drawdown_pct,
            triggered_at_utc=None,
        )

    def size_hyperliquid_order(
        self,
        anomaly: MarketAnomalyDTO,
        verification: AIVerificationResultDTO,
        account_equity_usd: Decimal,
        available_margin_usd: Optional[Decimal] = None,
    ) -> Optional[ApprovedOrderDTO]:
        """
        Calculates exact Hyperliquid position size and stops per Section 6.4:
        - R_usd = 0.02 * E
        - Delta_SL = 1.8 * ATR_14
        - Q = R_usd / Delta_SL
        - Hard Leverage Cap: Q * EntryPrice <= 2.0 * E
        - Exchange Minimum Notional ($10.00): If 2% risk sizing yields notional < $10.00,
          scales up to $10.00 floor ONLY IF total risk at SL <= 3.0% of current equity
          and available margin suffices; otherwise rejects with [WARN].
        """
        if not Gate2AIVerifier.passes_gate2(verification):
            return None
        if account_equity_usd <= Decimal("0"):
            return None
        if anomaly.atr_14 is None or anomaly.atr_14 <= Decimal("0"):
            return None
        if anomaly.current_price <= Decimal("0"):
            return None

        avail_margin = (
            available_margin_usd
            if available_margin_usd is not None
            else account_equity_usd
        )
        entry_px = anomaly.current_price
        delta_sl = self.ATR_STOP_MULTIPLIER * anomaly.atr_14
        if delta_sl <= Decimal("0"):
            return None

        if anomaly.proposed_direction == SignalDirection.LONG:
            stop_px = entry_px - delta_sl
            tp_px = entry_px + (self.TP_R_MULTIPLIER * delta_sl)
            if stop_px <= Decimal("0"):
                return None
        elif anomaly.proposed_direction == SignalDirection.SHORT:
            stop_px = entry_px + delta_sl
            tp_px = entry_px - (self.TP_R_MULTIPLIER * delta_sl)
            if tp_px <= Decimal("0"):
                return None
        else:
            return None

        p_win = verification.estimated_win_probability
        ev_ratio = (p_win * 3.0) - ((1.0 - p_win) * 1.0)
        if ev_ratio <= 0.0:
            return None

        quantum = (
            anomaly.sz_decimals_or_tick
            if anomaly.sz_decimals_or_tick > Decimal("0")
            else Decimal("0.0001")
        )
        if quantum >= Decimal("1"):
            decimals = int(quantum)
            quantum = Decimal("10") ** (-decimals) if decimals > 0 else Decimal("1")

        risk_usd = self.RISK_PER_TRADE_PCT * account_equity_usd
        units_q = risk_usd / delta_sl
        notional_usd = units_q * entry_px

        max_margin_per_trade = (
            self._max_margin_allocation_per_trade_pct * account_equity_usd
        )
        effective_margin_cap = min(max_margin_per_trade, avail_margin)
        max_notional_usd = min(
            self.MAX_LEVERAGE_MULTIPLIER * account_equity_usd,
            self.MAX_LEVERAGE_MULTIPLIER * effective_margin_cap,
        )
        if notional_usd > max_notional_usd:
            notional_usd = max_notional_usd
            units_q = max_notional_usd / entry_px
            risk_usd = units_q * delta_sl

        units_rounded = units_q.quantize(quantum, rounding=ROUND_DOWN)
        notional_rounded = (units_rounded * entry_px).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        risk_rounded = (units_rounded * delta_sl).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )

        # Enforce $10.00 Hyperliquid minimum order notional floor
        if notional_rounded < self._hl_min_order_usd:
            min_units_needed = (self._hl_min_order_usd / entry_px).quantize(
                quantum, rounding=ROUND_CEILING
            )
            scaled_notional = (min_units_needed * entry_px).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            scaled_risk = (min_units_needed * delta_sl).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            max_allowed_risk = (
                self.MAX_FLOOR_SCALED_RISK_PCT * account_equity_usd
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            margin_needed = scaled_notional / self.MAX_LEVERAGE_MULTIPLIER

            if (
                scaled_notional >= self._hl_min_order_usd
                and scaled_risk <= max_allowed_risk
                and scaled_notional <= max_notional_usd
                and margin_needed <= avail_margin
            ):
                units_rounded = min_units_needed
                notional_rounded = scaled_notional
                risk_rounded = scaled_risk
            else:
                logger.warning(
                    "[WARN] Insufficient equity for exchange minimum notional on %s "
                    "(equity=$%s, min_notional=$%s, scaled_risk=$%s > max_3pct_risk=$%s)",
                    anomaly.symbol_or_market_id,
                    account_equity_usd,
                    self._hl_min_order_usd,
                    scaled_risk,
                    max_allowed_risk,
                )
                return None

        if units_rounded <= Decimal("0"):
            return None

        return ApprovedOrderDTO(
            order_id=f"ord-hl-{uuid.uuid4().hex[:10]}",
            anomaly_id=anomaly.anomaly_id,
            venue=VenueType.HYPERLIQUID,
            symbol_or_market_id=anomaly.symbol_or_market_id,
            direction=anomaly.proposed_direction,
            entry_price_limit=entry_px,
            stop_loss_price=stop_px.quantize(Decimal("0.000001"), rounding=ROUND_DOWN),
            take_profit_price=tp_px.quantize(Decimal("0.000001"), rounding=ROUND_DOWN),
            position_size_usd=notional_rounded,
            position_size_units=units_rounded,
            risk_amount_usd=risk_rounded,
            expected_value_ratio=round(ev_ratio, 4),
            target_token_id=None,
            sz_decimals_or_tick=quantum,
            bid_ask_spread=anomaly.bid_ask_spread,
        )

    def size_polymarket_order(
        self,
        anomaly: MarketAnomalyDTO,
        verification: AIVerificationResultDTO,
        account_equity_usd: Decimal,
        available_margin_usd: Optional[Decimal] = None,
    ) -> Optional[ApprovedOrderDTO]:
        """
        Calculates dual-sided (`BUY_YES` vs `BUY_NO`) Quarter-Kelly size per Section 6.4,
        enforcing Polymarket minimum order constraints (5.0 shares and $1.00 minimum notional).
        """
        if not Gate2AIVerifier.passes_gate2(verification):
            return None
        if account_equity_usd <= Decimal("0"):
            return None

        avail_margin = (
            available_margin_usd
            if available_margin_usd is not None
            else account_equity_usd
        )
        p_model = Decimal(f"{verification.estimated_win_probability:.6f}")
        p_yes = anomaly.current_price
        if not (Decimal("0") < p_yes < Decimal("1")):
            return None
        p_no = Decimal("1.0") - p_yes

        edge_yes = p_model - p_yes
        edge_no = (Decimal("1.0") - p_model) - p_no
        min_edge = Decimal(f"{self.MIN_POLYMARKET_EDGE:.4f}")

        if edge_yes >= min_edge:
            direction = SignalDirection.BUY_YES
            edge = edge_yes
            cost_c = p_yes
            target_token = anomaly.target_token_id or anomaly.symbol_or_market_id
        elif edge_no >= min_edge:
            direction = SignalDirection.BUY_NO
            edge = edge_no
            cost_c = p_no
            target_token = (
                anomaly.no_token_id
                or anomaly.target_token_id
                or anomaly.symbol_or_market_id
            )
        else:
            return None

        denom = Decimal("1.0") - cost_c
        if denom <= Decimal("0"):
            return None

        kelly_f = self.KELLY_FRACTION * (edge / denom)
        if kelly_f <= Decimal("0"):
            return None

        uncapped_usd = kelly_f * account_equity_usd
        max_cap_usd = min(
            self.MAX_POLYMARKET_BANKROLL_PCT * account_equity_usd,
            avail_margin,
        )
        position_usd = min(uncapped_usd, max_cap_usd).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        if position_usd <= Decimal("0"):
            logger.warning(
                "[WARN] Insufficient equity for exchange minimum notional on Polymarket %s",
                anomaly.symbol_or_market_id,
            )
            return None

        units = (position_usd / cost_c).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        # Enforce Polymarket minimum 5 shares and $1.00 notional floor
        min_notional_for_shares = (self._polymarket_min_shares * cost_c).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        required_floor_usd = max(self.POLYMARKET_MIN_ORDER_USD, min_notional_for_shares)

        if position_usd < required_floor_usd or units < self._polymarket_min_shares:
            max_allowed_floor_usd = min(
                self.MAX_FLOOR_SCALED_RISK_PCT * Decimal("2.0") * account_equity_usd,
                avail_margin,
            )
            if required_floor_usd <= max_allowed_floor_usd:
                position_usd = required_floor_usd
                units = max(
                    self._polymarket_min_shares,
                    (position_usd / cost_c).quantize(Decimal("0.01"), rounding=ROUND_CEILING),
                )
                position_usd = (units * cost_c).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            else:
                logger.warning(
                    "[WARN] Insufficient equity for exchange minimum notional on Polymarket %s "
                    "(equity=$%s, required_floor=$%s, min_shares=%s)",
                    anomaly.symbol_or_market_id,
                    account_equity_usd,
                    required_floor_usd,
                    self._polymarket_min_shares,
                )
                return None

        if units < self._polymarket_min_shares or position_usd < self.POLYMARKET_MIN_ORDER_USD:
            logger.warning(
                "[WARN] Insufficient equity for exchange minimum notional on Polymarket %s",
                anomaly.symbol_or_market_id,
            )
            return None

        stop_px = max(
            Decimal("0.01"),
            (cost_c * Decimal("0.50")).quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        )
        tp_px = min(
            Decimal("0.99"),
            (cost_c + (Decimal("2.0") * edge)).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            ),
        )
        risk_usd = ((cost_c - stop_px) * units).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        ev_ratio = float(edge / cost_c)

        return ApprovedOrderDTO(
            order_id=f"ord-pm-{uuid.uuid4().hex[:10]}",
            anomaly_id=anomaly.anomaly_id,
            venue=VenueType.POLYMARKET,
            symbol_or_market_id=anomaly.symbol_or_market_id,
            direction=direction,
            entry_price_limit=cost_c.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
            stop_loss_price=stop_px,
            take_profit_price=tp_px,
            position_size_usd=position_usd,
            position_size_units=units,
            risk_amount_usd=risk_usd,
            expected_value_ratio=round(ev_ratio, 4),
            target_token_id=target_token,
            sz_decimals_or_tick=anomaly.sz_decimals_or_tick,
            bid_ask_spread=anomaly.bid_ask_spread,
        )

    @classmethod
    def compute_trailing_stop_breakeven(
        cls,
        entry_price: Decimal,
        current_price: Decimal,
        current_stop_loss: Decimal,
        atr_14: Decimal,
        direction: SignalDirection,
        fee_rate: Decimal = Decimal("0.0007"),
    ) -> Optional[Decimal]:
        """
        Section 6.4 Trailing Stop rule:
        Once unrealized profit reaches +1.5 * Delta_SL (where Delta_SL = 1.8 * ATR_14),
        automatically move Stop-Loss to Breakeven (EntryPrice + fees for LONG; EntryPrice - fees for SHORT).
        """
        delta_sl = cls.ATR_STOP_MULTIPLIER * atr_14
        trigger_dist = cls.TRAILING_BE_MULTIPLIER * delta_sl
        fee_buffer = entry_price * fee_rate

        if direction == SignalDirection.LONG:
            if current_price - entry_price >= trigger_dist:
                be_stop = (entry_price + fee_buffer).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                if be_stop > current_stop_loss:
                    return be_stop
        elif direction == SignalDirection.SHORT:
            if entry_price - current_price >= trigger_dist:
                be_stop = (entry_price - fee_buffer).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                if be_stop < current_stop_loss:
                    return be_stop
        return None

    async def evaluate_and_size(
        self,
        anomaly: MarketAnomalyDTO,
        verification: AIVerificationResultDTO,
        account_equity_usd: Optional[Decimal] = None,
        available_margin_usd: Optional[Decimal] = None,
        unrealized_pnl_usd: Decimal = Decimal("0.0"),
        now_utc: Optional[datetime] = None,
    ) -> Optional[ApprovedOrderDTO]:
        """
        Full Gate 3 pipeline: reads dynamic account_ledger if available, checks Circuit Breaker,
        then sizes the order according to venue-specific mathematical guardrails.
        """
        equity = account_equity_usd
        avail_margin = available_margin_usd
        if self._ledger_repo is not None and (equity is None or avail_margin is None):
            ledger = await self._ledger_repo.get_ledger(
                default_initial_equity_usd=self._starting_daily_equity_usd
            )
            if equity is None:
                equity = ledger.equity_usd
            if avail_margin is None:
                avail_margin = ledger.available_margin_usd

        resolved_equity = equity if equity is not None else self._starting_daily_equity_usd
        resolved_margin = avail_margin if avail_margin is not None else resolved_equity

        if self._trade_repo is not None:
            open_trades = await self._trade_repo.list_open_trades()
            if len(open_trades) >= self._max_concurrent_open_positions:
                logger.info(
                    "[VETO] Gate 3 blocked order for %s: open positions (%d) >= max (%d)",
                    anomaly.symbol_or_market_id,
                    len(open_trades),
                    self._max_concurrent_open_positions,
                )
                return None

        cb_state = await self.check_circuit_breaker(
            current_equity_usd=resolved_equity,
            unrealized_pnl_usd=unrealized_pnl_usd,
            now_utc=now_utc,
        )
        if cb_state.is_active:
            logger.warning(
                "[VETO] Gate 3 blocked order for %s due to active circuit breaker: %s",
                anomaly.symbol_or_market_id,
                cb_state.reason,
            )
            return None

        if anomaly.venue == VenueType.HYPERLIQUID:
            return self.size_hyperliquid_order(
                anomaly=anomaly,
                verification=verification,
                account_equity_usd=resolved_equity,
                available_margin_usd=resolved_margin,
            )
        if anomaly.venue == VenueType.POLYMARKET:
            return self.size_polymarket_order(
                anomaly=anomaly,
                verification=verification,
                account_equity_usd=resolved_equity,
                available_margin_usd=resolved_margin,
            )
        return None
