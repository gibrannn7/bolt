# xAI Grok-4.7 Responses API Reference for BOLT

## 1. Model & Endpoint Specification

- **Model Identifier:** `grok-4.7`
- **Context Window:** 500,000 tokens (Knowledge Cutoff: May 2026)
- **Primary Endpoint (Responses API):** `POST https://api.x.ai/v1/responses`
- **Headers:**
  - `Authorization: Bearer <XAI_API_KEY>`
  - `Content-Type: application/json`
- **Supported Reasoning Efforts:** `"low"`, `"medium"`, `"high"` (default), `"xhigh"`
- **Built-in Native Tools:** `{"type": "x_search"}`, `{"type": "web_search"}`

---

## 2. Step 2A Call: Live X & Web Catalyst Extractor (`effort: "low"`, Tools ON)

Step 2A uses `grok-4.7` with `low` reasoning effort and native `x_search` + `web_search` tools enabled to extract real-time catalysts from the last 180 minutes with minimal latency and token cost.

- **Endpoint:** `POST https://api.x.ai/v1/responses`
- **Request Payload:**

```json
{
  "model": "grok-4.7",
  "reasoning": {
    "effort": "low"
  },
  "tools": [
    {
      "type": "x_search"
    },
    {
      "type": "web_search"
    }
  ],
  "input": [
    {
      "role": "system",
      "content": "You are an institutional market intelligence extractor. Use x_search and web_search to find verifiable factual events, protocol announcements, whale movements, or breaking news from the last 180 minutes for the given asset or Polymarket question. Ignore retail spam or old news (>180 minutes old). Output strictly valid JSON."
    },
    {
      "role": "user",
      "content": "Venue: HYPERLIQUID | Symbol: HYPE | Question/Context: Hyperliquid Perpetuals | Anomaly Timestamp UTC: 2026-11-16T07:30:00Z. Search live X and Web for catalysts in the last 180 minutes."
    }
  ],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "catalyst_extraction_output",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "catalyst_found": { "type": "boolean" },
          "primary_catalyst_summary": { "type": "string" },
          "earliest_post_timestamp_utc": { "type": "string" },
          "age_in_minutes": { "type": "integer" },
          "verifiable_source_urls": {
            "type": "array",
            "items": { "type": "string" }
          },
          "is_recycled_or_old_news": { "type": "boolean" }
        },
        "required": [
          "catalyst_found",
          "primary_catalyst_summary",
          "earliest_post_timestamp_utc",
          "age_in_minutes",
          "verifiable_source_urls",
          "is_recycled_or_old_news"
        ],
        "additionalProperties": false
      }
    }
  }
}
```

---

## 3. Step 2B Call: Adversarial Red-Team Prosecutor (effort: "high", Tools OFF)

Step 2B runs in a completely isolated context with NO search tools enabled (tools omitted) and reasoning.effort set to "high" (or "xhigh" when rvol_ratio >= 4.0). It audits Gate 1 microstructure metrics + Step 2A catalyst output without knowing the current market price (to prevent anchoring bias).

- **Endpoint:** `POST https://api.x.ai/v1/responses`
- **Request Payload:**

```json
{
  "model": "grok-4.7",
  "reasoning": {
    "effort": "high"
  },
  "input": [
    {
      "role": "system",
      "content": "You are a Senior Quantitative Risk Prosecutor. Your job is to DESTROY weak trading theses and protect capital. Audit the Gate 1 microstructure metrics and Step 2A extracted catalyst. Issue red_team_veto = true immediately if: (1) catalyst_found is false, (2) age_in_minutes > 120, (3) is_recycled_or_old_news is true, or (4) evidence points to retail bull-trap, influencer wash-trading, or imminent token unlock dilution. Estimate independent win probability (0.0 to 1.0) without knowing market price."
    },
    {
      "role": "user",
      "content": "<JSON_STRING_OF_GATE1_METRICS_WITHOUT_PRICE_AND_STEP2A_JSON>"
    }
  ],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "ai_verification_result",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "anomaly_id": { "type": "string" },
          "primary_catalyst_summary": { "type": "string" },
          "source_timestamps_verified": { "type": "boolean" },
          "bull_thesis_score": { "type": "integer" },
          "red_team_flaws_detected": {
            "type": "array",
            "items": { "type": "string" }
          },
          "red_team_veto": { "type": "boolean" },
          "red_team_penalty": { "type": "integer" },
          "estimated_win_probability": { "type": "number" },
          "final_confidence_score": { "type": "integer" }
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
          "final_confidence_score"
        ],
        "additionalProperties": false
      }
    }
  }
}
```

---

## 4. Parsing Responses API Output in Python

When parsing `POST https://api.x.ai/v1/responses`, extract the structured JSON text from:

- `response_json["output_text"]` (if top-level convenience field is present), OR
- Iterate over `response_json["output"]` items where `item["type"] == "message"`, then read `item["content"][0]["text"]` and parse with `AIVerificationResultDTO.model_validate_json(raw_text)`.
