import asyncio
import json
import logging
from typing import Any, Dict, Optional
import httpx

from src.config.settings import Settings
from src.domain.dtos import (
    AIVerificationResultDTO,
    CatalystExtractionDTO,
    GeminiDecisionOutputDTO,
    MarketAnomalyDTO,
)
from src.domain.interfaces import LLMRouterAdapter
from src.infrastructure.llm.prompts import (
    GEMINI_DECISION_QUESTIONS,
    STEP2A_JSON_SCHEMA,
    STEP2A_SYSTEM_PROMPT,
    STEP2B_JSON_SCHEMA,
    STEP2B_SYSTEM_PROMPT,
    build_step2a_user_prompt,
    build_step2b_masked_user_payload,
)

logger = logging.getLogger(__name__)


class XAIResponsesRouter(LLMRouterAdapter):
    """
    Hybrid AI router supporting:
    - Step 2A: xAI Grok-4.7 Responses API (`POST https://api.x.ai/v1/responses`) with live `x_search` & `web_search`
    - Step 2B (Primary): Google Gemini Decision 1 (`POST https://generativelanguage.googleapis.com/v1beta/decisions`)
    - Step 2B (Fallback): xAI Grok-4.7 Red-Team Prosecutor (`effort="high"` or `"xhigh"`, tools disabled)
    Strictly implements @docs/xai_grok_api.md and @docs/gemini_decision_api.md.
    """

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
            timeout=httpx.Timeout(45.0, connect=10.0),
        )
        self._max_retries = max_retries
        self._base_backoff_sec = base_backoff_sec

    async def close(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    def _xai_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.xai_api_key}",
            "Content-Type": "application/json",
        }

    def _gemini_headers(self) -> Dict[str, str]:
        return {
            "x-goog-api-key": self._settings.gemini_api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def extract_output_text(response_json: Dict[str, Any]) -> str:
        """
        Extracts the structured JSON text from xAI Responses API output per Section 4 of @docs/xai_grok_api.md.
        """
        top_level_text = response_json.get("output_text")
        if isinstance(top_level_text, str) and top_level_text.strip():
            return top_level_text.strip()

        output_items = response_json.get("output")
        if isinstance(output_items, list):
            for item in output_items:
                if isinstance(item, dict) and item.get("type") == "message":
                    content_list = item.get("content")
                    if isinstance(content_list, list) and len(content_list) > 0:
                        first_block = content_list[0]
                        if isinstance(first_block, dict) and isinstance(
                            first_block.get("text"), str
                        ):
                            return first_block["text"].strip()

        raise ValueError("[ERROR] Could not extract output text from xAI Responses payload")

    async def _post_json(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        provider_label: str,
    ) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError(f"[ERROR] {provider_label} response JSON is not an object")
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                wait_sec = self._base_backoff_sec * (2**attempt)
                err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else repr(exc)
                logger.warning(
                    "[WARN] %s API request failed (attempt %d/%d): %s",
                    provider_label,
                    attempt + 1,
                    self._max_retries,
                    err_detail,
                )
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(wait_sec)
        err_final = f"{type(last_exc).__name__}: {last_exc}" if last_exc and str(last_exc) else repr(last_exc)
        raise RuntimeError(
            f"[ERROR] {provider_label} API failed after {self._max_retries} attempts: {err_final}"
        )

    @staticmethod
    def build_step2a_request_payload(
        anomaly: MarketAnomalyDTO,
        model: str = "grok-4.7",
        effort: str = "low",
    ) -> Dict[str, Any]:
        return {
            "model": model,
            "reasoning": {"effort": effort},
            "tools": [
                {"type": "x_search"},
                {"type": "web_search"},
            ],
            "input": [
                {"role": "system", "content": STEP2A_SYSTEM_PROMPT},
                {"role": "user", "content": build_step2a_user_prompt(anomaly)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "catalyst_extraction_output",
                    "strict": True,
                    "schema": STEP2A_JSON_SCHEMA,
                }
            },
        }

    @staticmethod
    def build_step2b_request_payload(
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
        model: str = "grok-4.7",
    ) -> Dict[str, Any]:
        effort = "xhigh" if anomaly.rvol_ratio >= 4.0 else "high"
        masked_user_content = build_step2b_masked_user_payload(anomaly, catalyst)
        return {
            "model": model,
            "reasoning": {"effort": effort},
            "input": [
                {"role": "system", "content": STEP2B_SYSTEM_PROMPT},
                {"role": "user", "content": masked_user_content},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ai_verification_result",
                    "strict": True,
                    "schema": STEP2B_JSON_SCHEMA,
                }
            },
        }

    @staticmethod
    def build_gemini_decision_request_payload(
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
        model: str = "gemini-decision-1",
    ) -> Dict[str, Any]:
        """
        Builds the exact Step 2B request payload for Google's `POST /v1beta/decisions`
        endpoint with price-masked Gate 1 metrics and Step 2A Grok bull/bear evidence.
        """
        combined_dossier = build_step2b_masked_user_payload(anomaly, catalyst)
        return {
            "model": model,
            "input": combined_dossier,
            "questions": GEMINI_DECISION_QUESTIONS,
        }

    @staticmethod
    def _extract_numeric_answer(
        container: Dict[str, Any],
        key: str,
        default: float,
    ) -> float:
        raw = container.get(key)
        if raw is None:
            return default
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, dict):
            for field_name in (
                "probability",
                "score",
                "expected_score",
                "value",
                "yes_probability",
                "answer",
            ):
                val = raw.get(field_name)
                if isinstance(val, (int, float)):
                    return float(val)
            # If a rubric distribution dict is provided without top-level score, compute expected value
            dist = raw.get("distribution") or raw.get("probabilities")
            if isinstance(dist, dict) and dist:
                total_w = 0.0
                weighted_sum = 0.0
                for k, p in dist.items():
                    try:
                        anchor = float(k)
                        prob = float(p)
                        weighted_sum += anchor * prob
                        total_w += prob
                    except (ValueError, TypeError):
                        continue
                if total_w > 0.0:
                    return weighted_sum / total_w
        return default

    @classmethod
    def parse_gemini_decision_response(
        cls,
        response_json: Dict[str, Any],
    ) -> GeminiDecisionOutputDTO:
        """
        Safely parses both REST and SDK response structures from `gemini-decision-1`.
        """
        answers_block: Dict[str, Any] = response_json
        for block_key in ("answers", "decisions", "results", "questions", "output"):
            candidate = response_json.get(block_key)
            if isinstance(candidate, dict):
                answers_block = candidate
                break

        p_fresh = cls._extract_numeric_answer(
            answers_block, "is_fresh_and_verifiable", 0.0
        )
        p_trap = cls._extract_numeric_answer(
            answers_block, "is_bull_trap_or_manipulation", 1.0
        )
        p_win = cls._extract_numeric_answer(answers_block, "win_probability", 0.5)
        rubric_score = cls._extract_numeric_answer(
            answers_block, "thesis_quality_rubric", 0.0
        )

        return GeminiDecisionOutputDTO(
            is_fresh_and_verifiable_prob=max(0.0, min(1.0, p_fresh)),
            is_bull_trap_or_manipulation_prob=max(0.0, min(1.0, p_trap)),
            win_probability=max(0.0, min(1.0, p_win)),
            thesis_quality_score=max(0.0, min(100.0, rubric_score)),
            raw_response_json=json.dumps(response_json, sort_keys=True),
        )

    async def extract_catalyst_step2a(
        self,
        anomaly: MarketAnomalyDTO,
    ) -> CatalystExtractionDTO:
        payload = self.build_step2a_request_payload(
            anomaly=anomaly,
            model=self._settings.xai_model,
            effort=self._settings.xai_search_effort,
        )
        response_json = await self._post_json(
            url=self._settings.xai_responses_url,
            headers=self._xai_headers(),
            payload=payload,
            provider_label="xAI Responses Step 2A",
        )
        raw_text = self.extract_output_text(response_json)
        return CatalystExtractionDTO.model_validate_json(raw_text)

    async def call_gemini_decision_step2b(
        self,
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
    ) -> GeminiDecisionOutputDTO:
        """
        Calls POST https://generativelanguage.googleapis.com/v1beta/decisions
        using `gemini-decision-1` (0 output tokens, single prefill pass).
        """
        payload = self.build_gemini_decision_request_payload(
            anomaly=anomaly,
            catalyst=catalyst,
            model=self._settings.gemini_decision_model,
        )
        response_json = await self._post_json(
            url=self._settings.gemini_decisions_url,
            headers=self._gemini_headers(),
            payload=payload,
            provider_label="Google Gemini Decision-1 Step 2B",
        )
        return self.parse_gemini_decision_response(response_json)

    async def run_red_team_step2b(
        self,
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
    ) -> tuple[AIVerificationResultDTO, str]:
        payload = self.build_step2b_request_payload(
            anomaly=anomaly,
            catalyst=catalyst,
            model=self._settings.xai_model,
        )
        response_json = await self._post_json(
            url=self._settings.xai_responses_url,
            headers=self._xai_headers(),
            payload=payload,
            provider_label="xAI Responses Step 2B",
        )
        raw_text = self.extract_output_text(response_json)
        dto = AIVerificationResultDTO.model_validate_json(raw_text)
        return dto, raw_text


LLMRouter = XAIResponsesRouter
