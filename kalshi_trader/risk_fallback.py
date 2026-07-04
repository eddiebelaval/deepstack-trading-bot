"""
Internal fallbacks for DeepStack's risk components.

Used when the external DeepStack repo (DEEPSTACK_PATH) is not available.
These mirror the API surface that deepstack_integration.py consumes so the
bot can boot and trade safely without the sibling checkout. The fallback
Kelly sizer is intentionally conservative (negative edge sizes to zero);
the fallback firewall never blocks — the bot's own circuit breakers,
EV gate, and daily-loss check in DeepStackIntegration remain in force.

Root cause this file exists for: commit 5adf40c blanked the DEEPSTACK_PATH
default, making `from core.risk...` raise ImportError at startup and
crash-looping launchd for weeks. A missing optional integration must never
be able to take the whole bot down again.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class FallbackKellyPositionSizer:
    """Minimal Kelly sizer matching DeepStack's KellyPositionSizer API."""

    def __init__(
        self,
        account_balance: float,
        max_position_pct: float = 0.25,
        max_total_exposure: float = 0.5,
        min_position_size: float = 1.0,
        max_position_size: float = 50.0,
    ):
        self.account_balance = account_balance
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.min_position_size = min_position_size
        self.max_position_size = max_position_size
        self._positions: Dict[str, float] = {}

    def _current_exposure(self) -> float:
        return sum(self._positions.values())

    def get_position_info(self) -> Dict[str, Any]:
        exposure = self._current_exposure()
        balance = max(self.account_balance, 1e-9)
        heat = exposure / balance
        remaining = max(0.0, self.max_total_exposure - heat)
        return {
            "current_heat": heat,
            "remaining_capacity": remaining,
            "open_positions": len(self._positions),
            "total_exposure": exposure,
        }

    def calculate_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        kelly_fraction: float = 0.02,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        warnings = []
        if avg_loss <= 0:
            win_loss_ratio = 0.0
        else:
            win_loss_ratio = avg_win / avg_loss

        if win_loss_ratio <= 0:
            kelly_pct = 0.0
        else:
            kelly_pct = win_rate - (1 - win_rate) / win_loss_ratio

        if kelly_pct <= 0:
            warnings.append("Negative edge: Kelly recommends no bet")
            adjusted_pct = 0.0
        else:
            adjusted_pct = kelly_pct * kelly_fraction

        adjusted_pct = min(adjusted_pct, self.max_position_pct)

        position_size = adjusted_pct * self.account_balance

        # Respect remaining portfolio capacity
        remaining_dollars = max(
            0.0,
            self.max_total_exposure * self.account_balance - self._current_exposure(),
        )
        if position_size > remaining_dollars:
            warnings.append("Capped by max total exposure")
            position_size = remaining_dollars

        position_size = min(position_size, self.max_position_size)
        if 0 < position_size < self.min_position_size:
            position_size = self.min_position_size

        return {
            "position_size": position_size,
            "kelly_pct": kelly_pct,
            "adjusted_pct": adjusted_pct,
            "win_loss_ratio": win_loss_ratio,
            "rationale": (
                f"fallback Kelly: raw={kelly_pct:.4f}, "
                f"fraction={kelly_fraction:.4f}, size=${position_size:.2f}"
            ),
            "warnings": warnings,
            "portfolio_heat": self.get_position_info()["current_heat"],
        }

    def update_positions(self, positions: Dict[str, float]) -> None:
        self._positions = dict(positions)

    def update_account_balance(self, balance: float) -> None:
        self.account_balance = balance


class FallbackEmotionalFirewall:
    """No-op firewall matching DeepStack's EmotionalFirewall API.

    Never blocks trades. The bot's own circuit breakers, EV gate, and the
    daily-loss check in DeepStackIntegration remain the active safety rails.
    """

    def __init__(self, **kwargs: Any):
        self._streak = 0
        self._trades = 0

    def should_block_trade(
        self, symbol: str, position_size: Optional[float] = None
    ) -> Dict[str, Any]:
        return {
            "blocked": False,
            "reasons": [],
            "cooldown_expires": None,
            "patterns_detected": [],
        }

    def record_trade(
        self, symbol: str, profit_loss: float, position_size: float
    ) -> None:
        self._trades += 1
        if profit_loss > 0:
            self._streak = max(1, self._streak + 1)
        elif profit_loss < 0:
            self._streak = min(-1, self._streak - 1)

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "current_streak": self._streak,
            "active_cooldown": False,
            "cooldown_reason": None,
            "total_trades": self._trades,
        }

    def override_cooldown(self, confirmation: str) -> bool:
        return True
