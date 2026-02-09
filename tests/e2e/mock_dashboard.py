"""
Mock Dashboard Sync — Recording Mock for DashboardSync

Records all push_trade/push_state/push_opportunity/push_log calls
in memory for test assertions. No Supabase interaction.
"""

from typing import Any, Dict, List, Optional


class MockDashboardSync:
    """
    Records all dashboard sync calls for assertion in tests.

    Interface-compatible with DashboardSync.
    """

    def __init__(self):
        # Recorded calls
        self.states: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        self.trade_closes: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self.opportunities: List[Dict[str, Any]] = []
        self.strategy_overrides: Dict[str, bool] = {}

        # Connection state
        self._available = True

    async def connect(self) -> None:
        """Simulate connection."""
        self._available = True

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._available = False

    async def get_strategy_overrides(self) -> Dict[str, bool]:
        """Return pre-configured strategy overrides."""
        return dict(self.strategy_overrides)

    async def push_state(
        self,
        balance_cents: int,
        available_balance_cents: int,
        daily_pnl_cents: int,
        total_positions: int,
        strategies: List[Dict[str, Any]],
        risk_config: Dict[str, Any],
    ) -> None:
        """Record a state push."""
        self.states.append({
            "balance_cents": balance_cents,
            "available_balance_cents": available_balance_cents,
            "daily_pnl_cents": daily_pnl_cents,
            "total_positions": total_positions,
            "strategies": strategies,
            "risk_config": risk_config,
        })

    async def push_trade(
        self,
        market_ticker: str,
        side: str,
        action: str,
        contracts: int,
        entry_price_cents: int,
        strategy: str,
        order_id: Optional[str] = None,
        reasoning: Optional[str] = None,
    ) -> None:
        """Record a trade push."""
        self.trades.append({
            "market_ticker": market_ticker,
            "side": side,
            "action": action,
            "contracts": contracts,
            "entry_price_cents": entry_price_cents,
            "strategy": strategy,
            "order_id": order_id,
            "reasoning": reasoning,
        })

    async def push_trade_close(
        self,
        trade_id: str,
        exit_price_cents: int,
        pnl_cents: int,
        exit_reason: str,
    ) -> None:
        """Record a trade close push."""
        self.trade_closes.append({
            "trade_id": trade_id,
            "exit_price_cents": exit_price_cents,
            "pnl_cents": pnl_cents,
            "exit_reason": exit_reason,
        })

    async def push_log(
        self,
        message: str,
        level: str = "INFO",
        strategy: Optional[str] = None,
    ) -> None:
        """Record a log push."""
        self.logs.append({
            "message": message,
            "level": level,
            "strategy": strategy,
        })

    async def push_opportunity(
        self,
        market_ticker: str,
        strategy: str,
        side: str,
        current_price_cents: int,
        target_price_cents: int,
        confidence: float,
        reasoning: Optional[str] = None,
        status: str = "active",
    ) -> None:
        """Record an opportunity push."""
        self.opportunities.append({
            "market_ticker": market_ticker,
            "strategy": strategy,
            "side": side,
            "current_price_cents": current_price_cents,
            "target_price_cents": target_price_cents,
            "confidence": confidence,
            "reasoning": reasoning,
            "status": status,
        })

    def reset(self) -> None:
        """Clear all recorded calls."""
        self.states.clear()
        self.trades.clear()
        self.trade_closes.clear()
        self.logs.clear()
        self.opportunities.clear()
