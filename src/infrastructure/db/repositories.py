import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from src.domain.dtos import (
    AIVerificationResultDTO,
    AccountLedgerDTO,
    BrierTrackingDTO,
    MarketAnomalyDTO,
    OISnapshotDTO,
    TradeRecordDTO,
)
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType
from src.infrastructure.db.sqlite_client import SQLiteClient


class AccountLedgerRepository:
    """
    Repository for dynamic account equity, locked/available margin, cumulative realized PnL,
    and total taker fees paid in SQLite WAL (`account_ledger`).
    """

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def initialize_ledger(
        self,
        initial_equity_usd: Decimal = Decimal("100.00"),
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO:
        ref_now = now_utc or datetime.now(timezone.utc)
        eq_str = str(initial_equity_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        async with self._client.session() as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO account_ledger (
                    id,
                    equity_usd,
                    available_margin_usd,
                    locked_margin_usd,
                    realized_pnl_cumulative_usd,
                    total_fees_paid_usd,
                    updated_at_utc
                ) VALUES (1, ?, ?, '0.00', '0.00', '0.00', ?)
                """,
                (eq_str, eq_str, ref_now.isoformat()),
            )
            await conn.commit()
        return await self.get_ledger(default_initial_equity_usd=initial_equity_usd)

    async def get_ledger(
        self,
        default_initial_equity_usd: Decimal = Decimal("100.00"),
    ) -> AccountLedgerDTO:
        async with self._client.session() as conn:
            cursor = await conn.execute("SELECT * FROM account_ledger WHERE id = 1")
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return await self.initialize_ledger(initial_equity_usd=default_initial_equity_usd)

        r = dict(row)
        updated_dt = datetime.fromisoformat(str(r["updated_at_utc"]))
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        return AccountLedgerDTO(
            equity_usd=Decimal(str(r["equity_usd"])),
            available_margin_usd=Decimal(str(r["available_margin_usd"])),
            locked_margin_usd=Decimal(str(r["locked_margin_usd"])),
            realized_pnl_cumulative_usd=Decimal(str(r["realized_pnl_cumulative_usd"])),
            total_fees_paid_usd=Decimal(str(r["total_fees_paid_usd"])),
            updated_at_utc=updated_dt,
        )

    async def lock_margin_and_deduct_entry_fee(
        self,
        margin_to_lock_usd: Decimal,
        entry_fee_usd: Decimal,
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO:
        ref_now = now_utc or datetime.now(timezone.utc)
        current = await self.get_ledger()

        new_equity = (current.equity_usd - entry_fee_usd).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_locked = (current.locked_margin_usd + margin_to_lock_usd).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_available = max(Decimal("0.00"), new_equity - new_locked).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_fees = (current.total_fees_paid_usd + entry_fee_usd).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        async with self._client.session() as conn:
            await conn.execute(
                """
                UPDATE account_ledger
                SET equity_usd = ?,
                    available_margin_usd = ?,
                    locked_margin_usd = ?,
                    total_fees_paid_usd = ?,
                    updated_at_utc = ?
                WHERE id = 1
                """,
                (
                    str(new_equity),
                    str(new_available),
                    str(new_locked),
                    str(new_fees),
                    ref_now.isoformat(),
                ),
            )
            await conn.commit()

        return AccountLedgerDTO(
            equity_usd=new_equity,
            available_margin_usd=new_available,
            locked_margin_usd=new_locked,
            realized_pnl_cumulative_usd=current.realized_pnl_cumulative_usd,
            total_fees_paid_usd=new_fees,
            updated_at_utc=ref_now,
        )

    async def release_margin_and_settle_pnl(
        self,
        margin_unlocked_usd: Decimal,
        net_realized_pnl_usd: Decimal,
        exit_fee_usd: Decimal,
        entry_fee_already_deducted_usd: Decimal = Decimal("0.00"),
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO:
        ref_now = now_utc or datetime.now(timezone.utc)
        current = await self.get_ledger()

        # net_realized_pnl_usd already has entry_fee + exit_fee + slippage subtracted;
        # since entry_fee_already_deducted_usd was subtracted from equity at open,
        # add back entry_fee_already_deducted_usd before adding net_realized_pnl_usd.
        equity_delta = net_realized_pnl_usd + entry_fee_already_deducted_usd
        new_equity = (current.equity_usd + equity_delta).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_locked = max(
            Decimal("0.00"), current.locked_margin_usd - margin_unlocked_usd
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_available = max(Decimal("0.00"), new_equity - new_locked).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_cum_pnl = (
            current.realized_pnl_cumulative_usd + net_realized_pnl_usd
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_fees = (current.total_fees_paid_usd + exit_fee_usd).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        async with self._client.session() as conn:
            await conn.execute(
                """
                UPDATE account_ledger
                SET equity_usd = ?,
                    available_margin_usd = ?,
                    locked_margin_usd = ?,
                    realized_pnl_cumulative_usd = ?,
                    total_fees_paid_usd = ?,
                    updated_at_utc = ?
                WHERE id = 1
                """,
                (
                    str(new_equity),
                    str(new_available),
                    str(new_locked),
                    str(new_cum_pnl),
                    str(new_fees),
                    ref_now.isoformat(),
                ),
            )
            await conn.commit()

        return AccountLedgerDTO(
            equity_usd=new_equity,
            available_margin_usd=new_available,
            locked_margin_usd=new_locked,
            realized_pnl_cumulative_usd=new_cum_pnl,
            total_fees_paid_usd=new_fees,
            updated_at_utc=ref_now,
        )


class OISnapshotRepository:
    """Repository for Hyperliquid 5-minute local Open Interest snapshots and 1h delta math."""

    ONE_HOUR_MS: int = 3_600_000
    DEFAULT_RETENTION_MS: int = 24 * 3_600_000

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def insert_snapshot(self, snapshot: OISnapshotDTO) -> int:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO hl_oi_snapshots (coin, timestamp_epoch_ms, open_interest, mark_px)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot.coin,
                    snapshot.timestamp_epoch_ms,
                    snapshot.open_interest,
                    snapshot.mark_px,
                ),
            )
            await conn.commit()
            row_id = int(cursor.lastrowid or 0)
            await cursor.close()
            return row_id

    async def insert_snapshots_bulk(self, snapshots: List[OISnapshotDTO]) -> None:
        if not snapshots:
            return
        async with self._client.session() as conn:
            await conn.executemany(
                """
                INSERT INTO hl_oi_snapshots (coin, timestamp_epoch_ms, open_interest, mark_px)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (s.coin, s.timestamp_epoch_ms, s.open_interest, s.mark_px)
                    for s in snapshots
                ],
            )
            await conn.commit()

    async def get_snapshot_1h_ago(
        self,
        coin: str,
        current_epoch_ms: int,
        tolerance_ms: int = 900_000,
    ) -> Optional[OISnapshotDTO]:
        target_ms = current_epoch_ms - self.ONE_HOUR_MS
        min_ms = target_ms - tolerance_ms
        max_ms = target_ms + tolerance_ms
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                SELECT id, coin, timestamp_epoch_ms, open_interest, mark_px
                FROM hl_oi_snapshots
                WHERE coin = ?
                  AND timestamp_epoch_ms BETWEEN ? AND ?
                ORDER BY ABS(timestamp_epoch_ms - ?) ASC
                LIMIT 1
                """,
                (coin, min_ms, max_ms, target_ms),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            return OISnapshotDTO(
                id=int(row["id"]),
                coin=str(row["coin"]),
                timestamp_epoch_ms=int(row["timestamp_epoch_ms"]),
                open_interest=float(row["open_interest"]),
                mark_px=float(row["mark_px"]),
            )

    async def calculate_oi_delta_1h_pct(
        self,
        coin: str,
        current_oi: float,
        current_epoch_ms: int,
        tolerance_ms: int = 900_000,
    ) -> Optional[float]:
        """
        Calculates 1h Open Interest relative change:
        (OI_now - OI_1h_ago) / OI_1h_ago.
        Returns e.g. 0.05 for a +5.0% increase, matching Section 6.1 of blueprint.md.
        """
        snapshot_1h = await self.get_snapshot_1h_ago(
            coin=coin,
            current_epoch_ms=current_epoch_ms,
            tolerance_ms=tolerance_ms,
        )
        if snapshot_1h is None or snapshot_1h.open_interest <= 0.0:
            return None
        return (current_oi - snapshot_1h.open_interest) / snapshot_1h.open_interest

    async def prune_old_snapshots(self, older_than_epoch_ms: int) -> int:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "DELETE FROM hl_oi_snapshots WHERE timestamp_epoch_ms < ?",
                (older_than_epoch_ms,),
            )
            await conn.commit()
            deleted = int(cursor.rowcount or 0)
            await cursor.close()
            return deleted

    async def retain_recent_window(
        self,
        current_epoch_ms: int,
        retention_ms: int = DEFAULT_RETENTION_MS,
    ) -> int:
        cutoff = current_epoch_ms - retention_ms
        return await self.prune_old_snapshots(cutoff)


class AnomalyRepository:
    """Repository for Gate 1 detected MarketAnomalyDTO records."""

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def save_anomaly(
        self,
        anomaly: MarketAnomalyDTO,
        passed_gate2: bool = False,
    ) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO anomalies (
                    anomaly_id,
                    timestamp_utc,
                    venue,
                    symbol_or_market_id,
                    asset_name_or_question,
                    target_token_id,
                    proposed_direction,
                    current_price,
                    rvol_ratio,
                    oi_delta_1h_pct,
                    funding_rate_hourly,
                    passed_gate2
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anomaly.anomaly_id,
                    anomaly.timestamp_utc.isoformat(),
                    anomaly.venue.value,
                    anomaly.symbol_or_market_id,
                    anomaly.asset_name_or_question,
                    anomaly.target_token_id,
                    anomaly.proposed_direction.value,
                    str(anomaly.current_price),
                    float(anomaly.rvol_ratio),
                    anomaly.oi_delta_1h_pct,
                    anomaly.funding_rate_hourly,
                    1 if passed_gate2 else 0,
                ),
            )
            await conn.commit()

    async def mark_passed_gate2(self, anomaly_id: str, passed: bool = True) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                "UPDATE anomalies SET passed_gate2 = ? WHERE anomaly_id = ?",
                (1 if passed else 0, anomaly_id),
            )
            await conn.commit()

    async def get_anomaly(self, anomaly_id: str) -> Optional[MarketAnomalyDTO]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "SELECT * FROM anomalies WHERE anomaly_id = ?",
                (anomaly_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            return self._row_to_dto(row)

    async def list_recent_anomalies(self, limit: int = 50) -> List[MarketAnomalyDTO]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "SELECT * FROM anomalies ORDER BY timestamp_utc DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return [self._row_to_dto(r) for r in rows]

    async def has_recent_gate2_evaluation(
        self,
        symbol_or_market_id: str,
        since_utc_iso: str,
    ) -> bool:
        """
        Checks if `symbol_or_market_id` has already been evaluated by Gate 2
        (recorded in anomalies + ai_verifications) at or after `since_utc_iso`.
        """
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                SELECT 1
                FROM anomalies a
                INNER JOIN ai_verifications v ON a.anomaly_id = v.anomaly_id
                WHERE a.symbol_or_market_id = ?
                  AND a.timestamp_utc >= ?
                LIMIT 1
                """,
                (symbol_or_market_id, since_utc_iso),
            )
            row = await cursor.fetchone()
            await cursor.close()
            return row is not None

    @staticmethod
    def _row_to_dto(row: object) -> MarketAnomalyDTO:
        r = dict(row)  # type: ignore[call-overload]
        ts = datetime.fromisoformat(str(r["timestamp_utc"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return MarketAnomalyDTO(
            anomaly_id=str(r["anomaly_id"]),
            timestamp_utc=ts,
            venue=VenueType(str(r["venue"])),
            symbol_or_market_id=str(r["symbol_or_market_id"]),
            asset_name_or_question=str(r["asset_name_or_question"]),
            target_token_id=str(r["target_token_id"]) if r["target_token_id"] is not None else None,
            current_price=Decimal(str(r["current_price"])),
            rvol_ratio=float(r["rvol_ratio"]),
            oi_delta_1h_pct=float(r["oi_delta_1h_pct"]) if r["oi_delta_1h_pct"] is not None else None,
            funding_rate_hourly=float(r["funding_rate_hourly"]) if r["funding_rate_hourly"] is not None else None,
            bid_ask_spread=Decimal("0.0"),
            proposed_direction=SignalDirection(str(r["proposed_direction"])),
        )


class AIVerificationRepository:
    """Repository for Gate 2 AIVerificationResultDTO records."""

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def save_verification(
        self,
        verification: AIVerificationResultDTO,
        raw_json_response: str,
    ) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO ai_verifications (
                    anomaly_id,
                    primary_catalyst_summary,
                    source_timestamps_verified,
                    bull_thesis_score,
                    red_team_veto,
                    red_team_penalty,
                    estimated_win_probability,
                    final_confidence_score,
                    raw_json_response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification.anomaly_id,
                    verification.primary_catalyst_summary,
                    1 if verification.source_timestamps_verified else 0,
                    verification.bull_thesis_score,
                    1 if verification.red_team_veto else 0,
                    verification.red_team_penalty,
                    verification.estimated_win_probability,
                    verification.final_confidence_score,
                    raw_json_response,
                ),
            )
            await conn.commit()

    async def get_verification(
        self,
        anomaly_id: str,
    ) -> Optional[AIVerificationResultDTO]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "SELECT * FROM ai_verifications WHERE anomaly_id = ?",
                (anomaly_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            r = dict(row)
            flaws: List[str] = []
            try:
                parsed_raw = json.loads(str(r["raw_json_response"]))
                if isinstance(parsed_raw, dict):
                    if isinstance(parsed_raw.get("red_team_flaws_detected"), list):
                        flaws = [str(item) for item in parsed_raw["red_team_flaws_detected"]]
                    elif isinstance(parsed_raw.get("step2a_catalyst"), dict) and isinstance(
                        parsed_raw["step2a_catalyst"].get("bear_flaws_detected"), list
                    ):
                        flaws = [
                            str(item)
                            for item in parsed_raw["step2a_catalyst"]["bear_flaws_detected"]
                        ]
            except (ValueError, TypeError):
                flaws = []
            return AIVerificationResultDTO(
                anomaly_id=str(r["anomaly_id"]),
                primary_catalyst_summary=str(r["primary_catalyst_summary"]),
                source_timestamps_verified=bool(int(r["source_timestamps_verified"])),
                bull_thesis_score=int(r["bull_thesis_score"]),
                red_team_flaws_detected=flaws,
                red_team_veto=bool(int(r["red_team_veto"])),
                red_team_penalty=int(r["red_team_penalty"]),
                estimated_win_probability=float(r["estimated_win_probability"]),
                final_confidence_score=int(r["final_confidence_score"]),
            )

    async def count_rolling_24h_ai_calls(
        self,
        since_utc_iso: str,
        exclude_fallback_quant_only: bool = True,
    ) -> int:
        """
        Counts real paid Gate 2 AI evaluations recorded in `ai_verifications`
        over the rolling 24-hour window (`a.timestamp_utc >= since_utc_iso`).
        """
        async with self._client.session() as conn:
            if exclude_fallback_quant_only:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM ai_verifications v
                    INNER JOIN anomalies a ON a.anomaly_id = v.anomaly_id
                    WHERE a.timestamp_utc >= ?
                      AND v.raw_json_response NOT LIKE '%"FALLBACK_QUANT_ONLY"%'
                      AND v.primary_catalyst_summary NOT LIKE '[FALLBACK_QUANT_ONLY]%'
                    """,
                    (since_utc_iso,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM ai_verifications v
                    INNER JOIN anomalies a ON a.anomaly_id = v.anomaly_id
                    WHERE a.timestamp_utc >= ?
                    """,
                    (since_utc_iso,),
                )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None or row["cnt"] is None:
                return 0
            return int(row["cnt"])


class TradeRepository:
    """Repository for Gate 3 & Execution trades, MFE/MAE tracking, and Circuit Breaker queries."""

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def create_trade(self, trade: TradeRecordDTO) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO trades (
                    order_id,
                    anomaly_id,
                    venue,
                    symbol_or_market_id,
                    execution_mode,
                    direction,
                    status,
                    entry_price,
                    exit_price,
                    stop_loss_price,
                    take_profit_price,
                    position_size_usd,
                    position_size_units,
                    realized_pnl_usd,
                    fees_paid_usd,
                    slippage_est_usd,
                    max_favorable_excursion_pct,
                    max_adverse_excursion_pct,
                    close_reason,
                    opened_at_utc,
                    closed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.order_id,
                    trade.anomaly_id,
                    trade.venue.value,
                    trade.symbol_or_market_id,
                    trade.execution_mode.value,
                    trade.direction.value,
                    trade.status.value,
                    str(trade.entry_price),
                    str(trade.exit_price) if trade.exit_price is not None else None,
                    str(trade.stop_loss_price),
                    str(trade.take_profit_price),
                    str(trade.position_size_usd),
                    str(trade.position_size_units),
                    str(trade.realized_pnl_usd),
                    str(trade.fees_paid_usd),
                    str(trade.slippage_est_usd),
                    float(trade.max_favorable_excursion_pct),
                    float(trade.max_adverse_excursion_pct),
                    trade.close_reason,
                    trade.opened_at_utc.isoformat(),
                    trade.closed_at_utc.isoformat() if trade.closed_at_utc is not None else None,
                ),
            )
            await conn.commit()

    async def get_trade(self, order_id: str) -> Optional[TradeRecordDTO]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "SELECT * FROM trades WHERE order_id = ?",
                (order_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            return self._row_to_dto(row)

    async def list_open_trades(
        self,
        venue: Optional[VenueType] = None,
    ) -> List[TradeRecordDTO]:
        async with self._client.session() as conn:
            if venue is not None:
                cursor = await conn.execute(
                    "SELECT * FROM trades WHERE status = ? AND venue = ? ORDER BY opened_at_utc ASC",
                    (OrderStatus.OPEN.value, venue.value),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * FROM trades WHERE status = ? ORDER BY opened_at_utc ASC",
                    (OrderStatus.OPEN.value,),
                )
            rows = await cursor.fetchall()
            await cursor.close()
            return [self._row_to_dto(r) for r in rows]

    async def update_stop_loss(
        self,
        order_id: str,
        new_stop_loss: Decimal,
    ) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                "UPDATE trades SET stop_loss_price = ? WHERE order_id = ?",
                (str(new_stop_loss), order_id),
            )
            await conn.commit()

    async def update_excursions(
        self,
        order_id: str,
        mfe_pct: float,
        mae_pct: float,
    ) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                """
                UPDATE trades
                SET max_favorable_excursion_pct = ?,
                    max_adverse_excursion_pct = ?
                WHERE order_id = ?
                """,
                (round(float(mfe_pct), 6), round(float(mae_pct), 6), order_id),
            )
            await conn.commit()

    async def close_trade(
        self,
        order_id: str,
        status: OrderStatus,
        exit_price: Decimal,
        realized_pnl_usd: Decimal,
        closed_at_utc_iso: str,
        fees_paid_usd: Optional[Decimal] = None,
        slippage_est_usd: Optional[Decimal] = None,
        close_reason: Optional[str] = None,
    ) -> None:
        reason = close_reason or status.value
        async with self._client.session() as conn:
            if fees_paid_usd is not None and slippage_est_usd is not None:
                await conn.execute(
                    """
                    UPDATE trades
                    SET status = ?,
                        exit_price = ?,
                        realized_pnl_usd = ?,
                        fees_paid_usd = ?,
                        slippage_est_usd = ?,
                        close_reason = ?,
                        closed_at_utc = ?
                    WHERE order_id = ?
                    """,
                    (
                        status.value,
                        str(exit_price),
                        str(realized_pnl_usd),
                        str(fees_paid_usd),
                        str(slippage_est_usd),
                        reason,
                        closed_at_utc_iso,
                        order_id,
                    ),
                )
            else:
                await conn.execute(
                    """
                    UPDATE trades
                    SET status = ?,
                        exit_price = ?,
                        realized_pnl_usd = ?,
                        close_reason = ?,
                        closed_at_utc = ?
                    WHERE order_id = ?
                    """,
                    (
                        status.value,
                        str(exit_price),
                        str(realized_pnl_usd),
                        reason,
                        closed_at_utc_iso,
                        order_id,
                    ),
                )
            await conn.commit()

    async def get_recent_closed_trades(self, limit: int = 3) -> List[TradeRecordDTO]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM trades
                WHERE status IN (?, ?, ?)
                ORDER BY closed_at_utc DESC, rowid DESC
                LIMIT ?
                """,
                (
                    OrderStatus.CLOSED_TP.value,
                    OrderStatus.CLOSED_SL.value,
                    OrderStatus.CLOSED_MANUAL.value,
                    limit,
                ),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return [self._row_to_dto(r) for r in rows]

    async def get_rolling_24h_realized_pnl(self, since_utc_iso: str) -> Decimal:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                SELECT realized_pnl_usd FROM trades
                WHERE status IN (?, ?, ?)
                  AND closed_at_utc IS NOT NULL
                  AND closed_at_utc >= ?
                """,
                (
                    OrderStatus.CLOSED_TP.value,
                    OrderStatus.CLOSED_SL.value,
                    OrderStatus.CLOSED_MANUAL.value,
                    since_utc_iso,
                ),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            total = Decimal("0.0")
            for row in rows:
                total += Decimal(str(row["realized_pnl_usd"]))
            return total

    async def cancel_all_open_trades(self, closed_at_utc_iso: str) -> int:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                UPDATE trades
                SET status = ?,
                    close_reason = ?,
                    closed_at_utc = ?
                WHERE status = ?
                """,
                (
                    OrderStatus.CANCELLED.value,
                    "CIRCUIT_BREAKER_OR_HALT",
                    closed_at_utc_iso,
                    OrderStatus.OPEN.value,
                ),
            )
            await conn.commit()
            count = int(cursor.rowcount or 0)
            await cursor.close()
            return count

    @staticmethod
    def _row_to_dto(row: object) -> TradeRecordDTO:
        r = dict(row)  # type: ignore[call-overload]
        opened_at = datetime.fromisoformat(str(r["opened_at_utc"]))
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        closed_at: Optional[datetime] = None
        if r.get("closed_at_utc"):
            closed_at = datetime.fromisoformat(str(r["closed_at_utc"]))
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)
        return TradeRecordDTO(
            order_id=str(r["order_id"]),
            anomaly_id=str(r["anomaly_id"]),
            venue=VenueType(str(r["venue"])),
            symbol_or_market_id=str(r["symbol_or_market_id"]),
            execution_mode=ExecutionMode(str(r["execution_mode"])),
            direction=SignalDirection(str(r["direction"])),
            status=OrderStatus(str(r["status"])),
            entry_price=Decimal(str(r["entry_price"])),
            exit_price=Decimal(str(r["exit_price"])) if r.get("exit_price") is not None else None,
            stop_loss_price=Decimal(str(r["stop_loss_price"])),
            take_profit_price=Decimal(str(r["take_profit_price"])),
            position_size_usd=Decimal(str(r["position_size_usd"])),
            position_size_units=Decimal(str(r["position_size_units"])),
            realized_pnl_usd=Decimal(str(r.get("realized_pnl_usd") or "0.0")),
            fees_paid_usd=Decimal(str(r.get("fees_paid_usd") or "0.0")),
            slippage_est_usd=Decimal(str(r.get("slippage_est_usd") or "0.0")),
            max_favorable_excursion_pct=float(r.get("max_favorable_excursion_pct") or 0.0),
            max_adverse_excursion_pct=float(r.get("max_adverse_excursion_pct") or 0.0),
            close_reason=str(r["close_reason"]) if r.get("close_reason") is not None else None,
            opened_at_utc=opened_at,
            closed_at_utc=closed_at,
        )


class BrierRepository:
    """Repository for tracking and computing Brier calibration scores."""

    def __init__(self, client: SQLiteClient) -> None:
        self._client = client

    async def record_prediction(self, record: BrierTrackingDTO) -> None:
        async with self._client.session() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO brier_tracking (
                    prediction_id,
                    anomaly_id,
                    predicted_prob,
                    actual_outcome,
                    brier_score_component,
                    recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.prediction_id,
                    record.anomaly_id,
                    record.predicted_prob,
                    record.actual_outcome,
                    record.brier_score_component,
                    record.recorded_at_utc.isoformat(),
                ),
            )
            await conn.commit()

    async def resolve_prediction(
        self,
        prediction_id: str,
        actual_outcome: int,
    ) -> Optional[BrierTrackingDTO]:
        if actual_outcome not in (0, 1):
            raise ValueError("actual_outcome must be 0 or 1")
        async with self._client.session() as conn:
            cursor = await conn.execute(
                "SELECT * FROM brier_tracking WHERE prediction_id = ?",
                (prediction_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            r = dict(row)
            predicted_prob = float(r["predicted_prob"])
            brier_component = (predicted_prob - float(actual_outcome)) ** 2
            await conn.execute(
                """
                UPDATE brier_tracking
                SET actual_outcome = ?,
                    brier_score_component = ?
                WHERE prediction_id = ?
                """,
                (actual_outcome, brier_component, prediction_id),
            )
            await conn.commit()
            recorded_at = datetime.fromisoformat(str(r["recorded_at_utc"]))
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            return BrierTrackingDTO(
                prediction_id=str(r["prediction_id"]),
                anomaly_id=str(r["anomaly_id"]),
                predicted_prob=predicted_prob,
                actual_outcome=actual_outcome,
                brier_score_component=brier_component,
                recorded_at_utc=recorded_at,
            )

    async def get_mean_brier_score(self) -> Optional[float]:
        async with self._client.session() as conn:
            cursor = await conn.execute(
                """
                SELECT AVG(brier_score_component) AS mean_brier
                FROM brier_tracking
                WHERE brier_score_component IS NOT NULL
                """
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None or row["mean_brier"] is None:
                return None
            return float(row["mean_brier"])
