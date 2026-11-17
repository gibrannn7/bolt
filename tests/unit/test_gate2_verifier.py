import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
import httpx
import pytest

from src.config.settings import Settings
from src.domain.dtos import (
    AIVerificationResultDTO,
    CatalystExtractionDTO,
    MarketAnomalyDTO,
)
from src.domain.enums import SignalDirection, VenueType
from src.infrastructure.llm.prompts import build_step2b_masked_user_payload
from src.infrastructure.llm.router import XAIResponsesRouter
from src.use_cases.gate2_ai_verifier import Gate2AIVerifier


def _sample_anomaly(
    anomaly_id: str = "anom-hl-hype",
    rvol_ratio: float = 3.2,
    price: Decimal = Decimal("42.75"),
) -> MarketAnomalyDTO:
    return MarketAnomalyDTO(
        anomaly_id=anomaly_id,
        timestamp_utc=datetime(2026, 11, 16, 7, 30, 0, tzinfo=timezone.utc),
        venue=VenueType.HYPERLIQUID,
        symbol_or_market_id="HYPE",
        asset_name_or_question="Hyperliquid Perpetuals",
        sz_decimals_or_tick=Decimal("0.01"),
        current_price=price,
        rvol_ratio=rvol_ratio,
        oi_delta_1h_pct=0.085,
        funding_rate_hourly=0.000015,
        vwap_distance_pct=0.032,
        btc_1h_return_pct=0.008,
        atr_14=Decimal("1.25"),
        bid_ask_spread=Decimal("0.01"),
        proposed_direction=SignalDirection.LONG,
    )


def test_step2a_and_step2b_payload_construction_and_price_masking() -> None:
    anom_normal = _sample_anomaly(rvol_ratio=3.2, price=Decimal("987.65"))
    step2a_payload = XAIResponsesRouter.build_step2a_request_payload(anom_normal)

    assert step2a_payload["model"] == "grok-4.7"
    assert step2a_payload["reasoning"] == {"effort": "low"}
    assert step2a_payload["tools"] == [{"type": "x_search"}, {"type": "web_search"}]
    assert step2a_payload["text"]["format"]["name"] == "catalyst_extraction_output"
    assert step2a_payload["text"]["format"]["strict"] is True

    catalyst = CatalystExtractionDTO(
        catalyst_found=True,
        primary_catalyst_summary="Protocol buyback increased by 50%",
        earliest_post_timestamp_utc="2026-11-16T07:10:00Z",
        age_in_minutes=20,
        verifiable_source_urls=["https://x.com/HyperliquidX/status/123456"],
        is_recycled_or_old_news=False,
    )

    masked_str = build_step2b_masked_user_payload(anom_normal, catalyst)
    assert "987.65" not in masked_str
    assert "current_price" not in masked_str

    step2b_payload_high = XAIResponsesRouter.build_step2b_request_payload(
        anom_normal, catalyst
    )
    assert step2b_payload_high["model"] == "grok-4.7"
    assert step2b_payload_high["reasoning"] == {"effort": "high"}
    assert "tools" not in step2b_payload_high
    assert step2b_payload_high["text"]["format"]["name"] == "ai_verification_result"

    # RVOL >= 4.0 upgrades reasoning effort to xhigh
    anom_extreme = _sample_anomaly(rvol_ratio=4.5, price=Decimal("987.65"))
    step2b_payload_xhigh = XAIResponsesRouter.build_step2b_request_payload(
        anom_extreme, catalyst
    )
    assert step2b_payload_xhigh["reasoning"] == {"effort": "xhigh"}


