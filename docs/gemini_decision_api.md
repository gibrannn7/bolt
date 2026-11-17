# Google Gemini Decision 1 (`gemini-decision-1`) API Reference for BOLT

## 1. Model & Endpoint Specification
- **Model Identifier:** `gemini-decision-1`
- **Input Token Limit:** 262,144 tokens
- **Output Token Limit:** 0 output tokens (single prefill forward pass)
- **Primary REST Endpoint:** `POST https://generativelanguage.googleapis.com/v1beta/decisions`
- **Headers:**
  - `x-goog-api-key: <GEMINI_API_KEY>`
  - `Content-Type: application/json`
- **Supported Question Types:**
  - `noul` (Binary Yes/No Probability): Returns calibrated probability `p` in `[0.01, 0.99]`.
  - `score` (Weighted Rubric Evaluation): Returns probability-weighted expected score across numeric rubric anchors.

---

## 2. Step 2B Call: Calibrated Probability & Risk Judge (`gemini-decision-1`)

In BOLT Gate 2, Step 2A (`grok-4.7` with `x_search` + `web_search`) extracts live catalysts, bull arguments, bear flaws, and an audit reasoning trace. Step 2B sends the price-masked Gate 1 quantitative metrics plus Step 2A's dossier into `gemini-decision-1` to evaluate four structured decision questions in a single zero-output-token pass:

- **Endpoint:** `POST https://generativelanguage.googleapis.com/v1beta/decisions`
- **Request Payload:**

```json
{
  "model": "gemini-decision-1",
  "input": "<COMBINED_DOSSIER_OF_GATE1_QUANT_METRICS_WITH_PRICE_MASKED_AND_STEP2A_GROK_BULL_BEAR_EVIDENCE>",
  "questions": {
    "is_fresh_and_verifiable": {
      "type": "noul",
      "instructions": "Is the extracted catalyst genuinely fresh (<120 minutes old) and backed by verifiable factual announcements rather than recycled news or unverified retail chatter?"
    },
    "is_bull_trap_or_manipulation": {
      "type": "noul",
      "instructions": "Does the evidence indicate a retail bull/bear trap, influencer wash-trading, artificial spoofing, or imminent token unlock dilution that warrants an immediate risk veto?"
    },
    "win_probability": {
      "type": "noul",
      "instructions": "What is the independent probability that the proposed trade direction will reach its target outcome before hitting its stop-loss?"
    },
    "thesis_quality_rubric": {
      "type": "score",
      "instructions": "Rate the overall structural strength of the catalyst combined with the quantitative microstructure anomaly.",
      "criteria": {
        "20": "Very weak, noisy, or unverified catalyst.",
        "40": "Below average catalyst with notable structural doubts.",
        "60": "Moderate catalyst with mixed microstructure confirmation.",
        "80": "Strong verifiable catalyst aligned with fresh OI and volume inflow.",
        "95": "Exceptional institutional-grade catalyst with pristine microstructure alignment."
      }
    }
  }
}
```

---

## 3. Response Payload & Parsing Specification

The `/v1beta/decisions` endpoint returns a JSON object containing calibrated answers for each question key (either directly under `"answers"` / `"questions"` / `"results"` or as float/object values):

```json
{
  "model": "gemini-decision-1",
  "answers": {
    "is_fresh_and_verifiable": {
      "probability": 0.88
    },
    "is_bull_trap_or_manipulation": {
      "probability": 0.12
    },
    "win_probability": {
      "probability": 0.71
    },
    "thesis_quality_rubric": {
      "score": 84.5,
      "distribution": {
        "20": 0.01,
        "40": 0.03,
        "60": 0.12,
        "80": 0.52,
        "95": 0.32
      }
    }
  }
}
```

### Deterministic Gate 2 Mapping Rules
Given the parsed `gemini-decision-1` values and Step 2A `CatalystExtractionDTO`:
1. `source_timestamps_verified = (P(is_fresh_and_verifiable) >= 0.60) and (0 <= age_in_minutes <= 120) and catalyst_found and len(verifiable_source_urls) > 0`
2. `red_team_veto = (not source_timestamps_verified) or (P(is_bull_trap_or_manipulation) >= 0.45) or is_recycled_or_old_news`
3. `bull_thesis_score = min(100, max(0, round(thesis_quality_rubric.score)))`
4. `red_team_penalty = min(100, max(0, round(P(is_bull_trap_or_manipulation) * 50)))`
5. `final_confidence_score = max(0, bull_thesis_score - red_team_penalty)`
6. `estimated_win_probability = round(P(win_probability), 4)`
7. **Pass Criteria:** `red_team_veto == False` AND `final_confidence_score >= 78`.

### Multi-Tier Fallback Hierarchy
1. **Primary (`GEMINI_API_KEY` set):** Step 2A (`grok-4.7` live X/web search) -> Step 2B (`gemini-decision-1` calibrated probability judge).
2. **Secondary (`GEMINI_API_KEY` empty, `XAI_API_KEY` set):** Step 2A (`grok-4.7` live X/web search) -> Step 2B (`grok-4.7` `effort="high"` / `"xhigh"` Red-Team Prosecutor).
3. **Zero-Spend Smoke Mode (`EXECUTION_MODE=PAPER` and both keys empty or `"MOCK"`):** Deterministic `FALLBACK_QUANT_ONLY` mode ($0 API spend).
