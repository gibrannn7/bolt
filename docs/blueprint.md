# BOLT: Quantitative Microstructure & Adversarial AI Trading Engine

# Architectural & Execution Blueprint (v1.0.0)

## 1. SYSTEM OVERVIEW & CORE PHILOSOPHY

BOLT is an automated, capital-efficient quantitative trading and prediction engine designed to operate on lean infrastructure (Single Linux VPS, SQLite WAL, Python 3.12+). It targets two high-velocity liquidity venues:

1. Primary Venue (70% Allocation): Hyperliquid DEX (Crypto Spot & Perpetuals Anomaly/Narrative Sniper).
2. Secondary Venue (30% Allocation): Polymarket CLOB (Short-Horizon Event Mispricing Sniper, resolution under 72 hours).

### Core Engineering Rules

- **Clean Architecture & SOLID Principles:** Strict separation between Domain Entities/DTOs, Use Cases (Quant Filters, Risk Engine), and Infrastructure Adapters (Hyperliquid SDK, Polymarket API, LLM Routers, SQLite, Telegram).
- **Deterministic First, AI Second:** LLMs are strictly forbidden from making raw price predictions from OHLCV arrays or deciding position sizes. Mathematical microstructure filters (Gate 1) must filter out 95%+ of noise before any LLM API call (Gate 2) is triggered.
- **Adversarial AI Validation:** Gate 2 uses a two-step adversarial prompt pipeline (Catalyst Extractor vs. Red-Team Prosecutor) to eliminate LLM sycophancy and confirmation bias.
- **Hard-Coded Risk Guardrails:** Gate 3 enforces mathematical position sizing (ATR-based volatility sizing for Perps/Spot; Fractional Kelly for Prediction Markets) and an automated Daily Circuit Breaker.
- **Code Standards:** Python 3.12+, strict type hints (`typing`), Pydantic v2 DTOs for all boundary data, asynchronous I/O (`asyncio`, `httpx`), and strictly ZERO emojis inside any source code, log messages, or configuration files.

---

## 2. HIGH-LEVEL ARCHITECTURE (THE 3-GATE FUNNEL)

```text
[Market Data Streams: Hyperliquid WS/REST + Polymarket Gamma/CLOB API]
                                  |
                                  v
+-------------------------------------------------------------------+
| GATE 1: DETERMINISTIC QUANT & MICROSTRUCTURE FILTER (Pure Python) |
| - Hyperliquid: RVOL > 2.5x, 1h OI Delta > +5%, Funding Rate Check |
| - Polymarket: Time-to-Resolution < 72h, Spread < $0.03, Vol Spike |
+-------------------------------------------------------------------+
                                  | (Only top 2% anomalies pass)
                                  v
+-------------------------------------------------------------------+
| 4-LAYER PRE-GATE-2 COST & MARGIN SHIELD (Pure Python, $0 Cost)    |
| 1. Margin & Circuit Breaker Guard (Avail >= $10, Open < 3)        |
| 2. Per-Symbol Cooldown (180m deduplication window in SQLite)      |
| 3. Top-K Ranking per Scan (Top 2 by RVOL * |OI_Delta_1h|)         |
| 4. Hard Daily AI Budget Cap (Max 12 paid AI calls / rolling 24h)  |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| GATE 2: ADVERSARIAL AI CATALYST & RED-TEAM ENGINE (LLM Router)    |
| - Step 2A (Grok API w/ Live X Search): Extract <2h social/news    |
| - Step 2B (Gemini Decision-1 / Grok): Calibrated Risk & Prob Judge|
| - Output: Validated Pydantic SignalDTO (Confidence Score 0-100)   |
+-------------------------------------------------------------------+
                                  | (Passes if Score >= 78 & EV > 0)
                                  v
+-------------------------------------------------------------------+
| GATE 3: RISK ENGINE & CIRCUIT BREAKER (Pure Python Math)          |
| - Check Daily Drawdown (< 5%) and Consecutive Losses (< 3)        |
| - Calculate Exact Size (Max 2% equity risk at Stop-Loss distance) |
| - Generate OrderPayloadDTO with hard Stop-Loss & Trailing TP      |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| EXECUTION & TELEMETRY LAYER                                       |
| - Modes: PAPER_TRADING | SEMI_AUTO_TELEGRAM | FULL_AUTO_LIVE      |
| - Persist state to SQLite (WAL mode) & notify via Telegram Bot    |
+-------------------------------------------------------------------+
```

