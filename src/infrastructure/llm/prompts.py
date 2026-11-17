import json
from typing import Any, Dict
from src.domain.dtos import CatalystExtractionDTO, MarketAnomalyDTO


STEP2A_SYSTEM_PROMPT: str = (
    "You are an institutional market intelligence extractor. Use x_search and web_search "
    "to find verifiable factual events, protocol announcements, whale movements, or breaking "
    "news from the last 180 minutes for the given asset or Polymarket question. Extract both "
    "bull_arguments and bear_flaws_detected along with an audit_reasoning_trace. Ignore retail "
    "spam or old news (>180 minutes old). Output strictly valid JSON."
)

STEP2B_SYSTEM_PROMPT: str = (
    "You are a Senior Quantitative Risk Prosecutor. Your job is to DESTROY weak trading theses "
    "and protect capital. Audit the Gate 1 microstructure metrics and Step 2A extracted catalyst. "
    "Issue red_team_veto = true immediately if: (1) catalyst_found is false, (2) age_in_minutes > 120, "
    "(3) is_recycled_or_old_news is true, or (4) evidence points to retail bull-trap, influencer "
    "wash-trading, or imminent token unlock dilution. Estimate independent win probability (0.0 to 1.0) "
    "without knowing market price."
)

STEP2A_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "catalyst_found": {"type": "boolean"},
        "primary_catalyst_summary": {"type": "string"},
        "bull_arguments": {
            "type": "array",
            "items": {"type": "string"},
        },
        "bear_flaws_detected": {
            "type": "array",
            "items": {"type": "string"},
        },
        "audit_reasoning_trace": {"type": "string"},
        "earliest_post_timestamp_utc": {"type": "string"},
        "age_in_minutes": {"type": "integer"},
        "verifiable_source_urls": {
            "type": "array",
            "items": {"type": "string"},
        },
        "is_recycled_or_old_news": {"type": "boolean"},
    },
    "required": [
        "catalyst_found",
        "primary_catalyst_summary",
        "bull_arguments",
        "bear_flaws_detected",
        "audit_reasoning_trace",
        "earliest_post_timestamp_utc",
        "age_in_minutes",
        "verifiable_source_urls",
        "is_recycled_or_old_news",
    ],
    "additionalProperties": False,
}

STEP2B_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "anomaly_id": {"type": "string"},
        "primary_catalyst_summary": {"type": "string"},
        "source_timestamps_verified": {"type": "boolean"},
        "bull_thesis_score": {"type": "integer"},
        "red_team_flaws_detected": {
            "type": "array",
            "items": {"type": "string"},
        },
        "red_team_veto": {"type": "boolean"},
        "red_team_penalty": {"type": "integer"},
        "estimated_win_probability": {"type": "number"},
        "final_confidence_score": {"type": "integer"},
    },
    "required": [
        "anomaly_id",
        "primary_catalyst_summary",
        "source_timestamps_verified",
        "bull_thesis_score",
        "red_team_flaws_detected",
        "red_team_veto",
        "red_team_penalty",
        "estimated_win_probability",
        "final_confidence_score",
    ],
    "additionalProperties": False,
}

GEMINI_DECISION_QUESTIONS: Dict[str, Any] = {
    "is_fresh_and_verifiable": {
        "type": "noul",
        "instructions": (
            "Is the extracted catalyst genuinely fresh (<120 minutes old) and backed by "
            "verifiable factual announcements rather than recycled news or unverified retail chatter?"
        ),
    },
    "is_bull_trap_or_manipulation": {
        "type": "noul",
        "instructions": (
            "Does the evidence indicate a retail bull/bear trap, influencer wash-trading, "
            "artificial spoofing, or imminent token unlock dilution that warrants an immediate risk veto?"
        ),
    },
    "win_probability": {
        "type": "noul",
        "instructions": (
            "What is the independent probability that the proposed trade direction will "
            "reach its target outcome before hitting its stop-loss?"
        ),
    },
    "thesis_quality_rubric": {
        "type": "score",
        "instructions": (
            "Rate the overall structural strength of the catalyst combined with the "
            "quantitative microstructure anomaly."
        ),
        "criteria": {
            "20": "Very weak, noisy, or unverified catalyst.",
            "40": "Below average catalyst with notable structural doubts.",
            "60": "Moderate catalyst with mixed microstructure confirmation.",
            "80": "Strong verifiable catalyst aligned with fresh OI and volume inflow.",
            "95": "Exceptional institutional-grade catalyst with pristine microstructure alignment.",
        },
    },
}


def build_step2a_user_prompt(anomaly: MarketAnomalyDTO) -> str:
    timestamp_iso = anomaly.timestamp_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"Venue: {anomaly.venue.value} | "
        f"Symbol: {anomaly.symbol_or_market_id} | "
        f"Question/Context: {anomaly.asset_name_or_question} | "
        f"Anomaly Timestamp UTC: {timestamp_iso}. "
        "Search live X and Web for catalysts in the last 180 minutes."
    )


def build_step2b_masked_user_payload(
    anomaly: MarketAnomalyDTO,
    catalyst: CatalystExtractionDTO,
) -> str:
    """
    Serializes Gate 1 microstructure metrics and Step 2A catalyst output for Step 2B,
    explicitly stripping `current_price` (and any price-revealing fields) to prevent anchoring bias.
    """
    raw_dump = anomaly.model_dump(mode="json")
    raw_dump.pop("current_price", None)
    raw_dump.pop("atr_14", None)

    payload = {
        "gate1_metrics_price_masked": raw_dump,
        "step2a_catalyst": catalyst.model_dump(mode="json"),
    }
    return json.dumps(payload, sort_keys=True)
