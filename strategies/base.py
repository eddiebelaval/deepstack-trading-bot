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

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
    side: str  # "yes", "no", "buy", or "sell"
    entry_price_cents: int
    current_yes_price: int
    current_no_price: int
    volume: int
    score: float
    reasoning: str
    expected_profit_cents: int
    max_loss_cents: int
    strategy_name: str = ""
    asset_class: str = "prediction_market"  # "prediction_market" or "stock"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate fields after initialization."""
        valid_sides = ("yes", "no", "buy", "sell")
        if self.side not in valid_sides:
            raise ValueError(f"side must be one of {valid_sides}, got '{self.side}'")
        if not (0 <= self.score <= 100):
            raise ValueError(f"score must be 0-100, got {self.score}")
        # Only enforce 1-99 price range for prediction markets
        if self.asset_class == "prediction_market":
            if not (1 <= self.entry_price_cents <= 99):
                raise ValueError(f"entry_price_cents must be 1-99 for prediction markets, got {self.entry_price_cents}")


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
        self._performance_tracker = None  # Set by main.py to enable learning loop

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

    def apply_adaptive_params(self, params: Dict[str, float]) -> None:
        """Update take_profit and stop_loss from learned parameters."""
        old_tp, old_sl = self.take_profit, self.stop_loss
        self.take_profit = int(params["take_profit_cents"])
        self.stop_loss = int(params["stop_loss_cents"])
        logger.info(
            f"[{self.name}] Adaptive thresholds: "
            f"TP {old_tp}c -> {self.take_profit}c, "
            f"SL {old_sl}c -> {self.stop_loss}c"
        )

    # Minimum absolute floors for safety — prevents params from going to zero
    _PARAM_FLOORS: Dict[str, float] = {
        "min_volume": 10,
        "min_score": 5,
        "price_floor_cents": 1,
        "price_ceiling_cents": 1,
        "momentum_threshold": 0.005,
        "min_profit_cents": 1,
        "min_liquidity": 5,
        "max_spread_cents": 1,
        "price_diff_threshold_cents": 1,
        "min_match_score": 0.1,
        "min_polymarket_volume": 100,
        "lookback_periods": 2,
    }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Each subclass gets its own cooldown tracker
        if not hasattr(cls, '_param_last_adapted'):
            cls._param_last_adapted: Dict[str, datetime] = {}

    def apply_parameter_flags(self, flags: List[Dict[str, Any]]) -> None:
        """Apply AI-suggested parameter adjustments with safety guardrails.

        Each flag dict has: param, current, suggested, reason.
        Guardrails:
          - Only mutates attributes that exist on self
          - Clamps change to +/-50% of current value
          - Enforces absolute minimum floors per param type
          - 30-minute cooldown between changes to same param
        """
        if not hasattr(self, '_param_last_adapted'):
            self._param_last_adapted = {}

        now = datetime.now()
        cooldown_seconds = 30 * 60  # 30 minutes

        for flag in flags:
            param = flag.get("param")
            suggested = flag.get("suggested")
            reason = flag.get("reason", "AI suggestion")

            if not param or suggested is None:
                continue

            if not hasattr(self, param):
                logger.debug(f"[{self.name}] Skipping unknown param '{param}'")
                continue

            # Cooldown check
            last = self._param_last_adapted.get(param)
            if last and (now - last).total_seconds() < cooldown_seconds:
                logger.debug(
                    f"[{self.name}] Param '{param}' on cooldown, skipping"
                )
                continue

            old_value = getattr(self, param)

            # Bounds clamping: max +/-50% from current value
            if old_value != 0:
                lower = old_value * 0.5
                upper = old_value * 1.5
            else:
                lower = 0
                upper = abs(suggested) * 1.5 if suggested != 0 else 1

            clamped = max(lower, min(upper, suggested))

            # Enforce absolute minimum floor
            floor = self._PARAM_FLOORS.get(param, 0)
            clamped = max(floor, clamped)

            # Cast to match original type
            if isinstance(old_value, int):
                clamped = int(round(clamped))
            else:
                clamped = float(clamped)

            if clamped == old_value:
                continue

            setattr(self, param, clamped)
            self._param_last_adapted[param] = now
            logger.info(
                f"[{self.name}] Adapted {param}: {old_value} -> {clamped} "
                f"(reason: {reason})"
            )

    def get_historical_stats(self) -> Dict[str, float]:
        """
        Get statistics for position sizing (Kelly Criterion).

        Routes through PerformanceTracker when attached (returns
        Bayesian-blended stats). Falls back to _get_prior_stats()
        when no tracker is available.
        """
        if self._performance_tracker is not None:
            return self._performance_tracker.get_blended_stats(self.name)
        return self._get_prior_stats()

    def _get_prior_stats(self) -> Dict[str, float]:
        """
        Get hardcoded prior statistics for this strategy.

        Override in subclasses to provide strategy-specific priors.
        These values seed the Bayesian blend when the learning loop
        is active.

        Returns:
            Dict with:
                - win_rate: Assumed win rate (0-1)
                - avg_win_cents: Average winning trade in cents
                - avg_loss_cents: Average losing trade in cents (positive)
        """
        # Neutral priors — let Bayesian learning converge to reality
        return {
            "win_rate": 0.50,
            "avg_win_cents": 6.0,
            "avg_loss_cents": 6.0,
        }

    def calculate_edge(self, commission_cents: float = 2.0) -> Dict[str, float]:
        """
        Calculate theoretical edge of the strategy, net of transaction costs.

        Kalshi charges per-contract fees:
        - Market orders: 7c/contract (entry) + 7c/contract (exit) = 14c round-trip
        - Limit orders: 2c/contract (entry) + 2c/contract (exit) = 4c round-trip
        Default assumes limit orders (2c each side = 4c round-trip).

        Args:
            commission_cents: Per-side commission in cents (default: 2.0 for limit orders)

        Returns:
            Dict with edge metrics:
                - expected_value_cents: EV per trade (GROSS, before fees)
                - expected_value_net_cents: EV per trade (NET, after fees)
                - round_trip_commission_cents: Total round-trip commission
                - win_loss_ratio: Risk/reward ratio
                - kelly_pct: Optimal Kelly fraction (based on net EV)
                - assumed_win_rate: Win rate used
                - breakeven_win_rate: Win rate needed to break even after fees
        """
        stats = self.get_historical_stats()
        win_rate = stats["win_rate"]
        avg_win = stats["avg_win_cents"]
        avg_loss = stats["avg_loss_cents"]
        round_trip = commission_cents * 2

        # Gross EV (before fees)
        ev_gross = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Net EV (after fees): winners pay commission on both sides, losers pay on both sides
        net_win = avg_win - round_trip
        net_loss = avg_loss + round_trip
        ev_net = (win_rate * net_win) - ((1 - win_rate) * net_loss)

        # Kelly % based on net values
        win_loss_ratio = net_win / net_loss if net_loss > 0 else 0
        if win_loss_ratio > 0 and net_win > 0:
            kelly = ((win_rate * win_loss_ratio) - (1 - win_rate)) / win_loss_ratio
        else:
            kelly = 0

        # Breakeven win rate after fees: solve win_rate * net_win = (1-win_rate) * net_loss
        # => win_rate = net_loss / (net_win + net_loss)
        if net_win > 0 and net_loss > 0:
            breakeven_wr = net_loss / (net_win + net_loss)
        elif net_win <= 0:
            breakeven_wr = 1.0  # Cannot break even — fees exceed profit
        else:
            breakeven_wr = 0.0

        return {
            "expected_value_cents": ev_gross,
            "expected_value_net_cents": ev_net,
            "round_trip_commission_cents": round_trip,
            "win_loss_ratio": win_loss_ratio,
            "kelly_pct": max(0, kelly),
            "assumed_win_rate": win_rate,
            "breakeven_win_rate": breakeven_wr,
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
