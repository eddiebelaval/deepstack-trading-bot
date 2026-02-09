"""
Trade Journal - SQLite-based Trade Logging

Persistent storage for trade history, performance analysis, and audit trail.
Follows the PaperTrader pattern from DeepStack but adapted for prediction markets.

Tables:
    - trades: Individual trade records
    - daily_summary: Aggregated daily performance
"""

import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


class TradeJournal:
    """
    SQLite-based trade journal for Kalshi bot.

    Provides persistent storage for trade history with methods for
    logging, querying, and generating performance reports.

    Example:
        >>> journal = TradeJournal("/path/to/trades.db")
        >>> trade_id = journal.log_trade(
        ...     market_ticker="INXD-25JAN26-4500",
        ...     side="yes",
        ...     action="buy",
        ...     contracts=10,
        ...     price_cents=48,
        ...     order_id="ord_123",
        ...     reasoning="Mean reversion: YES undervalued"
        ... )
        >>> journal.update_trade_fill(trade_id, fill_price_cents=47, pnl_cents=50)
    """

    # Connection pool settings
    POOL_SIZE = 5
    POOL_TIMEOUT = 10.0  # seconds

    def __init__(self, db_path: str, pool_size: int = 5):
        """
        Initialize trade journal with connection pooling.

        Args:
            db_path: Path to SQLite database file
            pool_size: Number of connections in pool
        """
        self.db_path = Path(db_path).expanduser()
        self._pool_size = pool_size

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connection pool
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._pool_lock = threading.Lock()
        self._initialized = False

        # Initialize database and pool
        self._init_db()
        self._init_pool()

        logger.info(f"TradeJournal initialized with WAL mode and {pool_size} connections")

    def _init_pool(self) -> None:
        """Initialize connection pool."""
        for _ in range(self._pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
        self._initialized = True

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimal settings."""
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,  # Safe with our pool management
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        # Synchronous NORMAL is safe with WAL and faster
        conn.execute("PRAGMA synchronous=NORMAL")
        # Increase cache size for better read performance
        conn.execute("PRAGMA cache_size=-64000")  # 64MB
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")

        return conn

    def _init_db(self) -> None:
        """Create database tables if they don't exist."""
        # Use a temporary connection for schema setup
        conn = self._create_connection()
        try:
            cursor = conn.cursor()

            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    market_ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    contracts INTEGER NOT NULL,
                    entry_price_cents INTEGER NOT NULL,
                    fill_price_cents INTEGER,
                    exit_price_cents INTEGER,
                    pnl_cents INTEGER,
                    order_id TEXT,
                    exit_order_id TEXT,
                    status TEXT DEFAULT 'pending',
                    reasoning TEXT,
                    exit_reason TEXT,
                    strategy TEXT DEFAULT 'mean_reversion',
                    session_date DATE,
                    metadata TEXT
                )
            """)

            # Daily summary table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date DATE PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    gross_pnl_cents INTEGER DEFAULT 0,
                    fees_cents INTEGER DEFAULT 0,
                    net_pnl_cents INTEGER DEFAULT 0,
                    largest_win_cents INTEGER DEFAULT 0,
                    largest_loss_cents INTEGER DEFAULT 0,
                    avg_winner_cents INTEGER DEFAULT 0,
                    avg_loser_cents INTEGER DEFAULT 0,
                    max_contracts INTEGER DEFAULT 0,
                    starting_balance_cents INTEGER,
                    ending_balance_cents INTEGER,
                    notes TEXT
                )
            """)

            # Indices for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_date
                ON trades(session_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_ticker
                ON trades(market_ticker)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_status
                ON trades(status)
            """)

            # Additional composite indexes for common query patterns
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_date_status
                ON trades(session_date, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_strategy_status
                ON trades(strategy, status)
            """)

            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection from the pool.

        Uses a connection pool to reduce overhead and improve concurrency.
        Connections are returned to the pool after use.
        """
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = self._pool.get(timeout=self.POOL_TIMEOUT)
            yield conn
        except Empty:
            # Pool exhausted, create a temporary connection
            logger.warning("Connection pool exhausted, creating temporary connection")
            conn = self._create_connection()
            yield conn
            conn.close()
            conn = None
        finally:
            if conn is not None:
                self._pool.put(conn)

    def close(self) -> None:
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
        logger.info("TradeJournal connections closed")

    def log_trade(
        self,
        market_ticker: str,
        side: str,
        action: str,
        contracts: int,
        price_cents: int,
        order_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        strategy: str = "mean_reversion",
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Log a new trade entry.

        Args:
            market_ticker: Market ticker (e.g., "INXD-25JAN26-4500")
            side: "yes" or "no"
            action: "buy" or "sell"
            contracts: Number of contracts
            price_cents: Entry price in cents
            order_id: Kalshi order ID
            reasoning: Strategy reasoning
            strategy: Strategy name
            metadata: Additional metadata as dict

        Returns:
            Trade ID (UUID)
        """
        trade_id = str(uuid.uuid4())[:8]  # Short ID for readability
        today = date.today()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (
                    id, market_ticker, side, action, contracts,
                    entry_price_cents, order_id, reasoning, strategy,
                    session_date, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    trade_id,
                    market_ticker,
                    side,
                    action,
                    contracts,
                    price_cents,
                    order_id,
                    reasoning,
                    strategy,
                    today,
                    str(metadata) if metadata else None,
                ),
            )
            conn.commit()

        logger.info(
            f"Trade logged: {trade_id} | {market_ticker} {action} {contracts} "
            f"{side} @ {price_cents}c"
        )

        return trade_id

    def update_trade_fill(
        self,
        trade_id: str,
        fill_price_cents: int,
        pnl_cents: Optional[int] = None,
    ) -> None:
        """
        Update trade with fill information.

        Args:
            trade_id: Trade ID
            fill_price_cents: Actual fill price
            pnl_cents: Realized P&L if position closed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trades
                SET fill_price_cents = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (fill_price_cents, trade_id),
            )

            if pnl_cents is not None:
                cursor.execute(
                    """
                    UPDATE trades
                    SET pnl_cents = ?,
                        status = 'closed'
                    WHERE id = ?
                    """,
                    (pnl_cents, trade_id),
                )

            conn.commit()

        logger.info(
            f"Trade updated: {trade_id} | Fill: {fill_price_cents}c, "
            f"P&L: {pnl_cents}c"
        )

    def close_trade(
        self,
        trade_id: str,
        exit_price_cents: int,
        exit_order_id: Optional[str] = None,
        exit_reason: Optional[str] = None,
    ) -> int:
        """
        Close a trade and calculate P&L.

        Args:
            trade_id: Trade ID
            exit_price_cents: Exit price
            exit_order_id: Exit order ID
            exit_reason: Reason for exit

        Returns:
            Realized P&L in cents
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get trade info
            cursor.execute(
                "SELECT * FROM trades WHERE id = ?",
                (trade_id,),
            )
            trade = cursor.fetchone()

            if not trade:
                logger.warning(f"Trade not found: {trade_id}")
                return 0

            # Calculate P&L
            entry_price = trade["fill_price_cents"] or trade["entry_price_cents"]
            contracts = trade["contracts"]
            side = trade["side"]
            action = trade["action"]

            # P&L calculation for prediction markets
            # Buy: profit if exit > entry
            # Sell: profit if exit < entry
            if action == "buy":
                pnl_cents = (exit_price_cents - entry_price) * contracts
            else:
                pnl_cents = (entry_price - exit_price_cents) * contracts

            # Update trade
            cursor.execute(
                """
                UPDATE trades
                SET exit_price_cents = ?,
                    exit_order_id = ?,
                    exit_reason = ?,
                    pnl_cents = ?,
                    status = 'closed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (exit_price_cents, exit_order_id, exit_reason, pnl_cents, trade_id),
            )
            conn.commit()

        logger.info(
            f"Trade closed: {trade_id} | Exit: {exit_price_cents}c, "
            f"P&L: {pnl_cents}c ({exit_reason})"
        )

        return pnl_cents

    def get_trade(self, trade_id: str) -> Optional[Dict]:
        """Get trade by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def close_trades_by_settlement(
        self,
        ticker: str,
        market_result: str,
    ) -> int:
        """
        Close all open trades for a settled market ticker.

        Computes per-trade P&L from market result:
          - YES result: YES contracts pay 100c, NO contracts pay 0c
          - NO result:  YES contracts pay 0c, NO contracts pay 100c

        Returns:
            Number of trades closed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades WHERE market_ticker = ? AND status = 'open'",
                (ticker,),
            )
            open_trades = cursor.fetchall()

            if not open_trades:
                return 0

            closed = 0
            for trade in open_trades:
                entry = trade["fill_price_cents"] or trade["entry_price_cents"]
                contracts = trade["contracts"]
                side = trade["side"]
                action = trade["action"]

                # Settlement payout: winning side gets 100c, losing side gets 0c
                if market_result == "yes":
                    settle_price = 100 if side == "yes" else 0
                elif market_result == "no":
                    settle_price = 0 if side == "yes" else 100
                else:
                    settle_price = 0  # void

                if action == "buy":
                    pnl = (settle_price - entry) * contracts
                else:
                    pnl = (entry - settle_price) * contracts

                cursor.execute(
                    """
                    UPDATE trades
                    SET exit_price_cents = ?,
                        exit_reason = ?,
                        pnl_cents = ?,
                        status = 'closed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (settle_price, f"settlement:{market_result}", pnl, trade["id"]),
                )
                closed += 1
                logger.info(
                    f"Settlement closed trade {trade['id']}: "
                    f"{ticker} {side} {action} {contracts}x @ {entry}c -> "
                    f"{settle_price}c = {pnl:+d}c ({market_result})"
                )

            conn.commit()
            return closed

    def get_open_trades(self) -> List[Dict]:
        """Get all open trades."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY created_at"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_daily_pnl(self, trade_date: Optional[date] = None) -> int:
        """
        Get total P&L for a date in cents.

        Args:
            trade_date: Date to query (default: today)

        Returns:
            Total P&L in cents
        """
        trade_date = trade_date or date.today()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(pnl_cents), 0) as total_pnl
                FROM trades
                WHERE session_date = ? AND status = 'closed'
                """,
                (trade_date,),
            )
            row = cursor.fetchone()
            return row["total_pnl"] if row else 0

    def get_trade_statistics(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive trade statistics.

        Args:
            start_date: Start of period (default: all time)
            end_date: End of period (default: today)

        Returns:
            Dict with performance metrics
        """
        end_date = end_date or date.today()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build query based on date range
            if start_date:
                date_filter = "AND session_date BETWEEN ? AND ?"
                params = (start_date, end_date)
            else:
                date_filter = "AND session_date <= ?"
                params = (end_date,)

            # Get closed trades
            cursor.execute(
                f"""
                SELECT * FROM trades
                WHERE status = 'closed' {date_filter}
                ORDER BY created_at
                """,
                params,
            )
            trades = [dict(row) for row in cursor.fetchall()]

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "breakeven_trades": 0,
                "win_rate": 0.0,
                "total_pnl_cents": 0,
                "avg_pnl_cents": 0,
                "gross_profit_cents": 0,
                "gross_loss_cents": 0,
                "largest_win_cents": 0,
                "largest_loss_cents": 0,
                "avg_winner_cents": 0,
                "avg_loser_cents": 0,
                "profit_factor": 0.0,
            }

        # Calculate statistics
        winners = [t for t in trades if (t.get("pnl_cents") or 0) > 0]
        losers = [t for t in trades if (t.get("pnl_cents") or 0) < 0]
        breakeven = [t for t in trades if (t.get("pnl_cents") or 0) == 0]

        total_pnl = sum(t.get("pnl_cents", 0) or 0 for t in trades)
        gross_profit = sum(t.get("pnl_cents", 0) or 0 for t in winners)
        gross_loss = abs(sum(t.get("pnl_cents", 0) or 0 for t in losers))

        return {
            "total_trades": len(trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "breakeven_trades": len(breakeven),
            "win_rate": len(winners) / len(trades) if trades else 0,
            "total_pnl_cents": total_pnl,
            "avg_pnl_cents": total_pnl / len(trades) if trades else 0,
            "gross_profit_cents": gross_profit,
            "gross_loss_cents": gross_loss,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            "largest_win_cents": max((t.get("pnl_cents") or 0 for t in trades), default=0),
            "largest_loss_cents": min((t.get("pnl_cents") or 0 for t in trades), default=0),
            "avg_winner_cents": sum(t.get("pnl_cents", 0) or 0 for t in winners) / len(winners) if winners else 0,
            "avg_loser_cents": sum(t.get("pnl_cents", 0) or 0 for t in losers) / len(losers) if losers else 0,
        }

    def generate_daily_summary(self, summary_date: Optional[date] = None) -> str:
        """
        Generate text summary of daily trading.

        Args:
            summary_date: Date to summarize (default: today)

        Returns:
            Formatted summary string
        """
        summary_date = summary_date or date.today()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get day's trades
            cursor.execute(
                """
                SELECT * FROM trades
                WHERE session_date = ?
                ORDER BY created_at
                """,
                (summary_date,),
            )
            trades = [dict(row) for row in cursor.fetchall()]

        if not trades:
            return f"No trades on {summary_date}"

        # Calculate metrics
        closed = [t for t in trades if t["status"] == "closed"]
        open_trades = [t for t in trades if t["status"] == "open"]

        total_pnl = sum(t.get("pnl_cents", 0) or 0 for t in closed)
        winners = len([t for t in closed if (t.get("pnl_cents") or 0) > 0])
        losers = len([t for t in closed if (t.get("pnl_cents") or 0) < 0])

        lines = [
            f"=== Daily Summary: {summary_date} ===",
            f"Total Trades: {len(trades)}",
            f"Closed: {len(closed)} (W: {winners}, L: {losers})",
            f"Open: {len(open_trades)}",
            f"Net P&L: ${total_pnl / 100:.2f}",
            "",
            "Trades:",
        ]

        for t in trades:
            pnl = t.get("pnl_cents", 0) or 0
            pnl_str = f"${pnl/100:+.2f}" if pnl else "pending"
            lines.append(
                f"  {t['market_ticker']}: {t['action']} {t['contracts']} "
                f"{t['side']} @ {t['entry_price_cents']}c -> {pnl_str}"
            )

        return "\n".join(lines)

    def save_daily_summary(self, summary_date: Optional[date] = None) -> None:
        """
        Save daily summary to daily_summary table.

        Args:
            summary_date: Date to summarize (default: today)
        """
        summary_date = summary_date or date.today()
        stats = self.get_trade_statistics(start_date=summary_date, end_date=summary_date)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO daily_summary (
                    date, total_trades, winning_trades, losing_trades,
                    gross_pnl_cents, net_pnl_cents, largest_win_cents,
                    largest_loss_cents, avg_winner_cents, avg_loser_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_date,
                    stats["total_trades"],
                    stats["winning_trades"],
                    stats["losing_trades"],
                    stats["gross_profit_cents"],
                    stats["total_pnl_cents"],
                    stats["largest_win_cents"],
                    stats["largest_loss_cents"],
                    int(stats["avg_winner_cents"]),
                    int(stats["avg_loser_cents"]),
                ),
            )
            conn.commit()

        logger.info(f"Daily summary saved for {summary_date}")
