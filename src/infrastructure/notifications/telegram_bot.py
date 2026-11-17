import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine, Dict, Optional
import httpx

from scripts.export_audit_report import export_audit_report_csv
from src.config.settings import Settings
from src.domain.dtos import (
    AIVerificationResultDTO,
    ApprovedOrderDTO,
    MarketAnomalyDTO,
    TradeRecordDTO,
)
from src.domain.interfaces import (
    AccountLedgerRepositoryProtocol,
    BrierRepositoryProtocol,
    TradeRepositoryProtocol,
)
from src.use_cases.gate3_risk_engine import Gate3RiskEngine

logger = logging.getLogger(__name__)

ApprovalCallback = Callable[
    [ApprovedOrderDTO, AIVerificationResultDTO],
    Coroutine[Any, Any, Optional[TradeRecordDTO]],
]


class TelegramBotC2:
    """
    Telegram Command & Control (C2) adapter with strictly zero emojis.
    Provides:
    - /status, /pnl, /halt, /export command handlers
    - Telemetry notifications with [INFO], [ANOMALY], [VETO], [ORDER] ASCII prefixes
    - Interactive [Approve Trade] / [Reject Trade] inline keyboard buttons for SEMI_AUTO mode
    """

    def __init__(
        self,
        settings: Settings,
        risk_engine: Gate3RiskEngine,
        trade_repo: TradeRepositoryProtocol,
        brier_repo: Optional[BrierRepositoryProtocol] = None,
        ledger_repo: Optional[AccountLedgerRepositoryProtocol] = None,
        on_approve_order: Optional[ApprovalCallback] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._settings = settings
        self._risk_engine = risk_engine
        self._trade_repo = trade_repo
        self._brier_repo = brier_repo
        self._ledger_repo = ledger_repo
        self._on_approve_order = on_approve_order
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._pending_orders: Dict[
            str, tuple[ApprovedOrderDTO, AIVerificationResultDTO]
        ] = {}

    async def close(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._settings.telegram_bot_token}/{method}"

    @staticmethod
    def format_order_proposal_message(
        anomaly: MarketAnomalyDTO,
        verification: AIVerificationResultDTO,
        order: ApprovedOrderDTO,
    ) -> str:
        return (
            f"[ORDER] SEMI_AUTO CONFIRMATION REQUIRED\n"
            f"Order ID: {order.order_id}\n"
            f"Venue: {order.venue.value}\n"
            f"Symbol/Market: {order.symbol_or_market_id}\n"
            f"Question/Context: {anomaly.asset_name_or_question}\n"
            f"Direction: {order.direction.value}\n"
            f"Entry Limit: {order.entry_price_limit}\n"
            f"Stop Loss: {order.stop_loss_price}\n"
            f"Take Profit: {order.take_profit_price}\n"
            f"Size USD: {order.position_size_usd} ({order.position_size_units} units)\n"
            f"Risk USD: {order.risk_amount_usd}\n"
            f"Confidence Score: {verification.final_confidence_score}/100 "
            f"(Win Prob: {verification.estimated_win_probability:.2f})\n"
            f"Catalyst: {verification.primary_catalyst_summary}"
        )

    @staticmethod
    def build_semi_auto_inline_keyboard(order_id: str) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "[Approve Trade]",
                        "callback_data": f"APPROVE:{order_id}",
                    },
                    {
                        "text": "[Reject Trade]",
                        "callback_data": f"REJECT:{order_id}",
                    },
                ]
            ]
        }

    async def send_message(
        self,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._settings.telegram_bot_token or not self._settings.telegram_chat_id:
            logger.info("[INFO] Telegram C2 local log: %s", text.replace("\n", " | "))
            return {"ok": True, "simulated": True, "text": text}

        payload: Dict[str, Any] = {
            "chat_id": self._settings.telegram_chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        response = await self._client.post(self._api_url("sendMessage"), json=payload)
        response.raise_for_status()
        data = response.json()
        return dict(data) if isinstance(data, dict) else {"ok": False}

    async def queue_semi_auto_order(
        self,
        anomaly: MarketAnomalyDTO,
        verification: AIVerificationResultDTO,
        order: ApprovedOrderDTO,
    ) -> Dict[str, Any]:
        self._pending_orders[order.order_id] = (order, verification)
        text = self.format_order_proposal_message(anomaly, verification, order)
        markup = self.build_semi_auto_inline_keyboard(order.order_id)
        return await self.send_message(text=text, reply_markup=markup)

    async def handle_command(
        self,
        command: str,
        now_utc: Optional[datetime] = None,
        export_csv_path: str = "reports/bolt_audit_report.csv",
    ) -> str:
        ref_now = now_utc or datetime.now(timezone.utc)
        cmd = command.strip().split()[0].lower()

        if cmd == "/status":
            cb_state = await self._risk_engine.check_circuit_breaker(now_utc=ref_now)
            open_trades = await self._trade_repo.list_open_trades()
            status_str = "HALTED" if cb_state.is_active else "ACTIVE"
            ledger_line = ""
            if self._ledger_repo is not None:
                ledger = await self._ledger_repo.get_ledger(
                    default_initial_equity_usd=self._settings.paper_initial_equity_usd
                )
                ledger_line = (
                    f"Equity USD: ${ledger.equity_usd:.2f} "
                    f"(Avail: ${ledger.available_margin_usd:.2f}, Locked: ${ledger.locked_margin_usd:.2f})\n"
                )
            response_text = (
                f"[INFO] BOLT SYSTEM STATUS: {status_str}\n"
                f"Execution Mode: {self._settings.execution_mode.value}\n"
                f"{ledger_line}"
                f"Open Positions: {len(open_trades)}\n"
                f"Pending SEMI_AUTO Approvals: {len(self._pending_orders)}\n"
                f"Circuit Breaker Reason: {cb_state.reason}"
            )
            await self.send_message(response_text)
            return response_text

        if cmd == "/pnl":
            since_24h = (ref_now - timedelta(hours=24)).isoformat()
            realized_24h = await self._trade_repo.get_rolling_24h_realized_pnl(since_24h)
            open_trades = await self._trade_repo.list_open_trades()
            mean_brier: Optional[float] = None
            if self._brier_repo is not None:
                mean_brier = await self._brier_repo.get_mean_brier_score()
            brier_str = f"{mean_brier:.4f}" if mean_brier is not None else "N/A"
            fees_line = ""
            if self._ledger_repo is not None:
                ledger = await self._ledger_repo.get_ledger(
                    default_initial_equity_usd=self._settings.paper_initial_equity_usd
                )
                fees_line = (
                    f"Account Equity: ${ledger.equity_usd:.2f} | "
                    f"Cumulative Net PnL: ${ledger.realized_pnl_cumulative_usd:.2f} | "
                    f"Total Fees Paid: ${ledger.total_fees_paid_usd:.4f}\n"
                )
            response_text = (
                f"[INFO] BOLT PNL & CALIBRATION REPORT\n"
                f"{fees_line}"
                f"Rolling 24h Realized PnL: ${realized_24h:.2f}\n"
                f"Open Trades Count: {len(open_trades)}\n"
                f"Mean Brier Score: {brier_str}"
            )
            await self.send_message(response_text)
            return response_text

        if cmd == "/export":
            out_path, count = await export_audit_report_csv(
                db_path=self._settings.sqlite_db_path,
                output_csv_path=export_csv_path,
            )
            response_text = (
                f"[INFO] BOLT AUDIT REPORT EXPORTED\n"
                f"Path: {out_path}\n"
                f"Total Rows: {count}"
            )
            await self.send_message(response_text)
            return response_text

        if cmd == "/halt":
            cb_state = self._risk_engine.trigger_manual_halt(
                now_utc=ref_now,
                reason="MANUAL_TELEGRAM_HALT",
            )
            cancelled_count = await self._trade_repo.cancel_all_open_trades(
                ref_now.isoformat()
            )
            self._pending_orders.clear()
            response_text = (
                f"[VETO] EMERGENCY HALT ACTIVATED\n"
                f"Reason: {cb_state.reason}\n"
                f"Cancelled Open Trades: {cancelled_count}"
            )
            await self.send_message(response_text)
            return response_text

        response_text = (
            "[WARN] Unknown command. Supported commands: /status, /pnl, /export, /halt"
        )
        await self.send_message(response_text)
        return response_text

    async def handle_callback_query(self, callback_data: str) -> str:
        if ":" not in callback_data:
            return "[ERROR] Malformed callback data"

        action, order_id = callback_data.split(":", 1)
        pending = self._pending_orders.pop(order_id, None)
        if pending is None:
            msg = f"[WARN] Order {order_id} is no longer pending or already processed"
            await self.send_message(msg)
            return msg

        order, verification = pending
        if action == "APPROVE":
            if self._on_approve_order is not None:
                await self._on_approve_order(order, verification)
            msg = (
                f"[ORDER] Approved and executed SEMI_AUTO order {order.order_id} "
                f"({order.venue.value} {order.symbol_or_market_id} {order.direction.value})"
            )
            await self.send_message(msg)
            return msg

        if action == "REJECT":
            msg = (
                f"[VETO] Rejected SEMI_AUTO order {order.order_id} "
                f"({order.venue.value} {order.symbol_or_market_id})"
            )
            await self.send_message(msg)
            return msg

        return f"[WARN] Unrecognized callback action: {action}"
