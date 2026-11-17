from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from src.domain.enums import ExecutionMode, OrderStatus, SignalDirection, VenueType


class MarketAnomalyDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    timestamp_utc: datetime
    venue: VenueType
    symbol_or_market_id: str
    asset_name_or_question: str = Field(
        ...,
        description="Coin ticker or full Polymarket question text for Grok search",
    )
    target_token_id: Optional[str] = Field(
        None,
        description="Polymarket CLOB token_id for execution",
    )
    no_token_id: Optional[str] = Field(
        None,
        description="Polymarket CLOB NO token_id for BUY_NO execution",
    )
    sz_decimals_or_tick: Decimal = Field(
        Decimal("0.01"),
        description="Size decimals (HL) or minimum_tick_size (Polymarket)",
    )
    current_price: Decimal
    rvol_ratio: float = Field(..., description="Relative volume vs 20-period mean")
    oi_delta_1h_pct: Optional[float] = Field(
        None,
        description="1h Open Interest change %",
    )
    funding_rate_hourly: Optional[float] = Field(
        None,
        description="Current hourly funding rate",
    )
    vwap_distance_pct: Optional[float] = Field(
        None,
        description="Distance from daily VWAP %",
    )
    btc_1h_return_pct: Optional[float] = Field(
        None,
        description="BTC 1h return % for regime filtering",
    )
    atr_14: Optional[Decimal] = Field(
        None,
        description="14-period Average True Range",
    )
    hours_to_resolution: Optional[float] = Field(
        None,
        description="Polymarket hours left",
    )
    bid_ask_spread: Decimal
    proposed_direction: SignalDirection


class CatalystExtractionDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalyst_found: bool
    primary_catalyst_summary: str
    bull_arguments: List[str] = Field(default_factory=list)
    bear_flaws_detected: List[str] = Field(default_factory=list)
    audit_reasoning_trace: str = ""
    earliest_post_timestamp_utc: str
    age_in_minutes: int
    verifiable_source_urls: List[str] = Field(default_factory=list)
    is_recycled_or_old_news: bool


class GeminiDecisionOutputDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_fresh_and_verifiable_prob: float = Field(..., ge=0.0, le=1.0)
    is_bull_trap_or_manipulation_prob: float = Field(..., ge=0.0, le=1.0)
    win_probability: float = Field(..., ge=0.0, le=1.0)
    thesis_quality_score: float = Field(..., ge=0.0, le=100.0)
    raw_response_json: str = ""


class AIVerificationResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    primary_catalyst_summary: str
    source_timestamps_verified: bool
    bull_thesis_score: int = Field(..., ge=0, le=100)
    red_team_flaws_detected: List[str]
    red_team_veto: bool
    red_team_penalty: int = Field(..., ge=0, le=100)
    estimated_win_probability: float = Field(..., ge=0.0, le=1.0)
    final_confidence_score: int = Field(..., ge=0, le=100)


class ApprovedOrderDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    anomaly_id: str
    venue: VenueType
    symbol_or_market_id: str
    direction: SignalDirection
    entry_price_limit: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    position_size_usd: Decimal
    position_size_units: Decimal
    risk_amount_usd: Decimal
    expected_value_ratio: float
    target_token_id: Optional[str] = Field(
        None,
        description="Polymarket resolved YES or NO token ID for order execution",
    )
    sz_decimals_or_tick: Decimal = Field(
        Decimal("0.01"),
        description="Precision rounding step for venue execution",
    )
    bid_ask_spread: Decimal = Field(
        Decimal("0.0"),
        description="Observed bid-ask spread at approval time for slippage accounting",
    )


class AccountLedgerDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    equity_usd: Decimal
    available_margin_usd: Decimal
    locked_margin_usd: Decimal = Decimal("0.0")
    realized_pnl_cumulative_usd: Decimal = Decimal("0.0")
    total_fees_paid_usd: Decimal = Decimal("0.0")
    updated_at_utc: datetime


class OISnapshotDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: Optional[int] = None
    coin: str
    timestamp_epoch_ms: int
    open_interest: float
    mark_px: float


class TradeRecordDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    anomaly_id: str
    venue: VenueType
    symbol_or_market_id: str
    execution_mode: ExecutionMode
    direction: SignalDirection
    status: OrderStatus
    entry_price: Decimal
    exit_price: Optional[Decimal] = None
    stop_loss_price: Decimal
    take_profit_price: Decimal
    position_size_usd: Decimal
    position_size_units: Decimal
    realized_pnl_usd: Decimal = Decimal("0.0")
    fees_paid_usd: Decimal = Decimal("0.0")
    slippage_est_usd: Decimal = Decimal("0.0")
    max_favorable_excursion_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    close_reason: Optional[str] = None
    opened_at_utc: datetime
    closed_at_utc: Optional[datetime] = None


class BrierTrackingDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction_id: str
    anomaly_id: str
    predicted_prob: float = Field(..., ge=0.0, le=1.0)
    actual_outcome: Optional[int] = Field(None, ge=0, le=1)
    brier_score_component: Optional[float] = None
    recorded_at_utc: datetime


class HyperliquidAssetContextDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    coin: str
    asset_index: int
    sz_decimals: int
    max_leverage: int
    day_ntl_vlm: Decimal
    funding_hourly: float
    open_interest: float
    mark_px: Decimal
    mid_px: Decimal
    oracle_px: Decimal
    prev_day_px: Decimal
    impact_bid_px: Optional[Decimal] = None
    impact_ask_px: Optional[Decimal] = None


class CandleDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp_open_ms: int
    timestamp_close_ms: int
    symbol: str
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    num_trades: int = 0


class PolymarketCandidateDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    market_id: str
    question: str
    condition_id: Optional[str] = None
    yes_token_id: str
    no_token_id: str
    yes_price: Decimal
    no_price: Decimal
    midpoint_yes: Decimal
    spread_yes: Decimal
    volume_usd: Decimal
    hours_to_resolution: float
    minimum_tick_size: Decimal = Decimal("0.01")


class CircuitBreakerStateDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_active: bool
    reason: str
    consecutive_losses: int
    rolling_24h_pnl_usd: Decimal
    daily_drawdown_pct: float
    triggered_at_utc: Optional[datetime] = None
