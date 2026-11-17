import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence
import numpy as np
import pandas as pd

from src.domain.dtos import (
    CandleDTO,
    HyperliquidAssetContextDTO,
    MarketAnomalyDTO,
    PolymarketCandidateDTO,
)
from src.domain.enums import SignalDirection, VenueType
from src.domain.interfaces import HyperliquidVenueAdapter, PolymarketVenueAdapter

logger = logging.getLogger(__name__)


def calculate_rvol(
    volumes_15m: Sequence[float | Decimal] | np.ndarray | pd.Series,
    window: int = 20,
) -> float:
    """
    Vectorized Relative Volume (RVOL) calculation:
    RVOL = Volume_current_15m / SMA(Volume_15m, 20)
    """
    arr = np.asarray([float(v) for v in volumes_15m], dtype=np.float64)
    if arr.size == 0:
        return 0.0
    if arr.size == 1:
        return 1.0 if arr[0] > 0.0 else 0.0

    current_vol = float(arr[-1])
    if arr.size >= window + 1:
        baseline = arr[-(window + 1) : -1]
    else:
        baseline = arr[:-1]

    sma_20 = float(np.mean(baseline))
    if sma_20 <= 0.0:
        return 0.0
    return current_vol / sma_20


def calculate_daily_vwap(candles: Sequence[CandleDTO]) -> Decimal:
    """
    Vectorized Daily VWAP calculation over 15m candles using Typical Price = (H + L + C) / 3.
    """
    if not candles:
        return Decimal("0")

    df = pd.DataFrame(
        {
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        }
    )
    total_vol = float(df["volume"].sum())
    if total_vol <= 0.0:
        return candles[-1].close

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    vwap_val = float((typical_price * df["volume"]).sum() / total_vol)
    return Decimal(f"{vwap_val:.8f}")


def calculate_vwap_distance_pct(
    current_price: Decimal | float,
    daily_vwap: Decimal | float,
) -> float:
    """
    Returns fractional distance from Daily VWAP:
    (Price - VWAP) / VWAP.
    Example: +0.04 means +4.0% above Daily VWAP; -0.02 means -2.0% below Daily VWAP.
    """
    vwap_f = float(daily_vwap)
    if vwap_f <= 0.0:
        return 0.0
    return (float(current_price) - vwap_f) / vwap_f


def calculate_atr_14(
    candles: Sequence[CandleDTO],
    period: int = 14,
) -> Decimal:
    """
    Vectorized 14-period Average True Range (ATR-14) using numpy and pandas.
    TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
    """
    if not candles:
        return Decimal("0")
    if len(candles) == 1:
        diff = candles[0].high - candles[0].low
        return diff if diff > Decimal("0") else Decimal("0")

    highs = np.array([float(c.high) for c in candles], dtype=np.float64)
    lows = np.array([float(c.low) for c in candles], dtype=np.float64)
    closes = np.array([float(c.close) for c in candles], dtype=np.float64)

    prev_closes = np.roll(closes, 1)
    prev_closes[0] = closes[0]

    tr1 = highs - lows
    tr2 = np.abs(highs - prev_closes)
    tr3 = np.abs(lows - prev_closes)
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))

    window = min(period, len(true_range))
    atr_val = float(np.mean(true_range[-window:]))
    return Decimal(f"{atr_val:.8f}")


def calculate_1h_return_pct(candles_15m: Sequence[CandleDTO]) -> float:
    """
    Computes 1-hour return fraction from 15-minute candles:
    (Close_now - Close_1h_ago) / Close_1h_ago.
    With 15m candles, 1 hour ago is 4 bars back (index -5 vs -1).
    """
    if len(candles_15m) < 2:
        return 0.0
    idx_1h_ago = -5 if len(candles_15m) >= 5 else 0
    close_prev = float(candles_15m[idx_1h_ago].close)
    close_now = float(candles_15m[-1].close)
    if close_prev <= 0.0:
        return 0.0
    return (close_now - close_prev) / close_prev


def evaluate_btc_macro_regime(
    btc_1h_return_pct: float,
    asset_1h_return_pct: float,
    proposed_direction: SignalDirection,
) -> bool:
    """
    BTC Macro Regime Filter (Anti-Knife-Catch Guard) from Section 6.1:
    If BTC 1-hour return is <= -2.0% (-0.02), block all altcoin LONG signals
    unless the candidate asset's 1-hour return is > +1.5% (+0.015).
    """
    if proposed_direction != SignalDirection.LONG:
        return True
    if btc_1h_return_pct <= -0.02:
        return asset_1h_return_pct > 0.015
    return True


