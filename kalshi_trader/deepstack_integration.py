"""
DeepStack Integration for Kalshi Trading Bot

Bridges the Kalshi trading bot with DeepStack's risk management components:
- KellyPositionSizer for optimal position sizing
- EmotionalFirewall for behavioral controls

Adapts these components for prediction market specifics (prices in cents,
24/7 trading, contract-based positions).
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Add DeepStack to path for importing risk management components
# Path is configurable via environment variable
DEEPSTACK_PATH = os.getenv('DEEPSTACK_PATH', '/Users/eddiebelaval/Development/id8/products/deepstack')
if DEEPSTACK_PATH not in sys.path:
    sys.path.insert(0, DEEPSTACK_PATH)

from core.risk.kelly_position_sizer import KellyPositionSizer
from core.psychology.emotional_firewall import EmotionalFirewall

from .config import KalshiConfig
from .exceptions import DailyLossLimitHit, RiskLimitExceeded

logger = logging.getLogger(__name__)


class DeepStackIntegration:
    """
    Bridge between Kalshi bot and DeepStack risk management.

    Provides a unified interface for risk checks, position sizing, and
    trade recording. Adapts stock-focused components for prediction markets.

    Example:
        >>> config = KalshiConfig()
        >>> integration = DeepStackIntegration(config, account_balance=1000.0)
        >>>
        >>> # Check if trade is allowed
        >>> result = integration.check_trade_allowed("INXD-25JAN26-4500")
        >>> if result["allowed"]:
        ...     size = integration.calculate_position_size(0.55, 5.0, 10.0)
        ...     print(f"Recommended size: ${size['position_size']:.2f}")
    """

    def __init__(
        self,
        config: KalshiConfig,
        account_balance: float,
    ):
        """
        Initialize DeepStack integration.

        Args:
            config: KalshiConfig with risk parameters
            account_balance: Current account balance in dollars
        """
        self.config = config
        self.account_balance = account_balance

        # Initialize Kelly position sizer
        # Adapted for prediction markets: smaller max positions, lower exposure
        # Handle zero balance case (new account or no funds)
        effective_balance = max(account_balance, config.min_position_size)
        max_pos_pct = min(config.max_position_size / effective_balance, 0.25) if effective_balance > 0 else 0.25

        self.kelly_sizer = KellyPositionSizer(
            account_balance=effective_balance,
            max_position_pct=max_pos_pct,
            max_total_exposure=0.5,  # More conservative for prediction markets
            min_position_size=config.min_position_size,
            max_position_size=config.max_position_size,
        )

        # Initialize emotional firewall
        # Disabled late night/weekend checks for 24/7 markets
        self.firewall = EmotionalFirewall(
            enable_all_checks=True,
            enable_late_night_check=False,  # Kalshi trades 24/7
            enable_weekend_check=False,  # Kalshi trades on weekends
            enable_revenge_check=True,
            enable_overtrading_check=True,
            enable_streak_check=True,
            enable_panic_check=True,
            timezone_name="America/New_York",
        )

        # Daily P&L tracking
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.trading_date: Optional[str] = None

        # Position tracking (ticker -> position value)
        self.open_positions: Dict[str, float] = {}

        logger.info(
            f"DeepStackIntegration initialized: "
            f"balance=${account_balance:.2f}, "
            f"max_position=${config.max_position_size:.2f}, "
            f"daily_loss_limit=${config.daily_loss_limit:.2f}"
        )

    def check_trade_allowed(
        self,
        ticker: str,
        position_size: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Check if a trade is allowed by risk management.

        Performs checks:
        1. Daily loss limit
        2. Emotional firewall patterns
        3. Portfolio capacity

        Args:
            ticker: Market ticker
            position_size: Proposed position size in dollars

        Returns:
            Dict with:
                - allowed: bool
                - reasons: List of blocking reasons
                - cooldown_expires: datetime if in cooldown
        """
        self._check_daily_reset()

        reasons = []

        # Check 1: Daily loss limit
        if abs(self.daily_pnl) >= self.config.daily_loss_limit and self.daily_pnl < 0:
            reasons.append(
                f"Daily loss limit hit: ${abs(self.daily_pnl):.2f} / ${self.config.daily_loss_limit:.2f}"
            )
            logger.warning(f"Trade blocked: Daily loss limit reached")

        # Check 2: Emotional firewall
        firewall_result = self.firewall.should_block_trade(
            symbol=ticker,
            position_size=position_size,
        )

        if firewall_result["blocked"]:
            reasons.extend(firewall_result["reasons"])

        # Check 3: Portfolio capacity (if position size provided)
        if position_size:
            portfolio_info = self.kelly_sizer.get_position_info()
            remaining = portfolio_info["remaining_capacity"] * self.account_balance

            if position_size > remaining:
                reasons.append(
                    f"Insufficient portfolio capacity: need ${position_size:.2f}, "
                    f"available ${remaining:.2f}"
                )

        allowed = len(reasons) == 0

        if not allowed:
            logger.info(f"Trade check for {ticker}: BLOCKED - {reasons}")
        else:
            logger.debug(f"Trade check for {ticker}: ALLOWED")

        return {
            "allowed": allowed,
            "reasons": reasons,
            "cooldown_expires": firewall_result.get("cooldown_expires"),
            "patterns_detected": firewall_result.get("patterns_detected", []),
        }

    def calculate_position_size(
        self,
        win_rate: float,
        avg_win_cents: float,
        avg_loss_cents: float,
        ticker: Optional[str] = None,
        kelly_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate optimal position size using Kelly Criterion.

        Converts prediction market cents to dollar values for Kelly calculation.

        Args:
            win_rate: Historical win rate (0-1)
            avg_win_cents: Average win in cents
            avg_loss_cents: Average loss in cents (positive)
            ticker: Optional ticker for existing position check
            kelly_override: Per-strategy Kelly fraction; takes precedence
                over self.config.kelly_fraction when provided.

        Returns:
            Dict with:
                - position_size: Recommended $ to invest
                - contracts: Number of contracts (at $1 each)
                - kelly_pct: Raw Kelly percentage
                - rationale: Explanation of sizing
                - warnings: Any warnings
        """
        # Convert cents to effective dollars for Kelly calculation
        # In prediction markets, your position size determines your payout
        avg_win_dollars = avg_win_cents / 100  # Win per dollar invested
        avg_loss_dollars = avg_loss_cents / 100  # Loss per dollar invested

        kelly_fraction = kelly_override if kelly_override is not None else self.config.kelly_fraction

        # Calculate using Kelly
        result = self.kelly_sizer.calculate_position_size(
            win_rate=win_rate,
            avg_win=avg_win_dollars,
            avg_loss=avg_loss_dollars,
            kelly_fraction=kelly_fraction,
            symbol=ticker,
        )

        # Apply max position cap from config
        position_size = min(result["position_size"], self.config.max_position_size)

        # Calculate number of contracts (each contract = $1 at risk)
        contracts = int(position_size)

        return {
            "position_size": position_size,
            "contracts": contracts,
            "kelly_pct": result["kelly_pct"],
            "adjusted_pct": result["adjusted_pct"],
            "win_loss_ratio": result["win_loss_ratio"],
            "rationale": result["rationale"],
            "warnings": result["warnings"],
            "portfolio_heat": result["portfolio_heat"],
        }

    def record_trade_result(
        self,
        ticker: str,
        profit_loss_cents: int,
        position_size_dollars: float,
    ) -> None:
        """
        Record a trade result for risk tracking.

        Updates both the emotional firewall and daily P&L tracking.

        Args:
            ticker: Market ticker
            profit_loss_cents: P&L in cents (negative for loss)
            position_size_dollars: Position size in dollars
        """
        self._check_daily_reset()

        profit_loss_dollars = profit_loss_cents / 100

        # Update daily tracking
        self.daily_pnl += profit_loss_dollars
        self.daily_trades += 1

        # Record in emotional firewall
        self.firewall.record_trade(
            symbol=ticker,
            profit_loss=profit_loss_dollars,
            position_size=position_size_dollars,
        )

        # Update open positions
        if ticker in self.open_positions:
            del self.open_positions[ticker]

        # Update Kelly sizer positions
        self.kelly_sizer.update_positions(self.open_positions)

        logger.info(
            f"Trade recorded: {ticker} P/L=${profit_loss_dollars:.2f}, "
            f"Daily P/L=${self.daily_pnl:.2f}, Trades today={self.daily_trades}"
        )

        # Check if we've hit daily loss limit
        if self.daily_pnl <= -self.config.daily_loss_limit:
            logger.warning(
                f"Daily loss limit reached: ${abs(self.daily_pnl):.2f} lost"
            )

    def record_position_open(
        self,
        ticker: str,
        position_size_dollars: float,
    ) -> None:
        """
        Record an opened position.

        Args:
            ticker: Market ticker
            position_size_dollars: Position size in dollars
        """
        self.open_positions[ticker] = position_size_dollars
        self.kelly_sizer.update_positions(self.open_positions)

        logger.debug(f"Position opened: {ticker} ${position_size_dollars:.2f}")

    def update_balance(self, new_balance: float) -> None:
        """
        Update account balance after deposits/withdrawals or settlement.

        Args:
            new_balance: New account balance in dollars
        """
        old_balance = self.account_balance
        self.account_balance = new_balance

        # Update Kelly sizer (use minimum position size if balance is zero)
        effective_balance = max(new_balance, self.config.min_position_size)
        self.kelly_sizer.update_account_balance(effective_balance)

        if old_balance > 0:
            pct_change = (new_balance - old_balance) / old_balance * 100
            logger.info(f"Balance updated: ${old_balance:.2f} -> ${new_balance:.2f} ({pct_change:+.2f}%)")
        else:
            logger.info(f"Balance initialized: ${new_balance:.2f}")

    def get_daily_stats(self) -> Dict[str, Any]:
        """
        Get current daily trading statistics.

        Returns:
            Dict with daily P&L, trade count, risk metrics
        """
        self._check_daily_reset()

        firewall_stats = self.firewall.get_statistics()
        portfolio_info = self.kelly_sizer.get_position_info()

        return {
            "date": self.trading_date,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl / self.account_balance * 100,
            "daily_trades": self.daily_trades,
            "daily_loss_limit": self.config.daily_loss_limit,
            "loss_limit_remaining": self.config.daily_loss_limit + self.daily_pnl,
            "can_trade": abs(self.daily_pnl) < self.config.daily_loss_limit or self.daily_pnl > 0,
            "portfolio_heat": portfolio_info["current_heat"],
            "open_positions": len(self.open_positions),
            "current_streak": firewall_stats["current_streak"],
            "active_cooldown": firewall_stats["active_cooldown"],
            "cooldown_reason": firewall_stats.get("cooldown_reason"),
        }

    def reset_daily_stats(self) -> None:
        """
        Reset daily statistics (called at start of new trading day).
        """
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.trading_date = today

        logger.info(f"Daily stats reset for {today}")

    def _check_daily_reset(self) -> None:
        """Check if we need to reset daily stats for new day."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.trading_date != today:
            self.reset_daily_stats()

    def override_cooldown(self, confirmation: str) -> bool:
        """
        Override emotional firewall cooldown.

        Args:
            confirmation: Must be "OVERRIDE_COOLDOWN"

        Returns:
            True if override successful
        """
        return self.firewall.override_cooldown(confirmation)

    def calculate_expected_value(
        self,
        price_cents: int,
        side: str,
    ) -> Dict[str, float]:
        """
        Calculate expected value for a trade at given price.

        For binary markets:
        - Buy YES at X cents: risk X, win (100-X)
        - Buy NO at X cents: risk X, win (100-X)

        Args:
            price_cents: Entry price in cents (1-99)
            side: "yes" or "no"

        Returns:
            Dict with break_even probability and implied probabilities
        """
        if side == "yes":
            risk = price_cents
            reward = 100 - price_cents
        else:
            risk = price_cents
            reward = 100 - price_cents

        break_even = risk / 100  # Probability needed to break even
        reward_to_risk = reward / risk if risk > 0 else 0

        return {
            "risk_cents": risk,
            "reward_cents": reward,
            "break_even_probability": break_even,
            "reward_to_risk_ratio": reward_to_risk,
            "implied_probability": price_cents / 100,
        }
