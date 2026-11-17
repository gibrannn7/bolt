# BOLT: Quantitative Microstructure & Adversarial AI Trading Engine

BOLT is a capital-efficient, production-grade quantitative trading and prediction engine engineered for Python 3.12+, Clean Architecture, and SQLite WAL persistence. It targets two high-velocity liquidity venues:

1. **Hyperliquid DEX (70% Allocation):** Crypto Perpetuals Microstructure & Narrative Anomaly Sniper.
2. **Polymarket CLOB (30% Allocation):** Short-Horizon Event Mispricing Sniper (resolution within 6 to 72 hours).

---

## 1. System Architecture (The 3-Gate Funnel)

```text
[Market Data Streams: Hyperliquid Info REST + Polymarket Gamma & CLOB Batch APIs]
                                       |
                                       v
+-------------------------------------------------------------------------------+
| GATE 1: DETERMINISTIC QUANT & MICROSTRUCTURE FILTER (Vectorized Python/NumPy) |
| - Hyperliquid (5m scan): 24h Vol >= $2M, RVOL >= 2.5x, 1h OI Delta >= +5.0%,  |
|   Daily VWAP distance bounds, Hourly Funding filter, BTC 1h Macro Guard       |
| - Polymarket (10m scan): 6h <= Resolution <= 72h, Vol >= $25k, Spread <= $0.03|
|   Implied Probability in [$0.15, $0.85]                                       |
+-------------------------------------------------------------------------------+
                                       | (Top ~2% microstructure anomalies)
                                       v
+-------------------------------------------------------------------------------+
| GATE 2: HYBRID ADVERSARIAL AI CATALYST & CALIBRATED PROBABILITY ENGINE        |
| - Step 2A (xAI grok-4.7 via /v1/responses): Live x_search + web_search        |
|   extracting <180m catalysts, bull arguments, bear flaws, and audit trace     |
| - Step 2B (Google gemini-decision-1 via /v1beta/decisions): Zero-output-token |
|   calibrated probabilities (freshness, bull-trap risk, win probability, and   |
|   thesis rubric score) with price masked to eliminate anchoring bias          |
| - Fallback Hierarchy: gemini-decision-1 -> grok-4.7 Prosecutor -> $0 Quant    |
+-------------------------------------------------------------------------------+
                                       | (Passes if Veto == False & Score >= 78)
                                       v
+-------------------------------------------------------------------------------+
| GATE 3: MATHEMATICAL RISK ENGINE, EXCHANGE FLOORS & 24H CIRCUIT BREAKER       |
| - Hyperliquid: 2.0% equity risk at 1.8x ATR-14 SL, 3.0x TP (1:3 R:R),         |
|   2.0x hard leverage cap, $10.00 min notional floor (<= 3.0% risk cap),       |
|   and automatic breakeven trailing stop at +1.5x SL distance                  |
| - Polymarket: Symmetric BUY_YES / BUY_NO Quarter-Kelly sizing (edge >= 0.12,  |
|   5.0% max bankroll cap, minimum 5 shares and $1.00 notional floor)           |
| - Circuit Breaker: 24h lock on 3 consecutive losses or <= -5.0% 24h drawdown  |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| EXECUTION, DYNAMIC ACCOUNT LEDGER & TELEMETRY LAYER                           |
| - Modes: PAPER | SEMI_AUTO | FULL_AUTO                                        |
| - Dynamic SQLite WAL account_ledger tracking equity, margin, fees, MFE/MAE    |
| - Telegram Command Center (/status, /pnl, /export, /halt & approval buttons)  |
+-------------------------------------------------------------------------------+
```

### Clean Architecture Directory Layout

```plaintext
bolt/
├── .gitignore
├── .env.example
├── pyproject.toml
├── README.md
├── docs/
│   ├── blueprint.md                 # Master architectural & math specification
│   ├── gemini_decision_api.md       # Google gemini-decision-1 REST Decisions API spec
│   ├── hyperliquid_api.md           # Hyperliquid Info/Exchange REST & SDK spec
│   ├── polymarket_api.md            # Polymarket Gamma & CLOB batch API spec
│   └── xai_grok_api.md              # xAI grok-4.7 Responses API & JSON schema spec
├── scripts/
│   ├── live_smoke_test.py           # Mainnet read-only + $0 paper smoke test
│   └── export_audit_report.py       # Post-mortem CSV/Excel audit report exporter
├── main.py                          # Application entrypoint & async task orchestrator
├── src/
│   ├── config/
│   │   └── settings.py              # Pydantic BaseSettings loading from .env
│   ├── domain/
│   │   ├── enums.py                 # VenueType, SignalDirection, ExecutionMode, OrderStatus
│   │   ├── dtos.py                  # Immutable Pydantic v2 DTOs (frozen=True)
│   │   └── interfaces.py            # Protocols and Abstract Base Classes
│   ├── use_cases/
│   │   ├── gate1_quant_filter.py    # Vectorized RVOL, OI delta, VWAP, ATR-14, Spread filters
│   │   ├── gate2_ai_verifier.py     # Hybrid Grok-4.7 + Gemini Decision-1 verifier
│   │   ├── gate3_risk_engine.py     # ATR sizing, Quarter-Kelly, exchange floors, Circuit Breaker
│   │   └── portfolio_manager.py     # Dynamic ledger, fee/slippage deduction, MFE/MAE, Brier score
│   └── infrastructure/
│       ├── db/
│       │   ├── sqlite_client.py     # Async SQLite connection manager (PRAGMA journal_mode=WAL)
│       │   └── repositories.py      # CRUD for account_ledger, hl_oi_snapshots, anomalies, trades
│       ├── venues/
│       │   ├── hyperliquid_client.py# Hyperliquid Info/Exchange client with Semaphore(3) throttling
│       │   └── polymarket_client.py # Polymarket Gamma/CLOB batch client with DoH fallback
│       ├── llm/
│       │   ├── router.py            # Hybrid xAI Responses + Google Decisions API router
│       │   └── prompts.py           # Strict JSON schemas & decision rubric definitions
│       └── notifications/
│           └── telegram_bot.py      # ASCII-prefixed Telegram C2 (/status, /pnl, /export, /halt)
└── tests/
    ├── unit/
    │   ├── test_dtos.py
    │   ├── test_gate1_math.py
    │   ├── test_gate2_verifier.py
    │   └── test_gate3_risk.py
    └── integration/
        └── test_paper_execution.py
```