@pytest.mark.asyncio
async def test_gate2_verifier_three_historical_anomalies() -> None:
    """
    Feeds 3 historical anomalies into Gate2AIVerifier:
    1. Strong fresh catalyst (<120m old, high confidence >= 78) -> PASSES
    2. Old/recycled catalyst (age_in_minutes=150 > 120) -> VETOED
    3. Unverified/missing catalyst (catalyst_found=False) -> VETOED
    """
    captured_requests: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(body)
        schema_name = body["text"]["format"]["name"]
        user_text = body["input"][1]["content"]

        if schema_name == "catalyst_extraction_output":
            if "anom-1-fresh" in user_text or "SOL" in user_text:
                out = {
                    "catalyst_found": True,
                    "primary_catalyst_summary": "SEC approves spot ETF options trading",
                    "earliest_post_timestamp_utc": "2026-11-16T07:05:00Z",
                    "age_in_minutes": 25,
                    "verifiable_source_urls": ["https://x.com/news/1"],
                    "is_recycled_or_old_news": False,
                }
            elif "ETH" in user_text:
                out = {
                    "catalyst_found": True,
                    "primary_catalyst_summary": "Recycled rumour from yesterday",
                    "earliest_post_timestamp_utc": "2026-11-16T04:50:00Z",
                    "age_in_minutes": 160,
                    "verifiable_source_urls": ["https://x.com/spam/2"],
                    "is_recycled_or_old_news": True,
                }
            else:
                out = {
                    "catalyst_found": False,
                    "primary_catalyst_summary": "No news found",
                    "earliest_post_timestamp_utc": "",
                    "age_in_minutes": 999,
                    "verifiable_source_urls": [],
                    "is_recycled_or_old_news": False,
                }
            return httpx.Response(200, json={"output_text": json.dumps(out)})

        # Step 2B response using nested message output structure
        parsed_user = json.loads(user_text)
        assert "current_price" not in parsed_user["gate1_metrics_price_masked"]
        anom_id = parsed_user["gate1_metrics_price_masked"]["anomaly_id"]

        if anom_id == "anom-1-fresh":
            verif = {
                "anomaly_id": anom_id,
                "primary_catalyst_summary": "SEC approves spot ETF options trading",
                "source_timestamps_verified": True,
                "bull_thesis_score": 90,
                "red_team_flaws_detected": ["Minor short-term basis expansion"],
                "red_team_veto": False,
                "red_team_penalty": 8,
                "estimated_win_probability": 0.74,
                "final_confidence_score": 82,
            }
        elif anom_id == "anom-2-stale":
            verif = {
                "anomaly_id": anom_id,
                "primary_catalyst_summary": "Recycled rumour from yesterday",
                "source_timestamps_verified": True,
                "bull_thesis_score": 85,
                "red_team_flaws_detected": ["Recycled news older than 120m"],
                "red_team_veto": False,
                "red_team_penalty": 5,
                "estimated_win_probability": 0.55,
                "final_confidence_score": 80,
            }
        else:
            verif = {
                "anomaly_id": anom_id,
                "primary_catalyst_summary": "No news found",
                "source_timestamps_verified": False,
                "bull_thesis_score": 40,
                "red_team_flaws_detected": ["No verifiable catalyst"],
                "red_team_veto": True,
                "red_team_penalty": 40,
                "estimated_win_probability": 0.30,
                "final_confidence_score": 0,
            }

        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(verif)}],
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        settings = Settings(XAI_API_KEY="test-xai-key", GEMINI_API_KEY="")
        router = XAIResponsesRouter(settings=settings, http_client=mock_http)
        verifier = Gate2AIVerifier(llm_router=router)

        anom1 = _sample_anomaly(anomaly_id="anom-1-fresh").model_copy(
            update={"symbol_or_market_id": "SOL"}
        )
        res1, passed1 = await verifier.verify_anomaly(anom1)
        assert passed1 is True
        assert res1.red_team_veto is False
        assert res1.final_confidence_score == 82

        anom2 = _sample_anomaly(anomaly_id="anom-2-stale").model_copy(
            update={"symbol_or_market_id": "ETH"}
        )
        res2, passed2 = await verifier.verify_anomaly(anom2)
        assert passed2 is False
        assert res2.red_team_veto is True
        assert res2.source_timestamps_verified is False

        anom3 = _sample_anomaly(anomaly_id="anom-3-missing").model_copy(
            update={"symbol_or_market_id": "DOGE"}
        )
        res3, passed3 = await verifier.verify_anomaly(anom3)
        assert passed3 is False
        assert res3.red_team_veto is True
        assert res3.final_confidence_score == 0


@pytest.mark.asyncio
async def test_gate2_fallback_quant_only_mode() -> None:
    """
    Verifies that when XAI_API_KEY is empty or 'MOCK' during PAPER mode,
    Gate 2 runs deterministically in FALLBACK_QUANT_ONLY mode with zero HTTP calls.
    """
    settings_mock = Settings(XAI_API_KEY="MOCK")
    router = XAIResponsesRouter(settings=settings_mock)
    verifier = Gate2AIVerifier(llm_router=router)

    assert verifier.is_fallback_quant_only_mode() is True
    anom = _sample_anomaly(anomaly_id="anom-fallback-1", rvol_ratio=3.0)
    result, passed = await verifier.verify_anomaly(anom)
    assert passed is True
    assert result.red_team_veto is False
    assert result.final_confidence_score >= 78
    assert "FALLBACK_QUANT_ONLY" in result.primary_catalyst_summary
    await router.close()


