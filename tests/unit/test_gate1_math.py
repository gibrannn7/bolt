from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List
import httpx
import pytest

from src.config.settings import Settings
from src.domain.dtos import (
    CandleDTO,
    HyperliquidAssetContextDTO,
    PolymarketCandidateDTO,
)
from src.domain.enums import SignalDirection, VenueType
from src.infrastructure.venues.hyperliquid_client import HyperliquidClient
from src.infrastructure.venues.polymarket_client import PolymarketClient
from src.use_cases.gate1_quant_filter import (
    Gate1QuantFilter,
    calculate_1h_return_pct,
    calculate_atr_14,
    calculate_daily_vwap,
    calculate_rvol,
    calculate_vwap_distance_pct,
    evaluate_btc_macro_regime,
)


def _make_candles(
    count: int = 25,
    base_price: Decimal = Decimal("100.0"),
    last_close: Decimal = Decimal("103.0"),
    base_volume: Decimal = Decimal("1000.0"),
    last_volume: Decimal = Decimal("3000.0"),
    high_offset: Decimal = Decimal("1.0"),
    low_offset: Decimal = Decimal("1.0"),
) -> List[CandleDTO]:
    candles: List[CandleDTO] = []
    start_ms = 1_760_000_000_000
    for i in range(count):
        is_last = i == count - 1
        close_px = last_close if is_last else base_price
        vol = last_volume if is_last else base_volume
        candles.append(
            CandleDTO(
                timestamp_open_ms=start_ms + i * 900_000,
                timestamp_close_ms=start_ms + (i + 1) * 900_000,
                symbol="SOL",
                interval="15m",
                open=base_price,
                high=close_px + high_offset,
                low=base_price - low_offset,
                close=close_px,
                volume=vol,
                num_trades=100,
            )
        )
    return candles


def test_rvol_vwap_and_atr_calculations() -> None:
    volumes = [100.0] * 20 + [250.0]
    rvol = calculate_rvol(volumes, window=20)
    assert rvol == pytest.approx(2.5)

    candles = _make_candles(
        count=21,
        base_price=Decimal("100.0"),
        last_close=Decimal("100.0"),
        base_volume=Decimal("500.0"),
        last_volume=Decimal("1500.0"),
        high_offset=Decimal("2.0"),
        low_offset=Decimal("2.0"),
    )
    vwap = calculate_daily_vwap(candles)
    assert float(vwap) == pytest.approx(100.0, rel=1e-5)

    vwap_dist = calculate_vwap_distance_pct(Decimal("104.0"), vwap)
    assert vwap_dist == pytest.approx(0.04, rel=1e-5)

    atr = calculate_atr_14(candles, period=14)
    assert float(atr) == pytest.approx(4.0, rel=1e-5)


def test_btc_macro_regime_filter() -> None:
    # BTC down -2.5%: block altcoin LONG if altcoin 1h return is +1.0% (<= +1.5%)
    assert (
        evaluate_btc_macro_regime(
            btc_1h_return_pct=-0.025,
            asset_1h_return_pct=0.010,
            proposed_direction=SignalDirection.LONG,
        )
        is False
    )
    # BTC down -2.5%: allow altcoin LONG if altcoin 1h return is +2.0% (> +1.5% decoupling)
    assert (
        evaluate_btc_macro_regime(
            btc_1h_return_pct=-0.025,
            asset_1h_return_pct=0.020,
            proposed_direction=SignalDirection.LONG,
        )
        is True
    )
    # SHORT signals are never blocked by BTC drop
    assert (
        evaluate_btc_macro_regime(
            btc_1h_return_pct=-0.035,
            asset_1h_return_pct=-0.020,
            proposed_direction=SignalDirection.SHORT,
        )
        is True
    )


def test_gate1_hyperliquid_long_and_short_filters() -> None:
    gate1 = Gate1QuantFilter()
    candles_long = _make_candles(
        count=21,
        base_price=Decimal("100.0"),
        last_close=Decimal("103.0"),
        base_volume=Decimal("1000.0"),
        last_volume=Decimal("3000.0"),
    )
    asset_long = HyperliquidAssetContextDTO(
        coin="SOL",
        asset_index=1,
        sz_decimals=2,
        max_leverage=20,
        day_ntl_vlm=Decimal("15000000"),
        funding_hourly=0.00002,  # 0.002% <= 0.005%
        open_interest=50000.0,
        mark_px=Decimal("103.0"),
        mid_px=Decimal("103.0"),
        oracle_px=Decimal("103.0"),
        prev_day_px=Decimal("99.0"),
        impact_bid_px=Decimal("102.95"),
        impact_ask_px=Decimal("103.05"),
    )

    anomaly_long = gate1.evaluate_hyperliquid_asset(
        asset=asset_long,
        candles_15m=candles_long,
        oi_delta_1h_pct=0.065,  # +6.5% >= +5.0%
        btc_1h_return_pct=0.005,
    )
    assert anomaly_long is not None
    assert anomaly_long.venue == VenueType.HYPERLIQUID
    assert anomaly_long.proposed_direction == SignalDirection.LONG
    assert anomaly_long.rvol_ratio == pytest.approx(3.0)

    # Reject LONG when overextended (> +8.0% above Daily VWAP)
    asset_overextended = asset_long.model_copy(
        update={"mid_px": Decimal("112.0"), "mark_px": Decimal("112.0")}
    )
    assert (
        gate1.evaluate_hyperliquid_asset(
            asset=asset_overextended,
            candles_15m=candles_long,
            oi_delta_1h_pct=0.065,
            btc_1h_return_pct=0.005,
        )
        is None
    )

    # Symmetric SHORT breakdown candidate (-2.5% below Daily VWAP, funding >= -0.005%)
    candles_short = _make_candles(
        count=21,
        base_price=Decimal("100.0"),
        last_close=Decimal("97.5"),
        base_volume=Decimal("1000.0"),
        last_volume=Decimal("2800.0"),
    )
    asset_short = asset_long.model_copy(
        update={
            "mid_px": Decimal("97.5"),
            "mark_px": Decimal("97.5"),
            "funding_hourly": -0.00001,
        }
    )
    anomaly_short = gate1.evaluate_hyperliquid_asset(
        asset=asset_short,
        candles_15m=candles_short,
        oi_delta_1h_pct=0.07,
        btc_1h_return_pct=-0.01,
    )
    assert anomaly_short is not None
    assert anomaly_short.proposed_direction == SignalDirection.SHORT