---

## 3. TECH STACK & INFRASTRUCTURE SPECIFICATION

- **Language & Runtime:** Python 3.12+
- **Concurrency:** asyncio, aiohttp / httpx (AsyncClient)
- **Data Validation & DTOs:** pydantic (v2), pydantic-settings
- **Numerical & Quant Processing:** numpy, pandas (vectorized calculations only, no heavy ML frameworks required)
- **Venue SDKs & APIs:**
  - Hyperliquid: hyperliquid-python-sdk, eth-account (for L1 wallet signing)
  - Polymarket: py-clob-client, REST calls to https://gamma-api.polymarket.com
- **AI / LLM Routing Layer (Hybrid xAI Grok-4.7 + Google Gemini Decision 1 via `httpx.AsyncClient`):**
  - Step 2A (Live Search & Dual-Sided Evidence Extractor): xAI Responses API (`POST https://api.x.ai/v1/responses`) using `grok-4.7` (`reasoning={"effort": "low"}` or configurable via `.env`, with `x_search` and `web_search` enabled) to extract verifiable catalysts, bull arguments, bear flaws/risks, and an audit reasoning trace.
  - Step 2B (Calibrated Probability & Risk Judge): Google Decisions API (`POST https://generativelanguage.googleapis.com/v1beta/decisions`) using `gemini-decision-1` (0 output tokens, single prefill pass) to compute calibrated probabilities (`is_fresh_and_verifiable`, `is_bull_trap_or_manipulation`, `win_probability`, and `thesis_quality_rubric`), with automatic fallback to `grok-4.7` (`effort="high"`) if `GEMINI_API_KEY` is not set.
- **Database:** sqlite3 / aiosqlite configured with PRAGMA journal_mode=WAL; for concurrent read/write without locking
- **Command & Control:** aiogram (v3) or direct async Telegram Bot HTTP API

---

## 4. DIRECTORY STRUCTURE (CLEAN ARCHITECTURE)

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
│   │   ├── __init__.py
│   │   └── settings.py              # Pydantic BaseSettings loading from .env
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── enums.py                 # VenueType, SignalDirection, ExecutionMode, OrderStatus
│   │   ├── dtos.py                  # Strict Pydantic DTOs for all layers
│   │   └── interfaces.py            # Abstract Base Classes (Protocols) for repositories & adapters
│   ├── use_cases/
│   │   ├── __init__.py
│   │   ├── gate1_quant_filter.py    # Pure math anomaly detection (RVOL, OI, VWAP, Spread)
│   │   ├── gate2_ai_verifier.py     # Adversarial Bull vs. Red-Team Prosecutor orchestration
│   │   ├── gate3_risk_engine.py     # ATR sizing, Fractional Kelly, Circuit Breaker logic
│   │   └── portfolio_manager.py     # Position tracking, trailing stops, PnL reconciliation
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── db/
│   │   │   ├── sqlite_client.py     # Async SQLite connection pool with WAL mode
│   │   │   └── repositories.py      # Concrete implementations of Trade & Signal repositories
│   │   ├── venues/
│   │   │   ├── hyperliquid_client.py# Wrapper for Hyperliquid Info & Exchange endpoints
│   │   │   └── polymarket_client.py # Wrapper for Polymarket Gamma & CLOB endpoints
│   │   ├── llm/
│   │   │   ├── router.py            # Multi-model LLM router with retry & fallback logic
│   │   │   └── prompts.py           # Strict system & user prompt templates
│   │   └── notifications/
│   │       └── telegram_bot.py      # Telemetry alerts & interactive confirmation callbacks
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