---

## 2. Quickstart & Installation

### Prerequisites
- Python 3.12+
- SQLite 3 (with WAL support enabled automatically at startup)

### Installation

```bash
# Install core dependencies and test tooling
pip install -e ".[dev]"

# Optional: install live venue execution SDKs (hyperliquid-python-sdk, py-clob-client, aiogram)
pip install -e ".[venues,dev]"
```

### Environment Configuration

Copy `.env.example` to `.env` and configure your keys and capital parameters:

```bash
cp .env.example .env
```

Key configuration variables in `.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `EXECUTION_MODE` | `PAPER` | `PAPER`, `SEMI_AUTO`, or `FULL_AUTO` |
| `PAPER_INITIAL_EQUITY_USD` | `100.00` | Starting dynamic ledger equity in USD |
| `HL_TAKER_FEE_BPS` | `3.5` | Hyperliquid taker fee in basis points (`0.035%`) |
| `HL_MIN_ORDER_USD` | `10.00` | Hyperliquid minimum exchange order notional (`$10.00`) |
| `POLYMARKET_MIN_SHARES` | `5.0` | Polymarket minimum order size in outcome shares |
| `CUSTOM_DNS_DOH_URL` | `https://cloudflare-dns.com/dns-query` | DNS-over-HTTPS resolver for sinkholed networks |
| `XAI_API_KEY` | `""` | xAI API key for Step 2A `grok-4.7` live search (`MOCK` for $0 smoke mode) |
| `XAI_MODEL` | `grok-4.7` | xAI Responses API model identifier |
| `XAI_SEARCH_EFFORT` | `low` | Reasoning effort for Step 2A search extraction |
| `GEMINI_API_KEY` | `""` | Google API key for Step 2B `gemini-decision-1` calibrated probability judge |
| `GEMINI_DECISION_MODEL` | `gemini-decision-1` | Google Decisions API model identifier |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram Bot token for Command & Control notifications |
| `TELEGRAM_CHAT_ID` | `""` | Authorized Telegram chat ID |

---

## 3. Operating Modes & Realistic Account Ledger

1. **`PAPER` Mode (Default):**
   - Initializes the SQLite `account_ledger` table with `PAPER_INITIAL_EQUITY_USD` (default `$100.00`).
   - Enforces real exchange minimum order floors (`$10.00` notional on Hyperliquid; `5.0` shares and `$1.00` on Polymarket). If `2.0%` risk sizing yields a notional below `$10.00` on Hyperliquid, Gate 3 scales up to the `$10.00` floor **only if** total stop-loss risk remains `<= 3.0%` of current equity and available margin suffices.
   - Deducts entry/exit taker fees (`0.035%` on Hyperliquid) and estimated half-spread slippage from `realized_pnl_usd`, locks/unlocks margin dynamically, and tracks intrabar `max_favorable_excursion_pct` (MFE) and `max_adverse_excursion_pct` (MAE) on every price update.
2. **`SEMI_AUTO` Mode:**
   - Sends formatted trade proposals to Telegram with `[Approve Trade]` and `[Reject Trade]` inline callback buttons before dispatching orders.
3. **`FULL_AUTO` Mode:**
   - Automatically signs and dispatches approved orders to Hyperliquid (`hyperliquid-python-sdk`) and Polymarket (`py-clob-client`) while enforcing the 24-hour Circuit Breaker.

---

## 4. Verification, Live Smoke Test & Audit Reporting

### Run the Test Suite

```bash
pytest -v
```

### Run the $0 Live Market Smoke Test

To test live mainnet ingestion (`https://api.hyperliquid.xyz/info` and Polymarket Gamma/CLOB), `asyncio.Semaphore(3)` candle throttling, cold-start OI snapshot warmup, `$100.00` dynamic paper ledger sizing, fee/MFE/MAE accounting, and CSV audit export with **$0 API spend**:

```bash
python scripts/live_smoke_test.py
```

### Export Post-Mortem Audit Report (CSV / Excel)

To join `anomalies`, `ai_verifications`, `trades`, `brier_tracking`, and `account_ledger` into `reports/bolt_audit_report.csv` (or trigger via `/export` in Telegram):

```bash
python scripts/export_audit_report.py --db bolt_state.db --out reports/bolt_audit_report.csv
```

### Run the Main Engine

```bash
# Execute a single scan cycle across both venues and exit
python main.py --once

# Run continuous production event loops (5m Hyperliquid / 10m Polymarket / 60s Reconciliation)
python main.py
```
