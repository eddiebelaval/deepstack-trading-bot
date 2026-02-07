"""
Kalshi Trading Bot Exceptions

Custom exception hierarchy for the Kalshi trading bot. Provides specific
error types for authentication, rate limiting, order execution, and
risk management failures.
"""

from typing import Optional


class KalshiTradingError(Exception):
    """Base exception for all Kalshi trading bot errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class KalshiAuthError(KalshiTradingError):
    """Authentication failed with Kalshi API."""

    def __init__(
        self,
        message: str = "Kalshi authentication failed",
        key_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message, details)
        self.key_id = key_id


class KalshiRateLimitError(KalshiTradingError):
    """Rate limit exceeded on Kalshi API."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after_seconds: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message, details)
        self.retry_after_seconds = retry_after_seconds or 60


class KalshiOrderError(KalshiTradingError):
    """Order placement or management failed."""

    def __init__(
        self,
        message: str,
        order_id: Optional[str] = None,
        ticker: Optional[str] = None,
        side: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message, details)
        self.order_id = order_id
        self.ticker = ticker
        self.side = side


class RiskLimitExceeded(KalshiTradingError):
    """Trade rejected due to risk limits."""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current_value: float,
        limit_value: float,
        details: Optional[dict] = None,
    ):
        super().__init__(message, details)
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value


class DailyLossLimitHit(RiskLimitExceeded):
    """Daily loss limit has been reached."""

    def __init__(
        self,
        current_loss: float,
        limit: float,
        details: Optional[dict] = None,
    ):
        super().__init__(
            message=f"Daily loss limit reached: ${current_loss:.2f} / ${limit:.2f}",
            limit_type="daily_loss",
            current_value=current_loss,
            limit_value=limit,
            details=details,
        )


class MarketNotFoundError(KalshiTradingError):
    """Requested market ticker not found."""

    def __init__(self, ticker: str, details: Optional[dict] = None):
        super().__init__(f"Market not found: {ticker}", details)
        self.ticker = ticker


class InsufficientBalanceError(KalshiTradingError):
    """Insufficient account balance for trade."""

    def __init__(
        self,
        required: float,
        available: float,
        details: Optional[dict] = None,
    ):
        super().__init__(
            f"Insufficient balance: need ${required:.2f}, have ${available:.2f}",
            details,
        )
        self.required = required
        self.available = available