## 5. DATA TRANSFER OBJECTS (DTOs) & DOMAIN CONTRACTS

All data moving between modules must be encapsulated in immutable Pydantic models (frozen=True).

```python
# src/domain/enums.py
from enum import Enum

class VenueType(str, Enum):
    HYPERLIQUID = "HYPERLIQUID"
    POLYMARKET = "POLYMARKET"

class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    NEUTRAL = "NEUTRAL"

class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    SEMI_AUTO = "SEMI_AUTO"
    FULL_AUTO = "FULL_AUTO"

class OrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    CANCELLED = "CANCELLED"
```

```python
# src/domain/dtos.py
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from src.domain.enums import VenueType, SignalDirection

class MarketAnomalyDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    timestamp_utc: datetime
    venue: VenueType
    symbol_or_market_id: str
    asset_name_or_question: str = Field(..., description="Coin ticker or full Polymarket question text for Grok search")
    target_token_id: Optional[str] = Field(None, description="Polymarket CLOB token_id for execution")
    sz_decimals_or_tick: Decimal = Field(Decimal("0.01"), description="Size decimals (HL) or minimum_tick_size (Polymarket)")
    current_price: Decimal
    rvol_ratio: float = Field(..., description="Relative volume vs 20-period mean")
    oi_delta_1h_pct: Optional[float] = Field(None, description="1h Open Interest change %")
    funding_rate_hourly: Optional[float] = Field(None, description="Current hourly funding rate")
    vwap_distance_pct: Optional[float] = Field(None, description="Distance from daily VWAP %")
    btc_1h_return_pct: Optional[float] = Field(None, description="BTC 1h return % for regime filtering")
    atr_14: Optional[Decimal] = Field(None, description="14-period Average True Range")
    hours_to_resolution: Optional[float] = Field(None, description="Polymarket hours left")
    bid_ask_spread: Decimal
    proposed_direction: SignalDirection

class AIVerificationResultDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    primary_catalyst_summary: str
    source_timestamps_verified: bool
    bull_thesis_score: int = Field(..., ge=0, le=100)
    red_team_flaws_detected: List[str]
    red_team_veto: bool
    red_team_penalty: int = Field(..., ge=0, le=100)
    estimated_win_probability: float = Field(..., ge=0.0, le=1.0)
    final_confidence_score: int = Field(..., ge=0, le=100)

class ApprovedOrderDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    anomaly_id: str
    venue: VenueType
    symbol_or_market_id: str
    direction: SignalDirection
    entry_price_limit: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    position_size_usd: Decimal
    position_size_units: Decimal
    risk_amount_usd: Decimal
    expected_value_ratio: float
```

---

## 6. MATHEMATICAL SPECIFICATIONS (GATE 1 & GATE 3)

### 6.1 Gate 1: Hyperliquid Crypto Anomaly Filter

Scan interval: Every 5 minutes on 15-minute candles and live ticker state.

An asset passes Gate 1 for a LONG candidate if and only if ALL conditions hold:

- **Liquidity Floor:** 24-hour USD Volume >= $2,000,000.
- **Relative Volume Spike (RVOL):**
  $$\text{RVOL} = \frac{\text{Volume}_{current\_15m}}{\text{SMA}(\text{Volume}_{15m}, 20)} \ge 2.5$$
- **Open Interest Confirmation (Fresh Capital Inflow):**
  $$\Delta \text{OI}_{1h} = \frac{\text{OI}_{now} - \text{OI}_{1h\_ago}}{\text{OI}_{1h\_ago}} \ge 0.05 \quad (+5\%)$$
- **Anti-Overextension & Anti-Crowding Filter:**
  - Price must be above Daily VWAP, but distance from Daily VWAP must be <= +8.0% (do not chase vertical green candles).
  - Hourly Funding Rate must be <= 0.005% (prevents buying into an overcrowded retail long trap).