class Gate1QuantFilter:
    """
    Gate 1 Deterministic Quant & Microstructure Filter.
    Filters out 95%+ of noise using pure vectorized Python math before any LLM call.
    """

    MIN_HL_24H_VOLUME_USD: Decimal = Decimal("2000000")
    MIN_RVOL_RATIO: float = 2.5
    MIN_OI_DELTA_1H_PCT: float = 0.05

    MAX_LONG_VWAP_DIST_PCT: float = 0.08
    MAX_LONG_FUNDING_HOURLY: float = 0.00005

    MIN_SHORT_VWAP_DIST_PCT: float = -0.08
    MAX_SHORT_VWAP_DIST_PCT: float = -0.005
    MIN_SHORT_FUNDING_HOURLY: float = -0.00005

    MIN_PM_HOURS: float = 6.0
    MAX_PM_HOURS: float = 72.0
    MIN_PM_VOLUME_USD: Decimal = Decimal("25000")
    MAX_PM_SPREAD: Decimal = Decimal("0.03")
    MIN_PM_PROB: Decimal = Decimal("0.15")
    MAX_PM_PROB: Decimal = Decimal("0.85")

    def __init__(
        self,
        hyperliquid_client: Optional[HyperliquidVenueAdapter] = None,
        polymarket_client: Optional[PolymarketVenueAdapter] = None,
        max_concurrent_candles: int = 3,
    ) -> None:
        self._hl_client = hyperliquid_client
        self._pm_client = polymarket_client
        self._candle_semaphore = asyncio.Semaphore(max_concurrent_candles)

    def compute_asset_microstructure_metrics(
        self,
        asset: HyperliquidAssetContextDTO,
        candles_15m: Sequence[CandleDTO],
        oi_delta_1h_pct: Optional[float] = None,
        btc_1h_return_pct: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Computes exact Gate 1 microstructure metrics (RVOL, Daily VWAP, VWAP Distance %,
        ATR-14, 1h Return %) for a Hyperliquid asset and its 15m candle series.
        Handles cold-start warmup (oi_delta_1h_pct is None) gracefully.
        """
        rvol = calculate_rvol([c.volume for c in candles_15m], window=20)
        daily_candles = candles_15m[-96:] if len(candles_15m) >= 96 else candles_15m
        daily_vwap = calculate_daily_vwap(daily_candles)
        current_px = asset.mid_px if asset.mid_px > Decimal("0") else asset.mark_px
        vwap_dist = calculate_vwap_distance_pct(current_px, daily_vwap)
        atr_14 = calculate_atr_14(candles_15m, period=14)
        asset_1h_ret = calculate_1h_return_pct(candles_15m)
        return {
            "coin": asset.coin,
            "current_price": current_px,
            "day_ntl_vlm": asset.day_ntl_vlm,
            "rvol_ratio": round(rvol, 4),
            "daily_vwap": daily_vwap,
            "vwap_distance_pct": round(vwap_dist, 6),
            "atr_14": atr_14,
            "asset_1h_return_pct": round(asset_1h_ret, 6),
            "btc_1h_return_pct": round(btc_1h_return_pct, 6),
            "oi_delta_1h_pct": round(oi_delta_1h_pct, 6) if oi_delta_1h_pct is not None else None,
            "funding_hourly": asset.funding_hourly,
        }

    def evaluate_hyperliquid_asset(
        self,
        asset: HyperliquidAssetContextDTO,
        candles_15m: Sequence[CandleDTO],
        oi_delta_1h_pct: Optional[float],
        btc_1h_return_pct: float,
        now_utc: Optional[datetime] = None,
        allow_cold_start_oi: bool = False,
    ) -> Optional[MarketAnomalyDTO]:
        """
        Evaluates a single Hyperliquid asset against all Gate 1 LONG and SHORT rules.
        During cold-start warmup (oi_delta_1h_pct is None), returns None gracefully
        unless allow_cold_start_oi=True is explicitly enabled for smoke testing.
        """
        if asset.day_ntl_vlm < self.MIN_HL_24H_VOLUME_USD:
            return None
        if oi_delta_1h_pct is None:
            if not allow_cold_start_oi:
                return None
            effective_oi_delta = 0.0
        else:
            if oi_delta_1h_pct < self.MIN_OI_DELTA_1H_PCT:
                return None
            effective_oi_delta = oi_delta_1h_pct
        if len(candles_15m) < 14:
            return None

        rvol = calculate_rvol([c.volume for c in candles_15m], window=20)
        if rvol < self.MIN_RVOL_RATIO:
            return None

        daily_candles = candles_15m[-96:] if len(candles_15m) >= 96 else candles_15m
        daily_vwap = calculate_daily_vwap(daily_candles)
        current_px = asset.mid_px if asset.mid_px > Decimal("0") else asset.mark_px
        vwap_dist = calculate_vwap_distance_pct(current_px, daily_vwap)
        atr_14 = calculate_atr_14(candles_15m, period=14)
        asset_1h_ret = calculate_1h_return_pct(candles_15m)

        direction: Optional[SignalDirection] = None

        # Check LONG criteria
        if (
            0.0 < vwap_dist <= self.MAX_LONG_VWAP_DIST_PCT
            and asset.funding_hourly <= self.MAX_LONG_FUNDING_HOURLY
        ):
            if evaluate_btc_macro_regime(
                btc_1h_return_pct=btc_1h_return_pct,
                asset_1h_return_pct=asset_1h_ret,
                proposed_direction=SignalDirection.LONG,
            ):
                direction = SignalDirection.LONG

        # Check SHORT criteria if not LONG
        if direction is None:
            if (
                self.MIN_SHORT_VWAP_DIST_PCT <= vwap_dist <= self.MAX_SHORT_VWAP_DIST_PCT
                and asset.funding_hourly >= self.MIN_SHORT_FUNDING_HOURLY
            ):
                direction = SignalDirection.SHORT

        if direction is None:
            return None

        if asset.impact_bid_px is not None and asset.impact_ask_px is not None:
            spread = abs(asset.impact_ask_px - asset.impact_bid_px)
        else:
            spread = Decimal("0.0")

        sz_step = (
            Decimal("10") ** (-asset.sz_decimals)
            if asset.sz_decimals > 0
            else Decimal("1")
        )

        anomaly = MarketAnomalyDTO(
            anomaly_id=f"hl-{asset.coin.lower()}-{uuid.uuid4().hex[:10]}",
            timestamp_utc=now_utc or datetime.now(timezone.utc),
            venue=VenueType.HYPERLIQUID,
            symbol_or_market_id=asset.coin,
            asset_name_or_question=f"{asset.coin} Hyperliquid Perpetuals",
            target_token_id=None,
            sz_decimals_or_tick=sz_step,
            current_price=current_px,
            rvol_ratio=round(rvol, 4),
            oi_delta_1h_pct=round(effective_oi_delta, 6) if oi_delta_1h_pct is not None else None,
            funding_rate_hourly=asset.funding_hourly,
            vwap_distance_pct=round(vwap_dist, 6),
            btc_1h_return_pct=round(btc_1h_return_pct, 6),
            atr_14=atr_14,
            hours_to_resolution=None,
            bid_ask_spread=spread,
            proposed_direction=direction,
        )
        logger.info(
            "[ANOMALY] Gate 1 HYPERLIQUID match: %s dir=%s RVOL=%.2f OI_1h=%.2f%% VWAP_dist=%.2f%%",
            asset.coin,
            direction.value,
            rvol,
            effective_oi_delta * 100.0,
            vwap_dist * 100.0,
        )
        return anomaly

    def evaluate_polymarket_market(
        self,
        candidate: PolymarketCandidateDTO,
        rvol_ratio: float = 2.5,
        now_utc: Optional[datetime] = None,
    ) -> Optional[MarketAnomalyDTO]:
        """
        Evaluates a Polymarket market against all Gate 1 Short-Horizon criteria (Section 6.2):
        - 6 <= Hours to Resolution <= 72
        - Total Market Volume >= $25,000 AND Best Bid-Ask Spread <= $0.03
        - Current Implied Probability (P_market) between $0.15 and $0.85
        """
        if not (self.MIN_PM_HOURS <= candidate.hours_to_resolution <= self.MAX_PM_HOURS):
            return None
        if candidate.volume_usd < self.MIN_PM_VOLUME_USD:
            return None
        if candidate.spread_yes > self.MAX_PM_SPREAD:
            return None
        if not (self.MIN_PM_PROB <= candidate.midpoint_yes <= self.MAX_PM_PROB):
            return None

        anomaly = MarketAnomalyDTO(
            anomaly_id=f"pm-{candidate.market_id}-{uuid.uuid4().hex[:10]}",
            timestamp_utc=now_utc or datetime.now(timezone.utc),
            venue=VenueType.POLYMARKET,
            symbol_or_market_id=candidate.market_id,
            asset_name_or_question=candidate.question,
            target_token_id=candidate.yes_token_id,
            no_token_id=candidate.no_token_id,
            sz_decimals_or_tick=candidate.minimum_tick_size,
            current_price=candidate.midpoint_yes,
            rvol_ratio=max(rvol_ratio, 2.5),
            oi_delta_1h_pct=None,
            funding_rate_hourly=None,
            vwap_distance_pct=None,
            btc_1h_return_pct=None,
            atr_14=None,
            hours_to_resolution=round(candidate.hours_to_resolution, 2),
            bid_ask_spread=candidate.spread_yes,
            proposed_direction=SignalDirection.BUY_YES,
        )
        logger.info(
            "[ANOMALY] Gate 1 POLYMARKET match: id=%s mid=%s spread=%s hrs=%.1f",
            candidate.market_id,
            candidate.midpoint_yes,
            candidate.spread_yes,
            candidate.hours_to_resolution,
        )
        return anomaly

    async def scan_hyperliquid(
        self,
        oi_deltas: Optional[Dict[str, Optional[float]]] = None,
        allow_cold_start_oi: bool = False,
    ) -> List[MarketAnomalyDTO]:
        if self._hl_client is None:
            return []

        assets = await self._hl_client.fetch_meta_and_asset_ctxs()
        now_ms = int(time.time() * 1000)
        start_24h_ms = now_ms - 24 * 3_600_000

        if oi_deltas is None and hasattr(
            self._hl_client, "record_oi_snapshots_and_get_deltas"
        ):
            oi_deltas = await getattr(
                self._hl_client, "record_oi_snapshots_and_get_deltas"
            )(assets, current_epoch_ms=now_ms)
        elif oi_deltas is None:
            oi_deltas = {}

        available_deltas = [v for v in oi_deltas.values() if v is not None]
        if not available_deltas and not allow_cold_start_oi:
            logger.info(
                "[INFO] Gate 1 Hyperliquid cold-start warmup: stored %d OI snapshots; waiting for 1h history.",
                len(assets),
            )
            return []

        async with self._candle_semaphore:
            btc_candles = await self._hl_client.fetch_candles(
                coin="BTC",
                interval="15m",
                start_time_ms=now_ms - 2 * 3_600_000,
                end_time_ms=now_ms,
            )
        btc_1h_ret = calculate_1h_return_pct(btc_candles)

        liquid_assets = [
            a for a in assets if a.day_ntl_vlm >= self.MIN_HL_24H_VOLUME_USD
        ]

        candidates_to_fetch: List[tuple[HyperliquidAssetContextDTO, Optional[float]]] = []
        for asset in liquid_assets:
            oi_delta = oi_deltas.get(asset.coin)
            if oi_delta is None and not allow_cold_start_oi:
                continue
            if oi_delta is not None and oi_delta < self.MIN_OI_DELTA_1H_PCT:
                continue
            candidates_to_fetch.append((asset, oi_delta))

        async def _evaluate_with_semaphore(
            asset: HyperliquidAssetContextDTO,
            oi_delta: Optional[float],
        ) -> Optional[MarketAnomalyDTO]:
            assert self._hl_client is not None
            async with self._candle_semaphore:
                candles = await self._hl_client.fetch_candles(
                    coin=asset.coin,
                    interval="15m",
                    start_time_ms=start_24h_ms,
                    end_time_ms=now_ms,
                )
            return self.evaluate_hyperliquid_asset(
                asset=asset,
                candles_15m=candles,
                oi_delta_1h_pct=oi_delta,
                btc_1h_return_pct=btc_1h_ret,
                allow_cold_start_oi=allow_cold_start_oi,
            )

        results = await asyncio.gather(
            *[_evaluate_with_semaphore(a, d) for a, d in candidates_to_fetch]
        )
        return [r for r in results if r is not None]

    async def scan_polymarket(self) -> List[MarketAnomalyDTO]:
        if self._pm_client is None:
            return []
        candidates = await self._pm_client.discover_short_horizon_markets()
        anomalies: List[MarketAnomalyDTO] = []
        for cand in candidates:
            anomaly = self.evaluate_polymarket_market(cand)
            if anomaly is not None:
                anomalies.append(anomaly)
        return anomalies
