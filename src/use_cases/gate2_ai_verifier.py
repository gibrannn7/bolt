import json
import logging
from typing import Any, Dict, List, Optional

from src.domain.dtos import (
    AIVerificationResultDTO,
    CatalystExtractionDTO,
    GeminiDecisionOutputDTO,
    MarketAnomalyDTO,
)
from src.domain.enums import ExecutionMode, VenueType
from src.domain.interfaces import (
    AIVerificationRepositoryProtocol,
    AnomalyRepositoryProtocol,
    LLMRouterAdapter,
)

logger = logging.getLogger(__name__)


class Gate2AIVerifier:
    """
    Gate 2 Hybrid Adversarial AI Catalyst & Calibrated Probability Engine:
    - Step 2A: xAI Grok-4.7 live X + Web Search catalyst & bull/bear evidence extractor
    - Step 2B (Primary): Google `gemini-decision-1` calibrated zero-output-token probability judge
    - Step 2B (Fallback a): xAI `grok-4.7` Red-Team Prosecutor if GEMINI_API_KEY is not set
    - Step 2B (Fallback b): Deterministic `FALLBACK_QUANT_ONLY` mode when both keys are empty/MOCK in PAPER mode
    """

    MIN_CONFIDENCE_SCORE: int = 78
    MAX_CATALYST_AGE_MINUTES: int = 120
    MIN_FRESH_PROBABILITY: float = 0.60
    MAX_BULL_TRAP_PROBABILITY: float = 0.45

    def __init__(
        self,
        llm_router: Optional[LLMRouterAdapter] = None,
        anomaly_repo: Optional[AnomalyRepositoryProtocol] = None,
        verification_repo: Optional[AIVerificationRepositoryProtocol] = None,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
        xai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self._router = llm_router
        self._anomaly_repo = anomaly_repo
        self._verification_repo = verification_repo
        self._execution_mode = execution_mode
        self._xai_api_key = xai_api_key
        self._gemini_api_key = gemini_api_key

    def _resolve_keys_and_mode(self) -> tuple[ExecutionMode, str, str]:
        mode = self._execution_mode
        xai_key = self._xai_api_key
        gem_key = self._gemini_api_key

        if self._router is not None and hasattr(self._router, "_settings"):
            router_settings = getattr(self._router, "_settings")
            if xai_key is None:
                xai_key = getattr(router_settings, "xai_api_key", "")
            if gem_key is None:
                gem_key = getattr(router_settings, "gemini_api_key", "")
            mode = getattr(router_settings, "execution_mode", mode)

        xai_norm = (xai_key or "").strip()
        gem_norm = (gem_key or "").strip()
        return mode, xai_norm, gem_norm

    @staticmethod
    def _is_key_active(key: str) -> bool:
        return bool(key) and key.upper() != "MOCK"

    def is_fallback_quant_only_mode(self) -> bool:
        """
        Returns True when running in PAPER mode and XAI_API_KEY / GEMINI_API_KEY
        is explicitly set to 'MOCK', or when both keys are empty (or no router is attached).
        """
        if self._router is None:
            return True
        mode, xai_key, gem_key = self._resolve_keys_and_mode()
        if mode != ExecutionMode.PAPER:
            return False
        if xai_key.upper() == "MOCK" or gem_key.upper() == "MOCK":
            return True
        return not self._is_key_active(xai_key) and not self._is_key_active(gem_key)

    def should_use_gemini_decision(self) -> bool:
        """
        Returns True when GEMINI_API_KEY is configured (and not 'MOCK') and router supports
        `call_gemini_decision_step2b`.
        """
        if self._router is None or not hasattr(
            self._router, "call_gemini_decision_step2b"
        ):
            return False
        _, _, gem_key = self._resolve_keys_and_mode()
        return self._is_key_active(gem_key)

    @classmethod
    def score_gemini_decision(
        cls,
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
        decision: GeminiDecisionOutputDTO,
    ) -> AIVerificationResultDTO:
        """
        Implements Section 6.3 Gate 2 Scoring Formula for `gemini-decision-1`:
        - source_timestamps_verified = (P(is_fresh_and_verifiable) >= 0.60) and age_in_minutes <= 120
        - red_team_veto = True if not source_timestamps_verified OR P(is_bull_trap_or_manipulation) >= 0.45
          OR is_recycled_or_old_news == True
        - bull_thesis_score = round(thesis_quality_rubric.score) (0-100 scale)
        - red_team_penalty = round(P(is_bull_trap_or_manipulation) * 50)
        - final_confidence_score = max(0, bull_thesis_score - red_team_penalty)
        - estimated_win_probability = round(P(win_probability), 4)
        """
        timestamps_verified = (
            decision.is_fresh_and_verifiable_prob >= cls.MIN_FRESH_PROBABILITY
            and catalyst.catalyst_found
            and (0 <= catalyst.age_in_minutes <= cls.MAX_CATALYST_AGE_MINUTES)
            and (not catalyst.is_recycled_or_old_news)
        )

        flaws: List[str] = list(catalyst.bear_flaws_detected)
        if not catalyst.catalyst_found:
            flaws.append("No verifiable catalyst found in last 180 minutes")
        if catalyst.age_in_minutes > cls.MAX_CATALYST_AGE_MINUTES:
            flaws.append("Catalyst age exceeds 120 minutes limit")
        if decision.is_fresh_and_verifiable_prob < cls.MIN_FRESH_PROBABILITY:
            flaws.append(
                f"Gemini Decision freshness probability too low ({decision.is_fresh_and_verifiable_prob:.2f} < 0.60)"
            )
        if decision.is_bull_trap_or_manipulation_prob >= cls.MAX_BULL_TRAP_PROBABILITY:
            flaws.append(
                f"Gemini Decision bull-trap/manipulation risk triggered ({decision.is_bull_trap_or_manipulation_prob:.2f} >= 0.45)"
            )
        if catalyst.is_recycled_or_old_news:
            flaws.append("Catalyst flagged as recycled or old news")

        red_team_veto = (
            (not timestamps_verified)
            or (decision.is_bull_trap_or_manipulation_prob >= cls.MAX_BULL_TRAP_PROBABILITY)
            or catalyst.is_recycled_or_old_news
        )

        bull_score = min(100, max(0, round(decision.thesis_quality_score)))
        penalty = min(
            100, max(0, round(decision.is_bull_trap_or_manipulation_prob * 50.0))
        )
        final_score = max(0, bull_score - penalty)
        win_prob = min(1.0, max(0.0, round(decision.win_probability, 4)))

        return AIVerificationResultDTO(
            anomaly_id=anomaly.anomaly_id,
            primary_catalyst_summary=catalyst.primary_catalyst_summary,
            source_timestamps_verified=timestamps_verified,
            bull_thesis_score=bull_score,
            red_team_flaws_detected=flaws,
            red_team_veto=red_team_veto,
            red_team_penalty=penalty,
            estimated_win_probability=win_prob,
            final_confidence_score=final_score,
        )

    @staticmethod
    def build_fallback_quant_only_verification(
        anomaly: MarketAnomalyDTO,
    ) -> AIVerificationResultDTO:
        """
        Deterministically constructs an AIVerificationResultDTO from Gate 1
        microstructure metrics in FALLBACK_QUANT_ONLY mode ($0 LLM API spend).
        """
        bull_score = min(96, max(84, int(76 + anomaly.rvol_ratio * 3.0)))
        penalty = 4
        final_score = max(0, bull_score - penalty)

        if anomaly.venue == VenueType.POLYMARKET:
            p_yes = float(anomaly.current_price)
            if p_yes <= 0.50:
                win_prob = min(0.92, round(p_yes + 0.16, 4))
            else:
                win_prob = max(0.08, round(p_yes - 0.16, 4))
        else:
            win_prob = 0.68

        return AIVerificationResultDTO(
            anomaly_id=anomaly.anomaly_id,
            primary_catalyst_summary=(
                f"[FALLBACK_QUANT_ONLY] Deterministic Gate 1 microstructure pass for "
                f"{anomaly.symbol_or_market_id} (RVOL={anomaly.rvol_ratio:.2f}x, $0 API spend)"
            ),
            source_timestamps_verified=True,
            bull_thesis_score=bull_score,
            red_team_flaws_detected=[
                "FALLBACK_QUANT_ONLY mode active (API keys unset or MOCK in PAPER mode)"
            ],
            red_team_veto=False,
            red_team_penalty=penalty,
            estimated_win_probability=win_prob,
            final_confidence_score=final_score,
        )

    @staticmethod
    def enforce_adversarial_scoring_rules(
        anomaly: MarketAnomalyDTO,
        catalyst: CatalystExtractionDTO,
        raw_result: AIVerificationResultDTO,
    ) -> AIVerificationResultDTO:
        """
        Enforces Section 6.3 of @docs/blueprint.md and Section 3 of @docs/xai_grok_api.md
        when using Grok-4.7 Step 2B Red-Team Prosecutor fallback.
        """
        timestamps_verified = (
            raw_result.source_timestamps_verified
            and catalyst.catalyst_found
            and (0 <= catalyst.age_in_minutes <= Gate2AIVerifier.MAX_CATALYST_AGE_MINUTES)
            and (not catalyst.is_recycled_or_old_news)
            and len(catalyst.verifiable_source_urls) > 0
        )

        flaws = list(raw_result.red_team_flaws_detected)
        for bear_flaw in catalyst.bear_flaws_detected:
            if bear_flaw not in flaws:
                flaws.append(bear_flaw)
        veto = raw_result.red_team_veto

        if not catalyst.catalyst_found:
            veto = True
            if "No verifiable catalyst found in last 180 minutes" not in flaws:
                flaws.append("No verifiable catalyst found in last 180 minutes")

        if catalyst.age_in_minutes > Gate2AIVerifier.MAX_CATALYST_AGE_MINUTES:
            veto = True
            if "Catalyst age exceeds 120 minutes limit" not in flaws:
                flaws.append("Catalyst age exceeds 120 minutes limit")

        if catalyst.is_recycled_or_old_news:
            veto = True
            if "Catalyst flagged as recycled or old news" not in flaws:
                flaws.append("Catalyst flagged as recycled or old news")

        if not timestamps_verified:
            veto = True

        computed_final_score = max(
            0, raw_result.bull_thesis_score - raw_result.red_team_penalty
        )

        return AIVerificationResultDTO(
            anomaly_id=anomaly.anomaly_id,
            primary_catalyst_summary=raw_result.primary_catalyst_summary
            or catalyst.primary_catalyst_summary,
            source_timestamps_verified=timestamps_verified,
            bull_thesis_score=raw_result.bull_thesis_score,
            red_team_flaws_detected=flaws,
            red_team_veto=veto,
            red_team_penalty=raw_result.red_team_penalty,
            estimated_win_probability=raw_result.estimated_win_probability,
            final_confidence_score=computed_final_score,
        )

    @classmethod
    def passes_gate2(cls, verification: AIVerificationResultDTO) -> bool:
        """
        Pass Criteria (Section 6.3):
        red_team_veto == False AND S_final >= 78.
        """
        return (
            not verification.red_team_veto
            and verification.final_confidence_score >= cls.MIN_CONFIDENCE_SCORE
        )

    @staticmethod
    def _build_audit_envelope_json(
        provider: str,
        verification: AIVerificationResultDTO,
        catalyst: Optional[CatalystExtractionDTO] = None,
        gemini_decision: Optional[GeminiDecisionOutputDTO] = None,
    ) -> str:
        envelope: Dict[str, Any] = verification.model_dump(mode="json")
        envelope["step2b_provider"] = provider
        if catalyst is not None:
            envelope["step2a_catalyst"] = catalyst.model_dump(mode="json")
        if gemini_decision is not None:
            envelope["gemini_decision_1"] = gemini_decision.model_dump(mode="json")
        return json.dumps(envelope, sort_keys=True)

    async def verify_anomaly(
        self,
        anomaly: MarketAnomalyDTO,
    ) -> tuple[AIVerificationResultDTO, bool]:
        """
        Executes Step 2A and Step 2B sequentially:
        - Fallback (b): FALLBACK_QUANT_ONLY if both keys are empty/MOCK in PAPER mode.
        - Primary: Step 2A (grok-4.7) -> Step 2B (gemini-decision-1) if GEMINI_API_KEY is set.
        - Fallback (a): Step 2A (grok-4.7) -> Step 2B (grok-4.7) if GEMINI_API_KEY is empty.
        """
        if self._anomaly_repo is not None:
            await self._anomaly_repo.save_anomaly(anomaly, passed_gate2=False)

        if self.is_fallback_quant_only_mode():
            validated = self.build_fallback_quant_only_verification(anomaly)
            synthetic_catalyst = CatalystExtractionDTO(
                catalyst_found=True,
                primary_catalyst_summary=validated.primary_catalyst_summary,
                bull_arguments=[
                    f"Gate 1 RVOL={anomaly.rvol_ratio:.2f}x microstructure confirmation"
                ],
                bear_flaws_detected=list(validated.red_team_flaws_detected),
                audit_reasoning_trace=(
                    "FALLBACK_QUANT_ONLY mode active in PAPER trading ($0 API spend)."
                ),
                earliest_post_timestamp_utc=anomaly.timestamp_utc.isoformat(),
                age_in_minutes=5,
                verifiable_source_urls=["https://bolt.local/fallback-quant-only"],
                is_recycled_or_old_news=False,
            )
            raw_json = self._build_audit_envelope_json(
                provider="FALLBACK_QUANT_ONLY",
                verification=validated,
                catalyst=synthetic_catalyst,
            )
            passed = self.passes_gate2(validated)
            if self._verification_repo is not None:
                await self._verification_repo.save_verification(
                    verification=validated,
                    raw_json_response=raw_json,
                )
            if self._anomaly_repo is not None and passed:
                await self._anomaly_repo.mark_passed_gate2(
                    anomaly.anomaly_id, passed=True
                )
            logger.info(
                "[INFO] Gate 2 FALLBACK_QUANT_ONLY for %s (%s): score=%d prob=%.2f",
                anomaly.symbol_or_market_id,
                anomaly.anomaly_id,
                validated.final_confidence_score,
                validated.estimated_win_probability,
            )
            return validated, passed

        assert self._router is not None
        _, xai_key, _ = self._resolve_keys_and_mode()

        if self._is_key_active(xai_key) or not self.should_use_gemini_decision():
            catalyst = await self._router.extract_catalyst_step2a(anomaly)
        else:
            catalyst = CatalystExtractionDTO(
                catalyst_found=True,
                primary_catalyst_summary=(
                    f"Microstructure anomaly on {anomaly.symbol_or_market_id} "
                    f"(RVOL={anomaly.rvol_ratio:.2f}x)"
                ),
                bull_arguments=["Significant Gate 1 microstructure volume/OI expansion"],
                bear_flaws_detected=[],
                audit_reasoning_trace="Step 2A skipped because XAI_API_KEY is unset; evaluating via gemini-decision-1.",
                earliest_post_timestamp_utc=anomaly.timestamp_utc.isoformat(),
                age_in_minutes=15,
                verifiable_source_urls=["https://bolt.local/gate1-microstructure"],
                is_recycled_or_old_news=False,
            )

        if self.should_use_gemini_decision():
            gemini_decision = await self._router.call_gemini_decision_step2b(
                anomaly=anomaly,
                catalyst=catalyst,
            )
            validated = self.score_gemini_decision(
                anomaly=anomaly,
                catalyst=catalyst,
                decision=gemini_decision,
            )
            raw_json = self._build_audit_envelope_json(
                provider="gemini-decision-1",
                verification=validated,
                catalyst=catalyst,
                gemini_decision=gemini_decision,
            )
        else:
            raw_verification, _ = await self._router.run_red_team_step2b(
                anomaly=anomaly,
                catalyst=catalyst,
            )
            validated = self.enforce_adversarial_scoring_rules(
                anomaly=anomaly,
                catalyst=catalyst,
                raw_result=raw_verification,
            )
            raw_json = self._build_audit_envelope_json(
                provider="grok-4.7",
                verification=validated,
                catalyst=catalyst,
            )

        passed = self.passes_gate2(validated)

        if self._verification_repo is not None:
            await self._verification_repo.save_verification(
                verification=validated,
                raw_json_response=raw_json,
            )
        if self._anomaly_repo is not None and passed:
            await self._anomaly_repo.mark_passed_gate2(anomaly.anomaly_id, passed=True)

        if passed:
            logger.info(
                "[INFO] Gate 2 PASSED for %s (%s): score=%d prob=%.2f",
                anomaly.symbol_or_market_id,
                anomaly.anomaly_id,
                validated.final_confidence_score,
                validated.estimated_win_probability,
            )
        else:
            logger.info(
                "[VETO] Gate 2 REJECTED %s (%s): veto=%s score=%d flaws=%s",
                anomaly.symbol_or_market_id,
                anomaly.anomaly_id,
                validated.red_team_veto,
                validated.final_confidence_score,
                validated.red_team_flaws_detected,
            )

        return validated, passed