def test_gate1_polymarket_short_horizon_filter() -> None:
    gate1 = Gate1QuantFilter()
    valid_candidate = PolymarketCandidateDTO(
        market_id="703257",
        question="Will the Fed cut rates by 25bps tomorrow?",
        condition_id="0xabc123",
        yes_token_id="tok-yes-1",
        no_token_id="tok-no-1",
        yes_price=Decimal("0.42"),
        no_price=Decimal("0.58"),
        midpoint_yes=Decimal("0.42"),
        spread_yes=Decimal("0.02"),
        volume_usd=Decimal("85000"),
        hours_to_resolution=18.5,
        minimum_tick_size=Decimal("0.01"),
    )
    anomaly = gate1.evaluate_polymarket_market(valid_candidate)
    assert anomaly is not None
    assert anomaly.venue == VenueType.POLYMARKET
    assert anomaly.target_token_id == "tok-yes-1"
    assert anomaly.no_token_id == "tok-no-1"

    # Reject spread > $0.03
    wide_spread = valid_candidate.model_copy(update={"spread_yes": Decimal("0.05")})
    assert gate1.evaluate_polymarket_market(wide_spread) is None

    # Reject hours > 72
    long_horizon = valid_candidate.model_copy(update={"hours_to_resolution": 96.0})
    assert gate1.evaluate_polymarket_market(long_horizon) is None

    # Reject tail probability < 0.15
    tail_prob = valid_candidate.model_copy(update={"midpoint_yes": Decimal("0.08")})
    assert gate1.evaluate_polymarket_market(tail_prob) is None


@pytest.mark.asyncio
async def test_venue_clients_parsing_with_mock_transport() -> None:
    now_utc = datetime(2026, 11, 16, 8, 0, 0, tzinfo=timezone.utc)
    end_date_iso = (now_utc + timedelta(hours=24)).isoformat().replace("+00:00", "Z")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/info"):
            return httpx.Response(
                200,
                json=[
                    {
                        "universe": [
                            {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
                            {"name": "HYPE", "szDecimals": 2, "maxLeverage": 20},
                        ]
                    },
                    [
                        {
                            "dayNtlVlm": "500000000.0",
                            "funding": "0.0000125",
                            "openInterest": "12000.0",
                            "markPx": "90000.0",
                            "midPx": "90000.5",
                            "oraclePx": "90000.0",
                            "prevDayPx": "89000.0",
                            "impactPxs": ["89999.0", "90001.0"],
                        },
                        {
                            "dayNtlVlm": "25000000.0",
                            "funding": "0.0000100",
                            "openInterest": "850000.0",
                            "markPx": "25.40",
                            "midPx": "25.41",
                            "oraclePx": "25.39",
                            "prevDayPx": "24.00",
                            "impactPxs": ["25.40", "25.42"],
                        },
                    ],
                ],
            )
        if "/markets" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "99001",
                        "question": "Will ETH close above $3500 tomorrow?",
                        "conditionId": "0x99001",
                        "outcomes": '["Yes", "No"]',
                        "outcomePrices": '["0.52", "0.48"]',
                        "clobTokenIds": '["yes-token-99001", "no-token-99001"]',
                        "volume": "120000.50",
                        "endDate": end_date_iso,
                        "orderPriceMinTickSize": "0.01",
                        "closed": False,
                        "active": True,
                    }
                ],
            )
        if url.endswith("/spreads"):
            return httpx.Response(200, json={"yes-token-99001": "0.02"})
        if url.endswith("/midpoints"):
            return httpx.Response(200, json={"yes-token-99001": "0.52"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        settings = Settings()
        hl_client = HyperliquidClient(settings=settings, http_client=mock_http)
        ctxs = await hl_client.fetch_meta_and_asset_ctxs()
        assert len(ctxs) == 2
        assert ctxs[1].coin == "HYPE"
        assert ctxs[1].sz_decimals == 2

        pm_client = PolymarketClient(settings=settings, http_client=mock_http)
        candidates = await pm_client.discover_short_horizon_markets(now_utc=now_utc)
        assert len(candidates) == 1
        assert candidates[0].yes_token_id == "yes-token-99001"
        assert candidates[0].no_token_id == "no-token-99001"
        assert candidates[0].spread_yes == Decimal("0.02")
        assert candidates[0].midpoint_yes == Decimal("0.52")
