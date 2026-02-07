"""
Strategy Base Classes

Abstract base class for all trading strategies. Defines the interface that
all strategies must implement for the StrategyManager to orchestrate them.

Design Principles:
    - Strategies are stateless scanners (state stored in self if needed)
    - Each strategy returns scored opportunities
    - Exit conditions are strategy-specific
    - Configuration is passed at initialization
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class TradingOpportunity:
    """
    Represents a potential trading opportunity identified by a strategy.

    Attributes:
        ticker: Market ticker (e.g., "INXD-25JAN26-4500")
        title: Human-readable market title
        side: "yes" or "no"
        entry_price_cents: Recommended entry price in cents
        current_yes_price: Current YES price
        current_no_price: Current NO price
        volume: Market volume
        score: Opportunity quality score (0-100, higher = better)
        reasoning: Human-readable explanation of why this is an opportunity
        expected_profit_cents: Target profit if trade succeeds
        max_loss_cents: Maximum loss (stop loss level)
        strategy_name: Name of strategy that found this opportunity
        metadata: Additional strategy-specific data
    """

    ticker: str
    title: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    current_yes_price: int
    current_no_price: int
    volume: int
    score: float
    reasoning: str
    expected_profit_cents: int
    max_loss_cents: int
    strategy_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate fields after initialization."""
        if self.side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got '{self.side}'")
        if not (0 <= self.score <= 100):
            raise ValueError(f"score must be 0-100, got {self.score}")
        if not (1 <= self.entry_price_cents <= 99):
            raise ValueError(f"entry_price_cents must be 1-99, got {self.entry_price_cents}")


@dataclass
class ExitSignal:
    """
    Represents a signal to exit a position.

    Attributes:
        should_exit: Whether position should be exited
        reason: Human-readable exit reason
        exit_type: Category of exit ("take_profit", "stop_loss", "expiry", "manual", "hold")
        current_price_cents: Current price for the position side
        pnl_cents: Current profit/loss in cents
        urgency: 0-1 indicating how urgently to exit (1 = immediate)
    """

    should_exit: bool
    reason: str
    exit_type: str
    current_price_cents: int
    pnl_cents: int
    urgency: float = 0.5

    def __post_init__(self):
        """Validate fields after initialization."""
        valid_exit_types = ("take_profit", "stop_loss", "expiry", "manual", "hold")
        if self.exit_type not in valid_exit_types:
            raise ValueError(f"exit_type must be one of {valid_exit_types}")


