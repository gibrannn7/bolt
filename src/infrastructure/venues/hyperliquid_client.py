import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional
import httpx

from src.config.settings import Settings
from src.domain.dtos import (
    ApprovedOrderDTO,
    CandleDTO,
    HyperliquidAssetContextDTO,
    OISnapshotDTO,
)
from src.domain.enums import ExecutionMode, SignalDirection
from src.domain.interfaces import HyperliquidVenueAdapter
from src.infrastructure.db.repositories import OISnapshotRepository

logger = logging.getLogger(__name__)


class HyperliquidClient(HyperliquidVenueAdapter):
    """
    Production async client for Hyperliquid Info & Exchange endpoints.
    Strictly implements @docs/hyperliquid_api.md.
    """

    def __init__(
        self,
        settings: Settings,
        oi_repository: Optional[OISnapshotRepository] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = 3,
        base_backoff_sec: float = 0.5,
    ) -> None:
        self._settings = settings
        self._oi_repo = oi_repository
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"Content-Type": "application/json"},
        )
        self._max_retries = max_retries
        self._base_backoff_sec = base_backoff_sec
        self._candle_semaphore = asyncio.Semaphore(3)

    async def close(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def _post_info(self, payload: Dict[str, Any]) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.post(
                    self._settings.hyperliquid_info_url,
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                wait_sec = self._base_backoff_sec * (2**attempt)
                err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else repr(exc)
                logger.warning(
                    "[WARN] Hyperliquid Info API call failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries,
                    err_detail,
                )
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(wait_sec)
        err_final = f"{type(last_exc).__name__}: {last_exc}" if last_exc and str(last_exc) else repr(last_exc)
        raise RuntimeError(
            f"[ERROR] Hyperliquid Info API failed after {self._max_retries} attempts: {err_final}"
        )

    async def fetch_meta_and_asset_ctxs(
        self,
        dex: str = "",
    ) -> List[HyperliquidAssetContextDTO]:
        """
        Calls POST https://api.hyperliquid.xyz/info with {"type": "metaAndAssetCtxs"}.
        Parses universe metadata and live asset contexts into HyperliquidAssetContextDTOs.
        """
        payload: Dict[str, Any] = {"type": "metaAndAssetCtxs"}
        if dex:
            payload["dex"] = dex

        data = await self._post_info(payload)
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError("[ERROR] Unexpected metaAndAssetCtxs response structure")

        meta_block = data[0]
        ctxs_block = data[1]
        universe = meta_block.get("universe", []) if isinstance(meta_block, dict) else []
        if not isinstance(ctxs_block, list):
            raise ValueError("[ERROR] assetCtxs block is not a list")

        results: List[HyperliquidAssetContextDTO] = []
        for idx, (u_item, ctx_item) in enumerate(zip(universe, ctxs_block)):
            if not isinstance(u_item, dict) or not isinstance(ctx_item, dict):
                continue
            if u_item.get("isDelisted", False):
                continue

            coin = str(u_item.get("name", ""))
            if not coin:
                continue

            sz_decimals = int(u_item.get("szDecimals", 2))
            max_leverage = int(u_item.get("maxLeverage", 1))

            day_ntl_vlm = Decimal(str(ctx_item.get("dayNtlVlm") or "0"))
            funding_hourly = float(ctx_item.get("funding") or 0.0)
            open_interest = float(ctx_item.get("openInterest") or 0.0)
            mark_px = Decimal(str(ctx_item.get("markPx") or "0"))
            mid_raw = ctx_item.get("midPx")
            mid_px = Decimal(str(mid_raw)) if mid_raw is not None else mark_px
            oracle_px = Decimal(str(ctx_item.get("oraclePx") or mark_px))
            prev_day_px = Decimal(str(ctx_item.get("prevDayPx") or mark_px))

            impact_pxs = ctx_item.get("impactPxs")
            impact_bid: Optional[Decimal] = None
            impact_ask: Optional[Decimal] = None
            if isinstance(impact_pxs, list) and len(impact_pxs) >= 2:
                if impact_pxs[0] is not None:
                    impact_bid = Decimal(str(impact_pxs[0]))
                if impact_pxs[1] is not None:
                    impact_ask = Decimal(str(impact_pxs[1]))

            results.append(
                HyperliquidAssetContextDTO(
                    coin=coin,
                    asset_index=idx,
                    sz_decimals=sz_decimals,
                    max_leverage=max_leverage,
                    day_ntl_vlm=day_ntl_vlm,
                    funding_hourly=funding_hourly,
                    open_interest=open_interest,
                    mark_px=mark_px,
                    mid_px=mid_px,
                    oracle_px=oracle_px,
                    prev_day_px=prev_day_px,
                    impact_bid_px=impact_bid,
                    impact_ask_px=impact_ask,
                )
            )
        return results

    async def fetch_candles(
        self,
        coin: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> List[CandleDTO]:
        """
        Calls POST https://api.hyperliquid.xyz/info with {"type": "candleSnapshot", ...}.
        Strictly throttled via asyncio.Semaphore(3) to prevent HTTP 429 rate limits.
        """
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        }
        async with self._candle_semaphore:
            raw_candles = await self._post_info(payload)
        if not isinstance(raw_candles, list):
            return []

        candles: List[CandleDTO] = []
        for item in raw_candles:
            if not isinstance(item, dict):
                continue
            candles.append(
                CandleDTO(
                    timestamp_open_ms=int(item.get("t", 0)),
                    timestamp_close_ms=int(item.get("T", 0)),
                    symbol=str(item.get("s", coin)),
                    interval=str(item.get("i", interval)),
                    open=Decimal(str(item.get("o", "0"))),
                    high=Decimal(str(item.get("h", "0"))),
                    low=Decimal(str(item.get("l", "0"))),
                    close=Decimal(str(item.get("c", "0"))),
                    volume=Decimal(str(item.get("v", "0"))),
                    num_trades=int(item.get("n", 0)),
                )
            )
        candles.sort(key=lambda c: c.timestamp_open_ms)
        return candles

    async def fetch_clearinghouse_state(self, user_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Calls POST https://api.hyperliquid.xyz/info with {"type": "clearinghouseState", "user": ...}.
        """
        address = user_address or self._settings.hyperliquid_wallet_address
        payload = {
            "type": "clearinghouseState",
            "user": address,
        }
        data = await self._post_info(payload)
        return dict(data) if isinstance(data, dict) else {}

    async def record_oi_snapshots_and_get_deltas(
        self,
        assets: List[HyperliquidAssetContextDTO],
        current_epoch_ms: Optional[int] = None,
    ) -> Dict[str, Optional[float]]:
        """
        Stores 5-minute Open Interest snapshots into SQLite WAL `hl_oi_snapshots`,
        prunes snapshots older than 24h, and computes 1h OI delta % for each coin.
        """
        if self._oi_repo is None:
            return {asset.coin: None for asset in assets}

        now_ms = current_epoch_ms if current_epoch_ms is not None else int(time.time() * 1000)
        snapshots = [
            OISnapshotDTO(
                coin=asset.coin,
                timestamp_epoch_ms=now_ms,
                open_interest=asset.open_interest,
                mark_px=float(asset.mark_px),
            )
            for asset in assets
        ]
        await self._oi_repo.insert_snapshots_bulk(snapshots)
        await self._oi_repo.retain_recent_window(now_ms)

        deltas: Dict[str, Optional[float]] = {}
        for asset in assets:
            delta = await self._oi_repo.calculate_oi_delta_1h_pct(
                coin=asset.coin,
                current_oi=asset.open_interest,
                current_epoch_ms=now_ms,
            )
            deltas[asset.coin] = delta
        return deltas

    @staticmethod
    def quantize_size(size: Decimal, sz_decimals_or_tick: Decimal) -> float:
        if sz_decimals_or_tick >= Decimal("1"):
            decimals = int(sz_decimals_or_tick)
            quantum = Decimal("10") ** (-decimals) if decimals > 0 else Decimal("1")
        else:
            quantum = sz_decimals_or_tick
        rounded = size.quantize(quantum, rounding=ROUND_DOWN)
        return float(rounded)

    async def place_order(self, order: ApprovedOrderDTO) -> Dict[str, object]:
        """
        Executes an ApprovedOrderDTO on Hyperliquid via official SDK when in live mode,
        or returns a deterministic paper fill in PAPER mode.
        """
        is_buy = order.direction == SignalDirection.LONG
        rounded_sz = self.quantize_size(order.position_size_units, order.sz_decimals_or_tick)
        limit_px = float(order.entry_price_limit)

        if (
            self._settings.execution_mode == ExecutionMode.PAPER
            or not self._settings.hyperliquid_private_key
        ):
            logger.info(
                "[ORDER] PAPER fill on HYPERLIQUID: %s %s sz=%s px=%s",
                order.direction.value,
                order.symbol_or_market_id,
                rounded_sz,
                limit_px,
            )
            return {
                "status": "ok",
                "mode": "PAPER",
                "order_id": order.order_id,
                "symbol": order.symbol_or_market_id,
                "is_buy": is_buy,
                "size": rounded_sz,
                "limit_px": limit_px,
            }

        from eth_account import Account
        from hyperliquid.exchange import Exchange  # type: ignore[import-untyped]
        from hyperliquid.utils import constants  # type: ignore[import-untyped]

        account = Account.from_key(self._settings.hyperliquid_private_key)
        exchange = Exchange(account, constants.MAINNET_API_URL)
        sdk_response = await asyncio.to_thread(
            exchange.order,
            order.symbol_or_market_id,
            is_buy,
            rounded_sz,
            limit_px,
            {"limit": {"tif": "Gtc"}},
        )
        logger.info(
            "[ORDER] LIVE order submitted to HYPERLIQUID for %s: %s",
            order.symbol_or_market_id,
            sdk_response,
        )
        return {"status": "ok", "mode": "LIVE", "sdk_response": sdk_response}
