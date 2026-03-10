"""
Position Adoption — Manage Eddie's Pre-Existing IBKR Positions

Dae doesn't trade these positions (until graduated). Instead, it:
  1. Tracks them every cycle (current price, P&L)
  2. Applies configurable stop-loss / take-profit alerts
  3. Reports status via Telegram and dashboard
  4. Post-graduation: can execute exits autonomously

Adoption lifecycle:
  Eddie buys stock manually in IBKR
  -> Eddie tells Dae "manage TSLA" via Telegram
  -> Dae records adoption with entry snapshot
  -> Each cycle: fetch price, check TP/SL, alert if triggered
  -> Eddie says "drop TSLA" to release management
  -> Post-graduation: Dae can auto-exit on TP/SL triggers

Storage: adopted_positions table in trade_journal.db
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AdoptedPosition:
    """Snapshot of an adopted position with current market data."""
    symbol: str
    qty: int
    avg_cost: float         # dollars
    current_price: float    # dollars
    unrealized_pnl: float   # dollars
    pnl_pct: float          # percentage
    stop_loss_pct: float    # configured SL (e.g. 15.0 = -15%)
    take_profit_pct: float  # configured TP (e.g. 25.0 = +25%)
    adopted_at: str
    sl_triggered: bool = False
    tp_triggered: bool = False
    notes: str = ""


# Default risk parameters for adopted positions
DEFAULT_STOP_LOSS_PCT = 15.0   # -15% from entry
DEFAULT_TAKE_PROFIT_PCT = 25.0  # +25% from entry


class PositionAdoption:
    """
    Manages positions Eddie opened manually in IBKR.

    Opens its own SQLite connection to trade_journal.db.
    Creates adopted_positions table on first use.
    """

    def __init__(self, journal_db_path: str):
        self._db_path = journal_db_path
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create adopted_positions and sell_ladder tables if they don't exist."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS adopted_positions (
                    symbol TEXT PRIMARY KEY,
                    qty INTEGER NOT NULL,
                    avg_cost_cents INTEGER NOT NULL,
                    adopted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    stop_loss_pct REAL DEFAULT 15.0,
                    take_profit_pct REAL DEFAULT 25.0,
                    notes TEXT DEFAULT '',
                    active INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sell_ladder (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    tranche INTEGER NOT NULL,
                    target_price_cents INTEGER NOT NULL,
                    qty INTEGER NOT NULL,
                    label TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    triggered_at TIMESTAMP,
                    UNIQUE(symbol, tranche)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Adoption lifecycle ─────────────────────────────────────────────

    def adopt(
        self,
        symbol: str,
        qty: int,
        avg_cost_cents: int,
        stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT,
        notes: str = "",
    ) -> bool:
        """
        Adopt a position for Dae to manage.

        If the symbol is already adopted, updates qty/cost/params.
        Returns True if adoption succeeded.
        """
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO adopted_positions
                    (symbol, qty, avg_cost_cents, stop_loss_pct, take_profit_pct, notes, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(symbol) DO UPDATE SET
                    qty = excluded.qty,
                    avg_cost_cents = excluded.avg_cost_cents,
                    stop_loss_pct = excluded.stop_loss_pct,
                    take_profit_pct = excluded.take_profit_pct,
                    notes = excluded.notes,
                    active = 1
                """,
                (symbol.upper(), qty, avg_cost_cents, stop_loss_pct, take_profit_pct, notes),
            )
            conn.commit()
            logger.info(
                "Adopted position: %s x%d @ %dc | SL=%.1f%% TP=%.1f%%",
                symbol, qty, avg_cost_cents, stop_loss_pct, take_profit_pct,
            )
            return True
        except Exception as e:
            logger.error("Failed to adopt %s: %s", symbol, e)
            return False
        finally:
            conn.close()

    def drop(self, symbol: str) -> bool:
        """Release a position from Dae's management."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE adopted_positions SET active = 0 WHERE symbol = ? AND active = 1",
                (symbol.upper(),),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("Dropped adopted position: %s", symbol)
                return True
            return False
        finally:
            conn.close()

    def get_active(self) -> List[Dict[str, Any]]:
        """Get all actively managed positions."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM adopted_positions WHERE active = 1"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def is_adopted(self, symbol: str) -> bool:
        """Check if a symbol is currently adopted."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM adopted_positions WHERE symbol = ? AND active = 1",
                (symbol.upper(),),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def update_params(
        self,
        symbol: str,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
    ) -> bool:
        """Update TP/SL parameters for an adopted position."""
        conn = self._connect()
        try:
            updates = []
            params = []
            if stop_loss_pct is not None:
                updates.append("stop_loss_pct = ?")
                params.append(stop_loss_pct)
            if take_profit_pct is not None:
                updates.append("take_profit_pct = ?")
                params.append(take_profit_pct)
            if not updates:
                return False
            params.append(symbol.upper())
            conn.execute(
                f"UPDATE adopted_positions SET {', '.join(updates)} WHERE symbol = ? AND active = 1",
                params,
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # ── Sell ladder ─────────────────────────────────────────────────────

    def set_ladder(
        self,
        symbol: str,
        tranches: List[Dict[str, Any]],
    ) -> bool:
        """
        Set a phased sell ladder for an adopted position.

        Args:
            tranches: List of dicts with keys:
                tranche (int), target_price_cents (int), qty (int), label (str)

        Replaces any existing ladder for this symbol.
        """
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM sell_ladder WHERE symbol = ?", (symbol.upper(),)
            )
            for t in tranches:
                conn.execute(
                    "INSERT INTO sell_ladder (symbol, tranche, target_price_cents, qty, label) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        symbol.upper(),
                        t["tranche"],
                        t["target_price_cents"],
                        t["qty"],
                        t.get("label", ""),
                    ),
                )
            conn.commit()
            logger.info(
                "Sell ladder set for %s: %d tranches", symbol, len(tranches)
            )
            return True
        except Exception as e:
            logger.error("Failed to set ladder for %s: %s", symbol, e)
            return False
        finally:
            conn.close()

    def get_ladder(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all ladder tranches for a symbol."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM sell_ladder WHERE symbol = ? ORDER BY tranche",
                (symbol.upper(),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def check_ladder_triggers(
        self,
        symbol: str,
        current_price_cents: int,
    ) -> List[Dict[str, Any]]:
        """
        Check if any pending ladder tranches have been triggered.

        Returns list of triggered tranches (not yet marked as triggered).
        Does NOT mark them — caller decides whether to alert or execute.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM sell_ladder "
                "WHERE symbol = ? AND status = 'pending' AND target_price_cents <= ? "
                "ORDER BY tranche",
                (symbol.upper(), current_price_cents),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_tranche_triggered(self, symbol: str, tranche: int) -> None:
        """Mark a ladder tranche as triggered."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE sell_ladder SET status = 'triggered', triggered_at = CURRENT_TIMESTAMP "
                "WHERE symbol = ? AND tranche = ?",
                (symbol.upper(), tranche),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Cycle check ────────────────────────────────────────────────────

    def check_triggers(
        self,
        ibkr_positions: List[Dict[str, Any]],
    ) -> List[AdoptedPosition]:
        """
        Check all adopted positions against current IBKR data.

        Args:
            ibkr_positions: Live positions from IBKRMarket.get_positions()

        Returns:
            List of AdoptedPosition snapshots with trigger flags set.
        """
        adopted = self.get_active()
        if not adopted:
            return []

        # Index IBKR positions by symbol
        ibkr_by_symbol = {p["ticker"]: p for p in ibkr_positions}

        results = []
        for pos in adopted:
            symbol = pos["symbol"]
            ibkr_pos = ibkr_by_symbol.get(symbol)

            if not ibkr_pos:
                # Position no longer exists in IBKR — Eddie sold it manually
                logger.info(
                    "Adopted position %s no longer in IBKR — auto-dropping", symbol
                )
                self.drop(symbol)
                continue

            avg_cost = pos["avg_cost_cents"] / 100
            current_price = ibkr_pos.get("current_price_cents", 0) / 100

            if avg_cost <= 0:
                continue

            pnl_dollars = (current_price - avg_cost) * pos["qty"]
            pnl_pct = ((current_price - avg_cost) / avg_cost) * 100

            sl_triggered = pnl_pct <= -pos["stop_loss_pct"]
            tp_triggered = pnl_pct >= pos["take_profit_pct"]

            results.append(AdoptedPosition(
                symbol=symbol,
                qty=pos["qty"],
                avg_cost=avg_cost,
                current_price=current_price,
                unrealized_pnl=pnl_dollars,
                pnl_pct=pnl_pct,
                stop_loss_pct=pos["stop_loss_pct"],
                take_profit_pct=pos["take_profit_pct"],
                adopted_at=pos["adopted_at"],
                sl_triggered=sl_triggered,
                tp_triggered=tp_triggered,
                notes=pos.get("notes", ""),
            ))

        return results

    # ── Formatting ─────────────────────────────────────────────────────

    @staticmethod
    def format_status(positions: List[AdoptedPosition]) -> str:
        """Format adopted positions for Telegram/logs."""
        if not positions:
            return "No adopted positions. Use 'manage SYMBOL' to adopt one."

        lines = [f"[Managed Positions ({len(positions)})]", ""]

        total_pnl = 0.0
        for p in positions:
            total_pnl += p.unrealized_pnl

            # Trigger indicators
            flags = ""
            if p.sl_triggered:
                flags = " [STOP LOSS]"
            elif p.tp_triggered:
                flags = " [TAKE PROFIT]"

            lines.append(
                f"{p.symbol} x{p.qty} | "
                f"${p.current_price:.2f} (avg ${p.avg_cost:.2f}) | "
                f"P&L: ${p.unrealized_pnl:.2f} ({p.pnl_pct:+.1f}%)"
                f"{flags}"
            )
            lines.append(
                f"  SL: -{p.stop_loss_pct:.0f}% | TP: +{p.take_profit_pct:.0f}%"
            )

        lines.append(f"\nTotal P&L: ${total_pnl:.2f}")
        return "\n".join(lines)

    @staticmethod
    def format_ladder(ladder: List[Dict[str, Any]], symbol: str, current_price_cents: int) -> str:
        """Format sell ladder for Telegram/logs."""
        if not ladder:
            return f"No sell ladder set for {symbol}."

        current = current_price_cents / 100
        lines = [f"[{symbol} Sell Ladder] (current: ${current:.2f})", ""]

        for t in ladder:
            target = t["target_price_cents"] / 100
            status = t["status"].upper()
            label = t.get("label", "")
            qty = t["qty"]

            if status == "TRIGGERED":
                marker = "[SOLD]"
            elif current >= target:
                marker = "[READY]"
            else:
                pct_away = ((target - current) / current * 100) if current > 0 else 0
                marker = f"{pct_away:+.0f}% away"

            line = f"  T{t['tranche']}: ${target:.2f} x{qty} {marker}"
            if label:
                line += f" — {label}"
            lines.append(line)

        pending = [t for t in ladder if t["status"] == "pending"]
        triggered = [t for t in ladder if t["status"] == "triggered"]
        lines.append(f"\n{len(triggered)}/{len(ladder)} tranches filled")

        return "\n".join(lines)
