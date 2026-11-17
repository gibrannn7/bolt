import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
import aiosqlite


SCHEMA_SQL = """
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
    status TEXT NOT NULL,
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
    actual_outcome INTEGER,
    brier_score_component REAL,
    recorded_at_utc TEXT NOT NULL
);
"""


class SQLiteClient:
    """Async SQLite connection manager enforcing WAL journal mode and foreign keys."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    @property
    def db_path(self) -> str:
        return self._db_path

    async def initialize(self) -> None:
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA synchronous=NORMAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.executescript(SCHEMA_SQL)
            await self._ensure_trade_columns(self._conn)
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA synchronous=NORMAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.commit()

    @staticmethod
    async def _ensure_trade_columns(conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute("PRAGMA table_info(trades);")
        rows = await cursor.fetchall()
        await cursor.close()
        existing = {str(r["name"]) for r in rows}

        migrations = [
            ("fees_paid_usd", "TEXT DEFAULT '0.0'"),
            ("slippage_est_usd", "TEXT DEFAULT '0.0'"),
            ("max_favorable_excursion_pct", "REAL DEFAULT 0.0"),
            ("max_adverse_excursion_pct", "REAL DEFAULT 0.0"),
            ("close_reason", "TEXT"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing:
                await conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_def};")

    async def get_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None
        return self._conn

    @asynccontextmanager
    async def session(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await self.get_connection()
        async with self._lock:
            yield conn

    async def get_journal_mode(self) -> str:
        async with self.session() as conn:
            cursor = await conn.execute("PRAGMA journal_mode;")
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return ""
            return str(row[0]).lower()

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
