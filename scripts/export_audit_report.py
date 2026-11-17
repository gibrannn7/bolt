import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.settings import get_settings
from src.infrastructure.db.sqlite_client import SQLiteClient


AUDIT_CSV_COLUMNS: List[str] = [
    "anomaly_id",
    "timestamp_utc",
    "venue",
    "symbol_or_market_id",
    "asset_name_or_question",
    "target_token_id",
    "proposed_direction",
    "anomaly_price",
    "rvol_ratio",
    "oi_delta_1h_pct",
    "funding_rate_hourly",
    "passed_gate2",
    "step2b_provider",
    "primary_catalyst_summary",
    "bull_arguments",
    "bear_flaws_detected",
    "audit_reasoning_trace",
    "source_timestamps_verified",
    "is_fresh_and_verifiable_prob",
    "is_bull_trap_or_manipulation_prob",
    "gemini_win_probability",
    "thesis_quality_score",
    "bull_thesis_score",
    "red_team_penalty",
    "red_team_veto",
    "final_confidence_score",
    "estimated_win_probability",
    "order_id",
    "execution_mode",
    "trade_direction",
    "trade_status",
    "entry_price",
    "exit_price",
    "stop_loss_price",
    "take_profit_price",
    "position_size_usd",
    "position_size_units",
    "fees_paid_usd",
    "slippage_est_usd",
    "max_favorable_excursion_pct",
    "max_adverse_excursion_pct",
    "realized_pnl_usd",
    "close_reason",
    "opened_at_utc",
    "closed_at_utc",
    "predicted_prob",
    "actual_outcome",
    "brier_score_component",
    "rolling_mean_brier_score",
    "ledger_equity_usd",
    "ledger_available_margin_usd",
    "ledger_locked_margin_usd",
    "ledger_realized_pnl_cumulative_usd",
    "ledger_total_fees_paid_usd",
]