- **SHORT Candidate Filter (Symmetric Breakdown):**
  - 24h Volume >= $2,000,000, $\text{RVOL} \ge 2.5$, and $\Delta \text{OI}_{1h} \ge +5.0\%$ (rising OI during price drop confirms aggressive short build-up).
  - Price is below Daily VWAP (distance between $-0.5\%$ and $-8.0\%$) and Hourly Funding Rate >= $-0.005\%$.
- **BTC Macro Regime Filter (Anti-Knife-Catch Guard):**
  - If BTC 1-hour return is $\le -2.0\%$, block all altcoin `LONG` signals unless the candidate asset's 1-hour return is $> +1.5\%$ (proven relative strength decoupling).

### 6.2 Gate 1: Polymarket Short-Horizon Filter

Scan interval: Every 10 minutes on active Gamma markets.

A market passes Gate 1 if and only if:

- **Time Horizon:** $6 \le \text{Hours to Resolution} \le 72$.
- **Orderbook Quality:** Total Market Volume >= $25,000 AND Best Bid-Ask Spread <= $0.03.
- **Price Zone:** Current Implied Probability ($P_{market}$) is between $0.15 and $0.85 (avoids low-payoff tail events).

### 6.3 Gate 2: Pre-Gate-2 Cost Shield & Adversarial AI Scoring Formula

#### 4-Layer Pre-Gate-2 Cost & Margin Shield (Pure Python, $0 Cost)
Before any Gate 1 anomaly invokes Gate 2 (`grok-4.7` and `gemini-decision-1`), four deterministic guards execute against SQLite WAL:
1. **Layer 1 — Pre-Gate-2 Margin & Circuit Breaker Guard:** Query `account_ledger` and open trades count first. If `CIRCUIT_BREAKER_ACTIVE` is True, OR `open_positions_count >= MAX_CONCURRENT_OPEN_POSITIONS` (`3`), OR `available_margin_usd < HL_MIN_ORDER_USD` (`$10.00`), skip Gate 2 completely.
2. **Layer 2 — Per-Symbol Cooldown (`ANOMALY_COOLDOWN_MINUTES = 180`):** Query `anomalies` and `ai_verifications`. If `symbol_or_market_id` has already been evaluated by Gate 2 within the last `180` minutes, skip Gate 2.
3. **Layer 3 — Top-K Ranking per Scan Cycle (`MAX_GATE2_CALLS_PER_SCAN = 2`):** Sort candidates descending by `rvol_ratio * abs(oi_delta_1h_pct or 1.0)` and forward at most `2` candidates per scan cycle.
4. **Layer 4 — Hard Daily AI Budget Cap (`MAX_DAILY_AI_CALLS = 12`):** Count paid Gate 2 evaluations recorded in `ai_verifications` over the rolling 24 hours. If `count >= 12`, block further paid AI calls for the remainder of the rolling window.

#### Adversarial AI Scoring Formula
For `gemini-decision-1` (with fallback to `grok-4.7` Step 2B):

- `source_timestamps_verified = (P(is_fresh_and_verifiable) >= 0.60) and age_in_minutes <= 120`.
- `red_team_veto = True` if `not source_timestamps_verified` OR `P(is_bull_trap_or_manipulation) >= 0.45` OR `is_recycled_or_old_news == True`.
- `bull_thesis_score = round(thesis_quality_rubric.score)` (0-100 scale), `red_team_penalty = round(P(is_bull_trap_or_manipulation) * 50)`, and `final_confidence_score = max(0, bull_thesis_score - red_team_penalty)`.
- `estimated_win_probability = round(P(win_probability), 4)`.

Final Confidence Score:
$$S_{final} = \max(0, S_{bull} - P_{penalty})$$

Pass Criteria: `red_team_veto == False` AND $S_{final} \ge 78$.

### 6.4 Gate 3: Position Sizing & Risk Guardrails

#### For Hyperliquid (Volatility-Adjusted Risk Sizing)

Never use arbitrary leverage. Size is dictated strictly by Stop-Loss distance derived from 14-period ATR:

