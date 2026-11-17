import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional
import httpx

from src.config.settings import Settings
from src.domain.dtos import ApprovedOrderDTO, PolymarketCandidateDTO
from src.domain.enums import ExecutionMode
from src.domain.interfaces import PolymarketVenueAdapter

logger = logging.getLogger(__name__)


class PolymarketClient(PolymarketVenueAdapter):
    """
    Production async client for Polymarket Gamma API & CLOB Batch endpoints.
    Strictly implements @docs/polymarket_api.md.
    """

    BATCH_LIMIT: int = 500

    def __init__(
        self,
        settings: Settings,
        http_client: Optional[httpx.AsyncClient] = None,
        max_retries: int = 3,
        base_backoff_sec: float = 0.5,
    ) -> None:
        self._settings = settings
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"Content-Type": "application/json"},
        )
        self._max_retries = max_retries
        self._base_backoff_sec = base_backoff_sec
        self._doh_cache: Dict[str, str] = {}

    async def resolve_host_via_doh(self, hostname: str) -> Optional[str]:
        """
        Resolves a hostname via configured DNS-over-HTTPS (DoH) endpoint
        (e.g. https://cloudflare-dns.com/dns-query) when local DNS is sinkholed.
        """
        if hostname in self._doh_cache:
            return self._doh_cache[hostname]

        doh_url = self._settings.custom_dns_doh_url
        if not doh_url:
            return None
        try:
            response = await self._client.get(
                doh_url,
                params={"name": hostname, "type": "A"},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
            answers = payload.get("Answer", []) if isinstance(payload, dict) else []
            for ans in answers:
                if isinstance(ans, dict) and ans.get("type") == 1 and ans.get("data"):
                    ip_str = str(ans["data"]).strip()
                    if ip_str and not ip_str.startswith("158.140."):
                        self._doh_cache[hostname] = ip_str
                        logger.info(
                            "[INFO] Resolved %s via DoH (%s) -> %s",
                            hostname,
                            doh_url,
                            ip_str,
                        )
                        return ip_str
        except Exception as exc:
            logger.warning(
                "[WARN] DoH resolution for %s via %s failed: %s",
                hostname,
                doh_url,
                str(exc) or repr(exc),
            )
        return None

    async def close(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def _request_json(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
    ) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                wait_sec = self._base_backoff_sec * (2**attempt)
                err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else repr(exc)
                logger.warning(
                    "[WARN] Polymarket API %s %s failed (attempt %d/%d): %s",
                    method,
                    url,
                    attempt + 1,
                    self._max_retries,
                    err_detail,
                )
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(wait_sec)
        err_final = f"{type(last_exc).__name__}: {last_exc}" if last_exc and str(last_exc) else repr(last_exc)
        raise RuntimeError(
            f"[ERROR] Polymarket API {method} {url} failed after {self._max_retries} attempts: {err_final}"
        )

    @staticmethod
    def parse_json_string_list(raw_field: Any) -> List[str]:
        """
        Safely parses Gamma API JSON-encoded array strings such as:
        outcomes='["Yes", "No"]', outcomePrices='["0.45", "0.55"]',
        clobTokenIds='["107505...", "730563..."]'.
        """
        if raw_field is None:
            return []
        if isinstance(raw_field, list):
            return [str(x) for x in raw_field]
        if isinstance(raw_field, str):
            stripped = raw_field.strip()
            if not stripped:
                return []
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                return []
        return []

    @staticmethod
    def _extract_yes_no_tokens_and_prices(
        market: Dict[str, Any],
    ) -> Optional[tuple[str, str, Decimal, Decimal]]:
        outcomes_raw = market.get("outcomes")
        if isinstance(outcomes_raw, dict):
            yes_obj = outcomes_raw.get("yes") or {}
            no_obj = outcomes_raw.get("no") or {}
            yes_token = str(yes_obj.get("tokenId") or yes_obj.get("token_id") or yes_obj.get("positionId") or yes_obj.get("position_id") or "")
            no_token = str(no_obj.get("tokenId") or no_obj.get("token_id") or no_obj.get("positionId") or no_obj.get("position_id") or "")
            prices = PolymarketClient.parse_json_string_list(market.get("outcomePrices"))
            yes_px = Decimal(prices[0]) if len(prices) >= 1 else Decimal("0.50")
            no_px = Decimal(prices[1]) if len(prices) >= 2 else Decimal("1.00") - yes_px
            if yes_token and no_token:
                return yes_token, no_token, yes_px, no_px

        outcomes = PolymarketClient.parse_json_string_list(outcomes_raw)
        token_ids = PolymarketClient.parse_json_string_list(market.get("clobTokenIds"))
        if not token_ids and isinstance(market.get("positionIds"), list):
            token_ids = [str(x) for x in market["positionIds"]]
        prices = PolymarketClient.parse_json_string_list(market.get("outcomePrices"))

        if len(token_ids) < 2:
            return None

        yes_idx = 0
        no_idx = 1
        if len(outcomes) >= 2:
            lowered = [o.strip().lower() for o in outcomes]
            if "yes" in lowered and "no" in lowered:
                yes_idx = lowered.index("yes")
                no_idx = lowered.index("no")

        yes_token = token_ids[yes_idx]
        no_token = token_ids[no_idx]

        yes_px = Decimal(prices[yes_idx]) if len(prices) > yes_idx else Decimal("0.50")
        no_px = Decimal(prices[no_idx]) if len(prices) > no_idx else (Decimal("1.00") - yes_px)
        return yes_token, no_token, yes_px, no_px

    @staticmethod
    def _compute_hours_to_resolution(
        market: Dict[str, Any],
        now_utc: datetime,
    ) -> Optional[float]:
        end_str = (
            market.get("endDate")
            or market.get("endDateIso")
            or market.get("end_date_iso")
        )
        if not end_str or not isinstance(end_str, str):
            return None
        normalized = end_str.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            end_dt = datetime.fromisoformat(normalized)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            delta_hours = (end_dt - now_utc).total_seconds() / 3600.0
            return delta_hours
        except ValueError:
            return None

    async def fetch_active_gamma_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Calls GET https://gamma-api.polymarket.com/markets?closed=false&active=true&limit=...
        """
        url = f"{self._settings.polymarket_gamma_url.rstrip('/')}/markets"
        params = {"closed": "false", "active": "true", "limit": str(limit)}
        data = await self._request_json("GET", url, params=params)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        if isinstance(data, dict) and isinstance(data.get("markets"), list):
            return [m for m in data["markets"] if isinstance(m, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [m for m in data["items"] if isinstance(m, dict)]
        return []

    async def fetch_spreads_batch(self, token_ids: List[str]) -> Dict[str, Decimal]:
        """
        Calls POST https://clob.polymarket.com/spreads with [{"token_id": ...}]
        in batches of up to 500 items per @docs/polymarket_api.md.
        """
        if not token_ids:
            return {}
        url = f"{self._settings.polymarket_clob_url.rstrip('/')}/spreads"
        result: Dict[str, Decimal] = {}
        for i in range(0, len(token_ids), self.BATCH_LIMIT):
            chunk = token_ids[i : i + self.BATCH_LIMIT]
            payload = [{"token_id": tid} for tid in chunk]
            resp = await self._request_json("POST", url, json_body=payload)
            if isinstance(resp, dict):
                for tid, val in resp.items():
                    if val is not None:
                        result[str(tid)] = Decimal(str(val))
        return result

    async def fetch_midpoints_batch(self, token_ids: List[str]) -> Dict[str, Decimal]:
        """
        Calls POST https://clob.polymarket.com/midpoints with [{"token_id": ...}]
        in batches of up to 500 items per @docs/polymarket_api.md.
        """
        if not token_ids:
            return {}
        url = f"{self._settings.polymarket_clob_url.rstrip('/')}/midpoints"
        result: Dict[str, Decimal] = {}
        for i in range(0, len(token_ids), self.BATCH_LIMIT):
            chunk = token_ids[i : i + self.BATCH_LIMIT]
            payload = [{"token_id": tid} for tid in chunk]
            resp = await self._request_json("POST", url, json_body=payload)
            if isinstance(resp, dict):
                for tid, val in resp.items():
                    if val is not None:
                        result[str(tid)] = Decimal(str(val))
        return result

    async def fetch_order_book(self, token_id: str) -> Dict[str, Any]:
        """
        Calls GET https://clob.polymarket.com/book?token_id=<token_id>.
        """
        url = f"{self._settings.polymarket_clob_url.rstrip('/')}/book"
        resp = await self._request_json("GET", url, params={"token_id": token_id})
        return dict(resp) if isinstance(resp, dict) else {}

    async def discover_short_horizon_markets(
        self,
        now_utc: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[PolymarketCandidateDTO]:
        """
        Discovers active Polymarket markets via Gamma API and enriches them
        with live CLOB batch midpoints and spreads.
        """
        ref_now = now_utc or datetime.now(timezone.utc)
        raw_markets = await self.fetch_active_gamma_markets(limit=limit)

        preliminary: List[tuple[Dict[str, Any], str, str, Decimal, Decimal, float, Decimal, Decimal]] = []
        yes_tokens: List[str] = []

        for m in raw_markets:
            if m.get("closed") is True or m.get("active") is False:
                continue
            hours_left = self._compute_hours_to_resolution(m, ref_now)
            if hours_left is None or not (6.0 <= hours_left <= 72.0):
                continue

            vol_raw = m.get("volumeNum") if m.get("volumeNum") is not None else m.get("volume", "0")
            try:
                volume_usd = Decimal(str(vol_raw))
            except Exception:
                continue
            if volume_usd < Decimal("25000"):
                continue

            extracted = self._extract_yes_no_tokens_and_prices(m)
            if extracted is None:
                continue
            yes_tid, no_tid, yes_px, no_px = extracted

            tick_raw = (
                m.get("orderPriceMinTickSize")
                or m.get("minimum_tick_size")
                or m.get("tickSize")
                or "0.01"
            )
            tick_size = Decimal(str(tick_raw))

            preliminary.append((m, yes_tid, no_tid, yes_px, no_px, hours_left, volume_usd, tick_size))
            yes_tokens.append(yes_tid)

        if not preliminary:
            return []

        spreads_map = await self.fetch_spreads_batch(yes_tokens)
        midpoints_map = await self.fetch_midpoints_batch(yes_tokens)

        candidates: List[PolymarketCandidateDTO] = []
        for m, yes_tid, no_tid, yes_px, no_px, hours_left, volume_usd, tick_size in preliminary:
            spread_yes = spreads_map.get(yes_tid)
            if spread_yes is None:
                spread_Raw = m.get("spread")
                spread_yes = Decimal(str(spread_Raw)) if spread_Raw is not None else Decimal("1.00")

            midpoint_yes = midpoints_map.get(yes_tid, yes_px)
            market_id = str(m.get("id") or m.get("conditionId") or yes_tid)
            question = str(m.get("question") or m.get("title") or market_id)
            condition_id = str(m["conditionId"]) if m.get("conditionId") else None

            candidates.append(
                PolymarketCandidateDTO(
                    market_id=market_id,
                    question=question,
                    condition_id=condition_id,
                    yes_token_id=yes_tid,
                    no_token_id=no_tid,
                    yes_price=yes_px,
                    no_price=no_px,
                    midpoint_yes=midpoint_yes,
                    spread_yes=spread_yes,
                    volume_usd=volume_usd,
                    hours_to_resolution=hours_left,
                    minimum_tick_size=tick_size,
                )
            )
        return candidates

    async def place_order(self, order: ApprovedOrderDTO) -> Dict[str, object]:
        """
        Executes an ApprovedOrderDTO on Polymarket CLOB via py-clob-client in live mode,
        or returns a deterministic paper fill in PAPER mode.
        """
        token_id = order.target_token_id or order.symbol_or_market_id
        tick = order.sz_decimals_or_tick if order.sz_decimals_or_tick > Decimal("0") else Decimal("0.01")
        price_rounded = float(order.entry_price_limit.quantize(tick, rounding=ROUND_DOWN))
        size_rounded = float(order.position_size_units.quantize(Decimal("0.01"), rounding=ROUND_DOWN))

        if (
            self._settings.execution_mode == ExecutionMode.PAPER
            or not self._settings.polymarket_private_key
        ):
            logger.info(
                "[ORDER] PAPER fill on POLYMARKET: %s token=%s sz=%s px=%s",
                order.direction.value,
                token_id,
                size_rounded,
                price_rounded,
            )
            return {
                "status": "ok",
                "mode": "PAPER",
                "order_id": order.order_id,
                "token_id": token_id,
                "direction": order.direction.value,
                "size": size_rounded,
                "price": price_rounded,
            }

        from py_clob_client.client import ClobClient  # type: ignore[import-untyped]
        from py_clob_client.clob_types import OrderArgs, OrderType  # type: ignore[import-untyped]
        from py_clob_client.order_builder.constants import BUY  # type: ignore[import-untyped]

        def _submit_sync() -> Any:
            clob_client = ClobClient(
                host=self._settings.polymarket_clob_url,
                key=self._settings.polymarket_private_key,
                chain_id=137,
                funder=self._settings.polymarket_funder_address,
            )
            clob_client.set_api_creds(clob_client.create_or_derive_api_creds())
            order_args = OrderArgs(
                price=price_rounded,
                size=size_rounded,
                side=BUY,
                token_id=token_id,
            )
            signed_order = clob_client.create_order(order_args)
            return clob_client.post_order(signed_order, OrderType.GTC)

        live_resp = await asyncio.to_thread(_submit_sync)
        logger.info(
            "[ORDER] LIVE order submitted to POLYMARKET for %s: %s",
            token_id,
            live_resp,
        )
        return {"status": "ok", "mode": "LIVE", "clob_response": live_resp}