async def export_audit_report_csv(
    db_path: Optional[str] = None,
    output_csv_path: str = "reports/bolt_audit_report.csv",
) -> tuple[Path, int]:
    """
    Joins anomalies, ai_verifications, trades, brier_tracking, and account_ledger
    from SQLite WAL into a comprehensive CSV/Excel-ready post-mortem audit report.
    """
    settings = get_settings()
    resolved_db = db_path or settings.sqlite_db_path
    out_path = Path(output_csv_path)
    if not out_path.is_absolute():
        out_path = ROOT_DIR / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = SQLiteClient(resolved_db)
    await client.initialize()

    try:
        async with client.session() as conn:
            ledger_cur = await conn.execute("SELECT * FROM account_ledger WHERE id = 1")
            ledger_row = await ledger_cur.fetchone()
            await ledger_cur.close()

            ledger_dict: Dict[str, Any] = dict(ledger_row) if ledger_row else {}

            brier_cur = await conn.execute(
                "SELECT AVG(brier_score_component) AS mean_brier FROM brier_tracking WHERE brier_score_component IS NOT NULL"
            )
            brier_row = await brier_cur.fetchone()
            await brier_cur.close()
            rolling_brier = (
                f"{float(brier_row['mean_brier']):.6f}"
                if brier_row and brier_row["mean_brier"] is not None
                else ""
            )

            query = """
            SELECT
                a.anomaly_id,
                a.timestamp_utc,
                a.venue,
                a.symbol_or_market_id,
                a.asset_name_or_question,
                a.target_token_id,
                a.proposed_direction,
                a.current_price AS anomaly_price,
                a.rvol_ratio,
                a.oi_delta_1h_pct,
                a.funding_rate_hourly,
                a.passed_gate2,
                v.primary_catalyst_summary,
                v.source_timestamps_verified,
                v.bull_thesis_score,
                v.red_team_veto,
                v.red_team_penalty,
                v.estimated_win_probability,
                v.final_confidence_score,
                v.raw_json_response,
                t.order_id,
                t.execution_mode,
                t.direction AS trade_direction,
                t.status AS trade_status,
                t.entry_price,
                t.exit_price,
                t.stop_loss_price,
                t.take_profit_price,
                t.position_size_usd,
                t.position_size_units,
                t.realized_pnl_usd,
                t.fees_paid_usd,
                t.slippage_est_usd,
                t.max_favorable_excursion_pct,
                t.max_adverse_excursion_pct,
                t.close_reason,
                t.opened_at_utc,
                t.closed_at_utc,
                b.predicted_prob,
                b.actual_outcome,
                b.brier_score_component
            FROM anomalies a
            LEFT JOIN ai_verifications v ON a.anomaly_id = v.anomaly_id
            LEFT JOIN trades t ON a.anomaly_id = t.anomaly_id
            LEFT JOIN brier_tracking b ON (
                b.prediction_id = ('brier-' || t.order_id)
                OR b.anomaly_id = a.anomaly_id
            )
            ORDER BY a.timestamp_utc DESC, t.opened_at_utc DESC
            """
            cursor = await conn.execute(query)
            rows = await cursor.fetchall()
            await cursor.close()

        row_count = 0
        with out_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=AUDIT_CSV_COLUMNS)
            writer.writeheader()

            for row in rows:
                r = dict(row)
                raw_json_str = str(r.get("raw_json_response") or "")
                step2b_provider = ""
                bull_args_str = ""
                bear_flaws_str = ""
                reasoning_trace = ""
                p_fresh = ""
                p_trap = ""
                p_gem_win = ""
                rubric_score = ""

                if raw_json_str:
                    try:
                        parsed = json.loads(raw_json_str)
                        if isinstance(parsed, dict):
                            step2b_provider = str(parsed.get("step2b_provider") or "")
                            cat = parsed.get("step2a_catalyst")
                            if isinstance(cat, dict):
                                bull_args = cat.get("bull_arguments") or []
                                bear_flaws = cat.get("bear_flaws_detected") or []
                                bull_args_str = " | ".join(str(x) for x in bull_args)
                                bear_flaws_str = " | ".join(str(x) for x in bear_flaws)
                                reasoning_trace = str(cat.get("audit_reasoning_trace") or "")
                            if not bear_flaws_str and isinstance(
                                parsed.get("red_team_flaws_detected"), list
                            ):
                                bear_flaws_str = " | ".join(
                                    str(x) for x in parsed["red_team_flaws_detected"]
                                )
                            gem = parsed.get("gemini_decision_1")
                            if isinstance(gem, dict):
                                p_fresh = str(gem.get("is_fresh_and_verifiable_prob", ""))
                                p_trap = str(gem.get("is_bull_trap_or_manipulation_prob", ""))
                                p_gem_win = str(gem.get("win_probability", ""))
                                rubric_score = str(gem.get("thesis_quality_score", ""))
                    except (ValueError, TypeError):
                        pass

                writer.writerow(
                    {
                        "anomaly_id": r.get("anomaly_id") or "",
                        "timestamp_utc": r.get("timestamp_utc") or "",
                        "venue": r.get("venue") or "",
                        "symbol_or_market_id": r.get("symbol_or_market_id") or "",
                        "asset_name_or_question": r.get("asset_name_or_question") or "",
                        "target_token_id": r.get("target_token_id") or "",
                        "proposed_direction": r.get("proposed_direction") or "",
                        "anomaly_price": r.get("anomaly_price") or "",
                        "rvol_ratio": r.get("rvol_ratio") if r.get("rvol_ratio") is not None else "",
                        "oi_delta_1h_pct": r.get("oi_delta_1h_pct") if r.get("oi_delta_1h_pct") is not None else "",
                        "funding_rate_hourly": r.get("funding_rate_hourly") if r.get("funding_rate_hourly") is not None else "",
                        "passed_gate2": r.get("passed_gate2") if r.get("passed_gate2") is not None else "",
                        "step2b_provider": step2b_provider,
                        "primary_catalyst_summary": r.get("primary_catalyst_summary") or "",
                        "bull_arguments": bull_args_str,
                        "bear_flaws_detected": bear_flaws_str,
                        "audit_reasoning_trace": reasoning_trace,
                        "source_timestamps_verified": r.get("source_timestamps_verified") if r.get("source_timestamps_verified") is not None else "",
                        "is_fresh_and_verifiable_prob": p_fresh,
                        "is_bull_trap_or_manipulation_prob": p_trap,
                        "gemini_win_probability": p_gem_win,
                        "thesis_quality_score": rubric_score,
                        "bull_thesis_score": r.get("bull_thesis_score") if r.get("bull_thesis_score") is not None else "",
                        "red_team_penalty": r.get("red_team_penalty") if r.get("red_team_penalty") is not None else "",
                        "red_team_veto": r.get("red_team_veto") if r.get("red_team_veto") is not None else "",
                        "final_confidence_score": r.get("final_confidence_score") if r.get("final_confidence_score") is not None else "",
                        "estimated_win_probability": r.get("estimated_win_probability") if r.get("estimated_win_probability") is not None else "",
                        "order_id": r.get("order_id") or "",
                        "execution_mode": r.get("execution_mode") or "",
                        "trade_direction": r.get("trade_direction") or "",
                        "trade_status": r.get("trade_status") or "",
                        "entry_price": r.get("entry_price") or "",
                        "exit_price": r.get("exit_price") or "",
                        "stop_loss_price": r.get("stop_loss_price") or "",
                        "take_profit_price": r.get("take_profit_price") or "",
                        "position_size_usd": r.get("position_size_usd") or "",
                        "position_size_units": r.get("position_size_units") or "",
                        "fees_paid_usd": r.get("fees_paid_usd") or "",
                        "slippage_est_usd": r.get("slippage_est_usd") or "",
                        "max_favorable_excursion_pct": r.get("max_favorable_excursion_pct") if r.get("max_favorable_excursion_pct") is not None else "",
                        "max_adverse_excursion_pct": r.get("max_adverse_excursion_pct") if r.get("max_adverse_excursion_pct") is not None else "",
                        "realized_pnl_usd": r.get("realized_pnl_usd") or "",
                        "close_reason": r.get("close_reason") or "",
                        "opened_at_utc": r.get("opened_at_utc") or "",
                        "closed_at_utc": r.get("closed_at_utc") or "",
                        "predicted_prob": r.get("predicted_prob") if r.get("predicted_prob") is not None else "",
                        "actual_outcome": r.get("actual_outcome") if r.get("actual_outcome") is not None else "",
                        "brier_score_component": r.get("brier_score_component") if r.get("brier_score_component") is not None else "",
                        "rolling_mean_brier_score": rolling_brier,
                        "ledger_equity_usd": ledger_dict.get("equity_usd", ""),
                        "ledger_available_margin_usd": ledger_dict.get("available_margin_usd", ""),
                        "ledger_locked_margin_usd": ledger_dict.get("locked_margin_usd", ""),
                        "ledger_realized_pnl_cumulative_usd": ledger_dict.get("realized_pnl_cumulative_usd", ""),
                        "ledger_total_fees_paid_usd": ledger_dict.get("total_fees_paid_usd", ""),
                    }
                )
                row_count += 1
        return out_path, row_count
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export BOLT Post-Mortem Audit Report to CSV"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite database (defaults to SQLITE_DB_PATH in settings)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="reports/bolt_audit_report.csv",
        help="Output CSV path (default: reports/bolt_audit_report.csv)",
    )
    args = parser.parse_args()
    out_path, count = asyncio.run(
        export_audit_report_csv(db_path=args.db, output_csv_path=args.out)
    )
    print(f"[INFO] Exported {count} audit rows to {out_path}")


if __name__ == "__main__":
    main()