- **Risk Per Trade ($R_{usd}$):** Locked at $2.0\%$ of current Total Account Equity ($E$):
  $$R_{usd} = 0.02 \times E$$

- **Stop-Loss Distance ($\Delta_{SL}$):**
  $$\Delta_{SL} = 1.8 \times \text{ATR}_{14}$$
  $$\text{StopPrice}_{long} = \text{EntryPrice} - \Delta_{SL}, \quad \text{TakeProfit}_{long} = \text{EntryPrice} + 3.0 \times \Delta_{SL}$$
  $$\text{StopPrice}_{short} = \text{EntryPrice} + \Delta_{SL}, \quad \text{TakeProfit}_{short} = \text{EntryPrice} - 3.0 \times \Delta_{SL}$$
- **Exact Position Size in Units ($Q$):**
  $$Q = \frac{R_{usd}}{\Delta_{SL}}$$

- **Hard Leverage & Per-Trade Margin Cap:** Total Notional Position Value ($Q \times \text{EntryPrice}$) must never exceed $2.0 \times E$ (Maximum effective leverage = 2x), and margin locked in any single position must never exceed `MAX_MARGIN_ALLOCATION_PER_TRADE_PCT` ($35\%$ of $E$, i.e. $\$35.00$ margin / $\$70.00$ notional on a $\$100.00$ account), with at most `MAX_CONCURRENT_OPEN_POSITIONS` ($3$) open positions.

- **Take-Profit & Trailing Stop:**
  - Initial Take-Profit target set at $3.0 \times \Delta_{SL}$ (1:3 Risk-to-Reward ratio).
  - Once unrealized profit reaches $+1.5 \times \Delta_{SL}$, automatically move Stop-Loss to Breakeven ($\text{EntryPrice} + \text{fees}$).

#### For Polymarket (Quarter-Kelly Sizing)

- **Dual-Sided Edge Calculation (`BUY_YES` vs `BUY_NO`):**
  Let $P_{model}$ be Grok's independent probability that the event resolves `YES`, and $P_{yes}$ be the current midpoint price of the `YES` token (with $P_{no} = 1 - P_{yes}$):
  - If $P_{model} - P_{yes} \ge 0.12$: Direction is `BUY_YES`, $\text{Edge} = P_{model} - P_{yes}$, and Effective Cost $C = P_{yes}$.
  - If $(1 - P_{model}) - P_{no} \ge 0.12$: Direction is `BUY_NO` (using `no_token_id`), $\text{Edge} = (1 - P_{model}) - P_{no}$, and Effective Cost $C = P_{no}$.
  - Otherwise, reject trade ($\text{Edge} < 0.12$).

- **Quarter-Kelly Fraction ($f$):**
  $$f = 0.25 \times \left( \frac{\text{Edge}}{1 - C} \right)$$

- **Hard Cap:** Position size is $\min(f \times E, 0.05 \times E)$ (never allocate more than 5% of total bankroll to a single prediction market).

#### Automated Circuit Breaker Rules

Before any order is emitted by Gate 3, query SQLite for the rolling 24-hour performance:

- **Rule 1 (Consecutive Losses):** If the last 3 closed trades resulted in net losses, trigger CIRCUIT_BREAKER_ACTIVE for 24 hours.
- **Rule 2 (Daily Drawdown Limit):** If rolling 24-hour realized + unrealized PnL is <= $-5.0\%$ of starting daily equity, cancel all open entry orders and trigger CIRCUIT_BREAKER_ACTIVE for 24 hours.

---

## 7. AI ORCHESTRATION & PROMPT SPECIFICATIONS (GATE 2)

To prevent hallucination and enforce deterministic parsing, all LLM calls must enforce JSON output matching AIVerificationResultDTO.

### Step 2A: xAI Grok-4.7 Live Search Prompt (Catalyst Extraction)

- **Model & Endpoint:** `grok-4.7` via `POST https://api.x.ai/v1/responses` with `reasoning={"effort": "low"}` and `tools=[{"type": "x_search"}, {"type": "web_search"}]` (see `docs/xai_grok_api.md`).
- **System Instruction:**