@dataclass
class StrategyConfig:
    """
    Base configuration for all strategies.

    Strategies can extend this with their specific parameters.
    All monetary values in cents unless noted otherwise.

    Attributes:
        name: Strategy identifier
        enabled: Whether strategy is active
        markets: List of market configurations to scan
        take_profit_cents: Default take profit level
        stop_loss_cents: Default stop loss level
        min_volume: Minimum volume to consider
        min_score: Minimum opportunity score to trade
        max_positions: Maximum concurrent positions for this strategy
        parameters: Strategy-specific parameters
    """

    name: str
    enabled: bool = True
    markets: List[Dict[str, str]] = field(default_factory=list)
    take_profit_cents: int = 8
    stop_loss_cents: int = 5
    min_volume: int = 100
    min_score: float = 30.0
    max_positions: int = 5
    parameters: Dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    """
    Abstract base class for all trading strategies.

    Strategies implement market scanning logic and exit condition checking.
    The StrategyManager calls these methods to orchestrate trading.

    State Management:
        Strategies can maintain internal state (e.g., price history for
        momentum strategies) in instance variables. State is persisted
        only through the trade journal.

    Example Implementation:
        >>> class MyStrategy(Strategy):
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_strategy"
        ...
        ...     async def scan_opportunities(self, markets):
        ...         opportunities = []
        ...         for market in markets:
        ...             if self._is_opportunity(market):
        ...                 opportunities.append(self._create_opportunity(market))
        ...         return opportunities
        ...
        ...     async def check_exit(self, position, current_price):
        ...         pnl = current_price - position["entry_price"]
        ...         if pnl >= self.take_profit:
        ...             return ExitSignal(should_exit=True, ...)
        ...         return ExitSignal(should_exit=False, ...)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy configuration dict. Expected keys:
                - take_profit_cents: Take profit level
                - stop_loss_cents: Stop loss level
                - min_volume: Minimum market volume
                - min_score: Minimum opportunity score
                - Additional strategy-specific parameters
        """
        self.config = config
        self.take_profit = config.get("take_profit_cents", 8)
        self.stop_loss = config.get("stop_loss_cents", 5)
        self.min_volume = config.get("min_volume", 100)
        self.min_score = config.get("min_score", 30.0)

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique strategy identifier.

        Returns:
            Strategy name (e.g., "mean_reversion", "momentum")
        """
        pass

    @property
    def description(self) -> str:
        """
        Human-readable strategy description.

        Returns:
            Description string
        """
        return f"{self.name} trading strategy"

    @abstractmethod
    async def scan_opportunities(
        self,
        markets: List[Dict],
        existing_positions: Optional[Dict[str, Any]] = None,
    ) -> List[TradingOpportunity]:
        """
        Scan markets for trading opportunities.

        This is the core method where strategy logic lives. Analyzes market
        data and returns scored opportunities.

        Args:
            markets: List of market data dicts from API. Expected keys:
                - ticker: Market ticker
                - title: Market title
                - yes_bid, yes_ask: YES prices
                - no_bid, no_ask: NO prices
                - volume: Trading volume
                - status: Market status
            existing_positions: Dict of ticker -> position data to avoid
                adding to existing positions

        Returns:
            List of TradingOpportunity objects, ideally sorted by score
        """
        pass

    @abstractmethod
    async def check_exit(
        self,
        position: Dict[str, Any],
        current_price: int,
        market_data: Optional[Dict] = None,
    ) -> ExitSignal:
        """
        Check if a position should be exited.

        Called periodically for each open position. Strategy determines
        whether exit conditions are met.

        Args:
            position: Position data dict. Expected keys:
                - ticker: Market ticker
                - side: "yes" or "no"
                - entry_price: Entry price in cents
                - contracts: Number of contracts
                - entry_time: When position was opened
            current_price: Current price for the position side in cents
            market_data: Optional additional market data

        Returns:
            ExitSignal indicating whether and how to exit
        """
        pass

    def get_historical_stats(self) -> Dict[str, float]:
        """
        Get assumed/historical statistics for position sizing.

        Used by Kelly Criterion calculator. Override to provide
        strategy-specific statistics.

        Returns:
            Dict with:
                - win_rate: Historical/assumed win rate (0-1)
                - avg_win_cents: Average winning trade in cents
                - avg_loss_cents: Average losing trade in cents (positive)
        """
        # Default conservative stats
        return {
            "win_rate": 0.55,
            "avg_win_cents": float(self.take_profit),
            "avg_loss_cents": float(self.stop_loss),
        }

    def calculate_edge(self) -> Dict[str, float]:
        """
        Calculate theoretical edge of the strategy.

        Returns:
            Dict with edge metrics:
                - expected_value_cents: EV per trade
                - win_loss_ratio: Risk/reward ratio
                - kelly_pct: Optimal Kelly fraction
                - assumed_win_rate: Win rate used
        """
        stats = self.get_historical_stats()
        win_rate = stats["win_rate"]
        avg_win = stats["avg_win_cents"]
        avg_loss = stats["avg_loss_cents"]

        # Expected value per trade
        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Kelly %
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        if win_loss_ratio > 0:
            kelly = ((win_rate * win_loss_ratio) - (1 - win_rate)) / win_loss_ratio
        else:
            kelly = 0

        return {
            "expected_value_cents": ev,
            "win_loss_ratio": win_loss_ratio,
            "kelly_pct": max(0, kelly),
            "assumed_win_rate": win_rate,
        }

    def get_exit_price(
        self,
        entry_price_cents: int,
        side: str,
        exit_type: str,
    ) -> int:
        """
        Calculate target exit price for limit orders.

        Args:
            entry_price_cents: Entry price
            side: "yes" or "no"
            exit_type: "take_profit" or "stop_loss"

        Returns:
            Target price in cents
        """
        if exit_type == "take_profit":
            return entry_price_cents + self.take_profit
        elif exit_type == "stop_loss":
            return max(1, entry_price_cents - self.stop_loss)
        else:
            return entry_price_cents

    def validate_config(self) -> tuple[bool, str]:
        """
        Validate strategy configuration.

        Override to add strategy-specific validation.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.take_profit <= 0:
            return False, "take_profit_cents must be positive"
        if self.stop_loss <= 0:
            return False, "stop_loss_cents must be positive"
        if self.min_volume < 0:
            return False, "min_volume cannot be negative"

        return True, ""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
