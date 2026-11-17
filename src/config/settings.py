from decimal import Decimal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.domain.enums import ExecutionMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.PAPER,
        alias="EXECUTION_MODE",
    )
    paper_initial_equity_usd: Decimal = Field(
        default=Decimal("100.00"),
        alias="PAPER_INITIAL_EQUITY_USD",
    )
    initial_account_equity_usd: Decimal = Field(
        default=Decimal("100.00"),
        alias="INITIAL_ACCOUNT_EQUITY_USD",
    )
    max_margin_allocation_per_trade_pct: Decimal = Field(
        default=Decimal("0.35"),
        alias="MAX_MARGIN_ALLOCATION_PER_TRADE_PCT",
    )
    max_concurrent_open_positions: int = Field(
        default=3,
        alias="MAX_CONCURRENT_OPEN_POSITIONS",
    )
    anomaly_cooldown_minutes: int = Field(
        default=180,
        alias="ANOMALY_COOLDOWN_MINUTES",
    )
    max_gate2_calls_per_scan: int = Field(
        default=2,
        alias="MAX_GATE2_CALLS_PER_SCAN",
    )
    max_daily_ai_calls: int = Field(
        default=12,
        alias="MAX_DAILY_AI_CALLS",
    )
    hyperliquid_wallet_address: str = Field(
        default="0x0000000000000000000000000000000000000000",
        alias="HYPERLIQUID_WALLET_ADDRESS",
    )
    hyperliquid_private_key: str = Field(
        default="",
        alias="HYPERLIQUID_PRIVATE_KEY",
    )
    hl_taker_fee_bps: Decimal = Field(
        default=Decimal("3.5"),
        alias="HL_TAKER_FEE_BPS",
    )
    hl_min_order_usd: Decimal = Field(
        default=Decimal("10.00"),
        alias="HL_MIN_ORDER_USD",
    )
    polymarket_private_key: str = Field(
        default="",
        alias="POLYMARKET_PRIVATE_KEY",
    )
    polymarket_funder_address: str = Field(
        default="0x0000000000000000000000000000000000000000",
        alias="POLYMARKET_FUNDER_ADDRESS",
    )
    polymarket_min_shares: Decimal = Field(
        default=Decimal("5.0"),
        alias="POLYMARKET_MIN_SHARES",
    )
    custom_dns_doh_url: str = Field(
        default="https://cloudflare-dns.com/dns-query",
        alias="CUSTOM_DNS_DOH_URL",
    )
    xai_api_key: str = Field(
        default="",
        alias="XAI_API_KEY",
    )
    xai_model: str = Field(
        default="grok-4.7",
        alias="XAI_MODEL",
    )
    xai_search_effort: str = Field(
        default="low",
        alias="XAI_SEARCH_EFFORT",
    )
    gemini_api_key: str = Field(
        default="",
        alias="GEMINI_API_KEY",
    )
    gemini_decision_model: str = Field(
        default="gemini-decision-1",
        alias="GEMINI_DECISION_MODEL",
    )
    gemini_decisions_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/decisions",
        alias="GEMINI_DECISIONS_URL",
    )
    telegram_bot_token: str = Field(
        default="",
        alias="TELEGRAM_BOT_TOKEN",
    )
    telegram_chat_id: str = Field(
        default="",
        alias="TELEGRAM_CHAT_ID",
    )
    sqlite_db_path: str = Field(
        default="bolt_state.db",
        alias="SQLITE_DB_PATH",
    )
    hyperliquid_allocation_pct: float = Field(
        default=0.70,
        alias="HYPERLIQUID_ALLOCATION_PCT",
    )
    polymarket_allocation_pct: float = Field(
        default=0.30,
        alias="POLYMARKET_ALLOCATION_PCT",
    )
    hyperliquid_info_url: str = Field(
        default="https://api.hyperliquid.xyz/info",
        alias="HYPERLIQUID_INFO_URL",
    )
    hyperliquid_exchange_url: str = Field(
        default="https://api.hyperliquid.xyz/exchange",
        alias="HYPERLIQUID_EXCHANGE_URL",
    )
    polymarket_gamma_url: str = Field(
        default="https://gamma-api.polymarket.com",
        alias="POLYMARKET_GAMMA_URL",
    )
    polymarket_clob_url: str = Field(
        default="https://clob.polymarket.com",
        alias="POLYMARKET_CLOB_URL",
    )
    xai_responses_url: str = Field(
        default="https://api.x.ai/v1/responses",
        alias="XAI_RESPONSES_URL",
    )


def get_settings() -> Settings:
    return Settings()