```plaintext
You are an institutional market intelligence extractor. Given an asset ticker or prediction market question that just experienced a statistically significant volume anomaly, search live X posts and breaking news from the last 180 minutes.
Extract ONLY verifiable factual events, protocol announcements, whale movements, or macro releases with exact timestamps. Ignore generic retail price predictions or spam.
Output strictly valid JSON.
```

### Step 2B: Red-Team Prosecutor Prompt (Reasoning Validator)

- **Model & Endpoint:** `grok-4.7` via `POST https://api.x.ai/v1/responses` with `reasoning={"effort": "high"}` (or `"xhigh"` when `rvol_ratio >= 4.0`) and `tools=[]` disabled (see `docs/xai_grok_api.md`).
- **System Instruction:**

```plaintext
You are a Senior Quantitative Risk Prosecutor. Your job is to DESTROY weak trading theses and protect capital.
You will receive:
1. Quantitative microstructure metrics (RVOL, Open Interest delta, Funding Rate, VWAP distance).
2. Extracted news/social catalysts from the last 180 minutes.

Note: Current market prices are intentionally hidden from you during probability estimation to prevent anchoring bias.

Perform the following audit:
- Verify if the catalyst is genuinely fresh (<120 minutes old) and structural, or if it is recycled news / influencer wash-trading.
- Check for hidden dilution risks (token unlocks, exploit rumors, regulatory actions, or artificial liquidity spoofing).
- Assign a bull_thesis_score (0-100), list specific red_team_flaws_detected, decide whether to issue a hard red_team_veto (boolean), and compute final_confidence_score (0-100).
Output strictly in the requested JSON schema.
```

---

## 8. DATABASE SCHEMA (SQLITE WAL)

Initialize on startup in `src/infrastructure/db/sqlite_client.py`:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS hl_oi_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    timestamp_epoch_ms INTEGER NOT NULL,
    open_interest REAL NOT NULL,
    mark_px REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hl_oi_coin_time ON hl_oi_snapshots(coin, timestamp_epoch_ms);

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol_or_market_id TEXT NOT NULL,
    asset_name_or_question TEXT NOT NULL,
    target_token_id TEXT,
    proposed_direction TEXT NOT NULL,
    current_price TEXT NOT NULL,
    rvol_ratio REAL NOT NULL,
    oi_delta_1h_pct REAL,
    funding_rate_hourly REAL,
    passed_gate2 INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ai_verifications (
    anomaly_id TEXT PRIMARY KEY,
    primary_catalyst_summary TEXT NOT NULL,
    source_timestamps_verified INTEGER NOT NULL,
    bull_thesis_score INTEGER NOT NULL,
    red_team_veto INTEGER NOT NULL,
    red_team_penalty INTEGER NOT NULL,
    estimated_win_probability REAL NOT NULL,
    final_confidence_score INTEGER NOT NULL,
    raw_json_response TEXT NOT NULL,
    FOREIGN KEY(anomaly_id) REFERENCES anomalies(anomaly_id)
);

CREATE TABLE IF NOT EXISTS account_ledger (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    equity_usd TEXT NOT NULL,
    available_margin_usd TEXT NOT NULL,
    locked_margin_usd TEXT NOT NULL DEFAULT '0.0',
    realized_pnl_cumulative_usd TEXT NOT NULL DEFAULT '0.0',
    total_fees_paid_usd TEXT NOT NULL DEFAULT '0.0',
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    order_id TEXT PRIMARY KEY,
    anomaly_id TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol_or_market_id TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    direction TEXT NOT NULL,
    status TEXT NOT NULL, -- OPEN, CLOSED_TP, CLOSED_SL, CLOSED_MANUAL, CANCELLED
    entry_price TEXT NOT NULL,
    exit_price TEXT,
    stop_loss_price TEXT NOT NULL,
    take_profit_price TEXT NOT NULL,
    position_size_usd TEXT NOT NULL,
    position_size_units TEXT NOT NULL,
    realized_pnl_usd TEXT DEFAULT '0.0',
    fees_paid_usd TEXT DEFAULT '0.0',
    slippage_est_usd TEXT DEFAULT '0.0',
    max_favorable_excursion_pct REAL DEFAULT 0.0,
    max_adverse_excursion_pct REAL DEFAULT 0.0,
    close_reason TEXT,
    opened_at_utc TEXT NOT NULL,
    closed_at_utc TEXT,
    FOREIGN KEY(anomaly_id) REFERENCES anomalies(anomaly_id)
);

