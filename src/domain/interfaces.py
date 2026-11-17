from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Protocol, runtime_checkable
from src.domain.dtos import (
    AIVerificationResultDTO,
    AccountLedgerDTO,
    ApprovedOrderDTO,
    BrierTrackingDTO,
    CandleDTO,
    CatalystExtractionDTO,
    GeminiDecisionOutputDTO,
    HyperliquidAssetContextDTO,
    MarketAnomalyDTO,
    OISnapshotDTO,
    PolymarketCandidateDTO,
    TradeRecordDTO,
)
from src.domain.enums import OrderStatus, VenueType


@runtime_checkable
class AccountLedgerRepositoryProtocol(Protocol):
    async def initialize_ledger(
        self,
        initial_equity_usd: Decimal = Decimal("100.00"),
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO: ...

    async def get_ledger(
        self,
        default_initial_equity_usd: Decimal = Decimal("100.00"),
    ) -> AccountLedgerDTO: ...

    async def lock_margin_and_deduct_entry_fee(
        self,
        margin_to_lock_usd: Decimal,
        entry_fee_usd: Decimal,
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO: ...

    async def release_margin_and_settle_pnl(
        self,
        margin_unlocked_usd: Decimal,
        net_realized_pnl_usd: Decimal,
        exit_fee_usd: Decimal,
        now_utc: Optional[datetime] = None,
    ) -> AccountLedgerDTO: ...


@runtime_checkable
class OISnapshotRepositoryProtocol(Protocol):
    async def insert_snapshot(self, snapshot: OISnapshotDTO) -> int: ...

    async def insert_snapshots_bulk(self, snapshots: List[OISnapshotDTO]) -> None: ...

    async def get_snapshot_1h_ago(
        self,
        coin: str,
        current_epoch_ms: int,
        tolerance_ms: int = 900_000,
    ) -> Optional[OISnapshotDTO]: ...

    async def calculate_oi_delta_1h_pct(
        self,
        coin: str,
        current_oi: float,
        current_epoch_ms: int,
    ) -> Optional[float]: ...

    async def prune_old_snapshots(self, older_than_epoch_ms: int) -> int: ...


@runtime_checkable
class AnomalyRepositoryProtocol(Protocol):
    async def save_anomaly(
        self,
        anomaly: MarketAnomalyDTO,
        passed_gate2: bool = False,
    ) -> None: ...

    async def mark_passed_gate2(self, anomaly_id: str, passed: bool = True) -> None: ...

    async def get_anomaly(self, anomaly_id: str) -> Optional[MarketAnomalyDTO]: ...

    async def list_recent_anomalies(self, limit: int = 50) -> List[MarketAnomalyDTO]: ...

    async def has_recent_gate2_evaluation(
        self,
        symbol_or_market_id: str,
        since_utc_iso: str,
    ) -> bool: ...


@runtime_checkable
class AIVerificationRepositoryProtocol(Protocol):
    async def save_verification(
        self,
        verification: AIVerificationResultDTO,
        raw_json_response: str,
    ) -> None: ...

    async def get_verification(
        self,
        anomaly_id: str,
    ) -> Optional[AIVerificationResultDTO]: ...

    async def count_rolling_24h_ai_calls(
        self,
        since_utc_iso: str,
        exclude_fallback_quant_only: bool = True,
    ) -> int: ...


@runtime_checkable
class TradeRepositoryProtocol(Protocol):
    async def create_trade(self, trade: TradeRecordDTO) -> None: ...

    async def get_trade(self, order_id: str) -> Optional[TradeRecordDTO]: ...

    async def list_open_trades(
        self,
        venue: Optional[VenueType] = None,
    ) -> List[TradeRecordDTO]: ...

    async def update_stop_loss(
        self,
        order_id: str,
        new_stop_loss: Decimal,
    ) -> None: ...

    async def update_excursions(
        self,
        order_id: str,
        mfe_pct: float,
        mae_pct: float,
    ) -> None: ...

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
    ) -> None: ...

    async def get_recent_closed_trades(self, limit: int = 3) -> List[TradeRecordDTO]: ...

    async def get_rolling_24h_realized_pnl(self, since_utc_iso: str) -> Decimal: ...

    async def cancel_all_open_trades(self, closed_at_utc_iso: str) -> int: ...


@runtime_checkable
class BrierRepositoryProtocol(Protocol):
    async def record_prediction(self, record: BrierTrackingDTO) -> None: ...

    async def resolve_prediction(
        self,
        prediction_id: str,
        actual_outcome: int,
    ) -> Optional[BrierTrackingDTO]: ...

    async def get_mean_brier_score(self) -> Optional[float]: ...


class HyperliquidVenueAdapter(ABC):
    @abstractmethod
    async def fetch_meta_and_asset_ctxs(self) -> List[HyperliquidAssetContextDTO]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_candles(
        self,
        coin: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> List[CandleDTO]:
        raise NotImplementedError

    @abstractmethod
    async def place_order(self, order: ApprovedOrderDTO) -> Dict[str, object]:
        raise NotImplementedError


class PolymarketVenueAdapter(ABC):
    @abstractmethod
    async def discover_short_horizon_markets(self) -> List[PolymarketCandidateDTO]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_spreads_batch(self, token_ids: List[str]) -> Dict[str, Decimal]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_midpoints_batch(self, token_ids: List[str]) -> Dict[str, Decimal]:
        raise NotImplementedError

    @abstractmethod
    async def place_order(self, order: ApprovedOrderDTO) -> Dict[str, object]:
        raise NotImplementedError


class LLMRouterAdapter(ABC):
    @abstractmethod
    async def extract_catalyst_step2a(
        self,
        anomaly: MarketAnomalyDTO,
    ) -> CatalystExtractionDTO:
        raise NotImplementedError

    @abstractmethod
    async def call_gemini_decision_step2b(
        self,
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
    ) -> GeminiDecisionOutputDTO:
        raise NotImplementedError

    @abstractmethod
    async def run_red_team_step2b(
        self,
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
    ) -> tuple[AIVerificationResultDTO, str]:
        raise NotImplementedError
