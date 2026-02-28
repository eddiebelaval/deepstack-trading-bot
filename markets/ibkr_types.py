"""
IBKR data types for stock positions and market data.

Follows the Sure Finance Holding cost basis pattern.
All monetary values in cents (integers).
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StockPosition:
    """
    Enriched stock position with cost basis tracking.

    All monetary fields are in cents (integers) to avoid
    floating-point precision issues in financial calculations.

    Attributes:
        symbol: Stock ticker symbol (e.g., "AAPL")
        qty: Number of shares held (negative for short)
        avg_cost_cents: Average cost per share in cents
        current_price_cents: Current market price per share in cents
        market_value_cents: Total market value in cents (qty * current_price)
        unrealized_pnl_cents: Unrealized profit/loss in cents
        realized_pnl_cents: Realized profit/loss in cents
        day_change_cents: Day's price change in cents
        exchange: Trading exchange (default: SMART routing)
    """

    symbol: str
    qty: int
    avg_cost_cents: int
    current_price_cents: int
    market_value_cents: int
    unrealized_pnl_cents: int
    realized_pnl_cents: int = 0
    day_change_cents: int = 0
    exchange: str = "SMART"

    @property
    def cost_basis_cents(self) -> int:
        """Total cost basis in cents (qty * avg_cost)."""
        return self.qty * self.avg_cost_cents

    @property
    def return_pct(self) -> float:
        """Return percentage based on cost basis."""
        if self.cost_basis_cents == 0:
            return 0.0
        return (self.unrealized_pnl_cents / self.cost_basis_cents) * 100

    def __repr__(self) -> str:
        return (
            f"StockPosition(symbol='{self.symbol}', qty={self.qty}, "
            f"avg_cost=${self.avg_cost_cents / 100:.2f}, "
            f"current=${self.current_price_cents / 100:.2f}, "
            f"pnl=${self.unrealized_pnl_cents / 100:.2f})"
        )