CREATE TABLE IF NOT EXISTS brier_tracking (
    prediction_id TEXT PRIMARY KEY,
    anomaly_id TEXT NOT NULL,
    predicted_prob REAL NOT NULL,
    actual_outcome INTEGER, -- 1 for win/resolved YES, 0 for loss/resolved NO
    brier_score_component REAL,
    recorded_at_utc TEXT NOT NULL
);
```

---

## 9. PHASED IMPLEMENTATION ROADMAP (FOR AI CODING ASSISTANT)

When generating code for this repository, execute strictly in the following sequential phases. Do not skip ahead until unit tests for the current phase pass.

### Phase 1: Foundation, Config & SQLite WAL Persistence

- Create `pyproject.toml` and `.env.example` containing keys for `EXECUTION_MODE=PAPER`, `HYPERLIQUID_WALLET_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_FUNDER_ADDRESS`, `XAI_API_KEY`, `XAI_MODEL=grok-4.7`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`.
- Implement src/config/settings.py, src/domain/enums.py, and src/domain/dtos.py.
- Implement `src/infrastructure/db/sqlite_client.py` and `repositories.py` with full async CRUD operations for `hl_oi_snapshots`, `anomalies`, `ai_verifications`, `trades`, and `brier_tracking`.
- Verification: Run pytest tests/unit/test_dtos.py to validate schema serialization and SQLite WAL creation.

### Phase 2: Gate 1 — Market Ingestion & Deterministic Quant Filters

- Implement src/infrastructure/venues/hyperliquid_client.py to fetch all mid-prices, 24h volume, Open Interest history, Funding Rates, and 15m candles from Hyperliquid Info API (https://api.hyperliquid.xyz/info).
- Implement src/infrastructure/venues/polymarket_client.py to fetch active markets from Gamma API and orderbook spreads from CLOB API.
- Implement src/use_cases/gate1_quant_filter.py containing vectorized calculation functions for RVOL, VWAP, ATR-14, and OI Delta.
- Verification: Run pytest tests/unit/test_gate1_math.py with mock candle/OI arrays and run a live read-only scan printing detected anomalies to console.

### Phase 3: Gate 2 — LLM Router & Adversarial Red-Team Verifier

- Implement src/infrastructure/llm/router.py using httpx.AsyncClient with exponential backoff, timeout handling, and strict JSON schema validation.
- Implement src/infrastructure/llm/prompts.py and src/use_cases/gate2_ai_verifier.py chaining Step 2A (Grok live search) into Step 2B (Red-Team Prosecutor).
- Verification: Feed 3 historical anomalies into gate2_ai_verifier.py and verify that weak/unverified catalysts trigger red_team_veto = True.

### Phase 4: Gate 3 — Risk Engine, Paper Trading & Telegram Command Center

- Implement src/use_cases/gate3_risk_engine.py (ATR sizing, Quarter-Kelly, 2% max risk cap, and SQLite Circuit Breaker checks).
- Implement src/use_cases/portfolio_manager.py to simulate fills, monitor virtual Stop-Loss / Take-Profit hits against live Hyperliquid/Polymarket prices in PAPER mode, and calculate Brier Scores.
- Implement src/infrastructure/notifications/telegram_bot.py with /status, /pnl, /halt, and interactive [Approve Trade] / [Reject Trade] inline buttons for SEMI_AUTO mode.
- Assemble main.py async event loop and deploy to VPS in PAPER mode for a mandatory 7-day forward test before enabling live wallet signing.