@pytest.mark.asyncio
async def test_gate2_hybrid_grok_step2a_and_gemini_decision_1_step2b() -> None:
    """
    Tests the primary hybrid Gate 2 architecture:
    - Step 2A: xAI grok-4.7 extracts catalyst, bull_arguments, bear_flaws_detected, audit_reasoning_trace
    - Step 2B: Google gemini-decision-1 (`POST /v1beta/decisions`) evaluates calibrated probabilities
      with price masked (`is_fresh_and_verifiable`, `is_bull_trap_or_manipulation`, `win_probability`, `thesis_quality_rubric`)
    """
    captured_urls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        captured_urls.append(url)
        body = json.loads(request.content.decode("utf-8"))

        if url.endswith("/v1/responses"):
            out = {
                "catalyst_found": True,
                "primary_catalyst_summary": "Layer-1 mainnet upgrade and fee burn activated 20m ago",
                "bull_arguments": [
                    "Verified core dev announcement on X",
                    "Fresh Open Interest +8.5% inflow",
                ],
                "bear_flaws_detected": ["Minor short-term funding uptick"],
                "audit_reasoning_trace": "Cross-checked official protocol handle and on-chain block timestamp.",
                "earliest_post_timestamp_utc": "2026-11-16T07:10:00Z",
                "age_in_minutes": 20,
                "verifiable_source_urls": ["https://x.com/HyperliquidX/status/1001"],
                "is_recycled_or_old_news": False,
            }
            return httpx.Response(200, json={"output_text": json.dumps(out)})

        if url.endswith("/v1beta/decisions"):
            assert request.headers.get("x-goog-api-key") == "test-gemini-key"
            assert body["model"] == "gemini-decision-1"
            assert "current_price" not in body["input"]
            assert "42.75" not in body["input"]
            assert "is_fresh_and_verifiable" in body["questions"]
            assert "is_bull_trap_or_manipulation" in body["questions"]
            assert "win_probability" in body["questions"]
            assert "thesis_quality_rubric" in body["questions"]

            input_obj = json.loads(body["input"])
            anom_id = input_obj["gate1_metrics_price_masked"]["anomaly_id"]
            if anom_id == "anom-gemini-pass":
                return httpx.Response(
                    200,
                    json={
                        "model": "gemini-decision-1",
                        "answers": {
                            "is_fresh_and_verifiable": {"probability": 0.91},
                            "is_bull_trap_or_manipulation": {"probability": 0.10},
                            "win_probability": {"probability": 0.725},
                            "thesis_quality_rubric": {"score": 88.0},
                        },
                    },
                )
            # Trap probability >= 0.45 triggers immediate red_team_veto
            return httpx.Response(
                200,
                json={
                    "model": "gemini-decision-1",
                    "answers": {
                        "is_fresh_and_verifiable": {"probability": 0.75},
                        "is_bull_trap_or_manipulation": {"probability": 0.52},
                        "win_probability": {"probability": 0.48},
                        "thesis_quality_rubric": {"score": 82.0},
                    },
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        settings = Settings(
            XAI_API_KEY="test-xai-key",
            GEMINI_API_KEY="test-gemini-key",
        )
        router = XAIResponsesRouter(settings=settings, http_client=mock_http)
        verifier = Gate2AIVerifier(llm_router=router)

        anom_pass = _sample_anomaly(anomaly_id="anom-gemini-pass", price=Decimal("42.75"))
        res_pass, passed = await verifier.verify_anomaly(anom_pass)
        assert passed is True
        assert res_pass.red_team_veto is False
        # bull_thesis_score = round(88.0) = 88, penalty = round(0.10 * 50) = 5 -> final = 83
        assert res_pass.bull_thesis_score == 88
        assert res_pass.red_team_penalty == 5
        assert res_pass.final_confidence_score == 83
        assert res_pass.estimated_win_probability == pytest.approx(0.725)

        anom_trap = _sample_anomaly(anomaly_id="anom-gemini-trap", price=Decimal("42.75"))
        res_trap, passed_trap = await verifier.verify_anomaly(anom_trap)
        assert passed_trap is False
        assert res_trap.red_team_veto is True
        assert any("bull-trap/manipulation" in f for f in res_trap.red_team_flaws_detected)
