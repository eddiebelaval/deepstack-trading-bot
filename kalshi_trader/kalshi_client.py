"""
Authenticated Kalshi API Client

RSA-PSS authenticated wrapper for Kalshi's trading API.
Handles signing, rate limiting, and retry logic.

Authentication:
    Kalshi uses RSA-PSS signatures for API authentication. Each request
    is signed with a private key, and the signature is included in headers.
"""

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .api_circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError
from .config import KalshiConfig
from .exceptions import (
    KalshiAuthError,
    KalshiOrderError,
    KalshiRateLimitError,
    KalshiTradingError,
    MarketNotFoundError,
)

logger = logging.getLogger(__name__)


def _dollars_to_cents(value: Any) -> int:
    """Convert a dollar-denominated value (str or float) to integer cents.

    Kalshi API v2 migrated from integer-cent fields (yes_ask=45)
    to dollar-string fields (yes_ask_dollars="0.4500"). This helper
    supports both formats so the rest of the codebase can keep using cents.
    """
    if value is None:
        return 0
    try:
        return int(round(float(value) * 100))
    except (ValueError, TypeError):
        return 0


def _fp_to_int(value: Any) -> int:
    """Convert a float-point string field (e.g. '5.00') to integer."""
    if value is None:
        return 0
    try:
        return int(round(float(value)))
    except (ValueError, TypeError):
        return 0


def _normalize_order(o: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Kalshi order dict to internal format.

    Handles v2 field migration: count→initial_count_fp, yes_price→yes_price_dollars, etc.
    """
    count = _fp_to_int(o.get("initial_count_fp")) or o.get("initial_count") or o.get("count") or 0
    remaining = _fp_to_int(o.get("remaining_count_fp")) or o.get("remaining_count") or 0
    fill_count = _fp_to_int(o.get("fill_count_fp")) or o.get("fill_count") or 0
    yes_price = _dollars_to_cents(o.get("yes_price_dollars")) or o.get("yes_price")
    no_price = _dollars_to_cents(o.get("no_price_dollars")) or o.get("no_price")
    taker_fees = _dollars_to_cents(o.get("taker_fees_dollars")) or o.get("taker_fees") or 0
    maker_fees = _dollars_to_cents(o.get("maker_fees_dollars")) or o.get("maker_fees") or 0
    taker_fill_cost = _dollars_to_cents(o.get("taker_fill_cost_dollars")) or o.get("taker_fill_cost") or 0
    maker_fill_cost = _dollars_to_cents(o.get("maker_fill_cost_dollars")) or o.get("maker_fill_cost") or 0

    return {
        "order_id": o.get("order_id"),
        "ticker": o.get("ticker"),
        "side": o.get("side"),
        "action": o.get("action"),
        "type": o.get("type", "limit"),
        "status": o.get("status"),
        "count": count,
        "remaining_count": remaining,
        "fill_count": fill_count,
        "yes_price": yes_price,
        "no_price": no_price,
        "price": no_price if o.get("side") == "no" else yes_price,
        "initial_count": count,
        "taker_fees": taker_fees,
        "maker_fees": maker_fees,
        "taker_fill_cost": taker_fill_cost,
        "maker_fill_cost": maker_fill_cost,
        "created_time": o.get("created_time"),
        "last_update_time": o.get("last_update_time"),
        "expiration_time": o.get("expiration_time"),
    }


def _normalize_position(pos: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Kalshi position dict to internal format.

    Handles v2 field migration: position→position_fp, market_exposure→market_exposure_dollars, etc.
    """
    position = _fp_to_int(pos.get("position_fp")) or pos.get("position") or 0
    total_traded = _dollars_to_cents(pos.get("total_traded_dollars")) or pos.get("total_traded") or 0
    market_exposure = _dollars_to_cents(pos.get("market_exposure_dollars")) or pos.get("market_exposure") or 0
    realized_pnl = _dollars_to_cents(pos.get("realized_pnl_dollars")) or pos.get("realized_pnl") or 0
    fees_paid = _dollars_to_cents(pos.get("fees_paid_dollars")) or pos.get("fees_paid") or 0

    return {
        "ticker": pos.get("ticker"),
        "market_ticker": pos.get("market_ticker") or pos.get("ticker"),
        "position": position,
        "resting_orders_count": pos.get("resting_orders_count", 0),
        "total_traded": total_traded,
        "market_exposure": market_exposure,
        "realized_pnl": realized_pnl,
        "fees_paid": fees_paid,
        "last_updated_ts": pos.get("last_updated_ts"),
    }


def _normalize_fill(f: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Kalshi fill dict to internal format.

    Handles v2 field migration: count→count_fp, yes_price→yes_price_dollars, etc.
    """
    count = _fp_to_int(f.get("count_fp")) or f.get("count") or 0
    yes_price = _dollars_to_cents(f.get("yes_price_dollars")) or f.get("yes_price")
    no_price = _dollars_to_cents(f.get("no_price_dollars")) or f.get("no_price")
    fee_str = f.get("fee_cost")
    fee_cost = _dollars_to_cents(fee_str) if isinstance(fee_str, str) else (fee_str or 0)

    return {
        "fill_id": f.get("fill_id") or f.get("trade_id"),
        "order_id": f.get("order_id"),
        "ticker": f.get("ticker") or f.get("market_ticker"),
        "side": f.get("side"),
        "action": f.get("action"),
        "count": count,
        "yes_price": yes_price,
        "no_price": no_price,
        "is_taker": f.get("is_taker", False),
        "fee_cost": fee_cost,
        "created_time": f.get("created_time"),
    }


def _normalize_settlement(s: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Kalshi settlement dict to internal format."""
    yes_count = _fp_to_int(s.get("yes_count_fp")) or s.get("yes_count") or 0
    no_count = _fp_to_int(s.get("no_count_fp")) or s.get("no_count") or 0
    yes_total_cost = _dollars_to_cents(s.get("yes_total_cost_dollars")) or s.get("yes_total_cost") or 0
    no_total_cost = _dollars_to_cents(s.get("no_total_cost_dollars")) or s.get("no_total_cost") or 0
    fee_str = s.get("fee_cost")
    fee_cost = _dollars_to_cents(fee_str) if isinstance(fee_str, str) else (fee_str or 0)

    return {
        "ticker": s.get("ticker"),
        "event_ticker": s.get("event_ticker"),
        "market_result": s.get("market_result"),
        "yes_count": yes_count,
        "no_count": no_count,
        "yes_total_cost": yes_total_cost,
        "no_total_cost": no_total_cost,
        "revenue": s.get("revenue", 0),
        "settled_time": s.get("settled_time"),
        "fee_cost": fee_cost,
        "value": s.get("value"),
    }


def _normalize_market(m: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Kalshi market dict to the internal cents-based format.

    Handles both legacy (integer cents) and new (dollar-denominated) API responses.
    """
    # Prefer new dollar fields, fall back to legacy cent fields
    yes_bid = _dollars_to_cents(m.get("yes_bid_dollars")) or m.get("yes_bid", 0) or 0
    yes_ask = _dollars_to_cents(m.get("yes_ask_dollars")) or m.get("yes_ask", 0) or 0
    no_bid = _dollars_to_cents(m.get("no_bid_dollars")) or m.get("no_bid", 0) or 0
    no_ask = _dollars_to_cents(m.get("no_ask_dollars")) or m.get("no_ask", 0) or 0
    last_price = _dollars_to_cents(m.get("last_price_dollars")) or m.get("last_price", 0) or 0

    # Volume fields: _fp suffix is float contracts, no dollar conversion needed
    volume = int(float(m.get("volume_fp", 0) or 0)) or m.get("volume", 0) or 0
    volume_24h = int(float(m.get("volume_24h_fp", 0) or 0)) or m.get("volume_24h", 0) or 0
    open_interest = int(float(m.get("open_interest_fp", 0) or 0)) or m.get("open_interest", 0) or 0

    return {
        "ticker": m.get("ticker"),
        "title": m.get("title"),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "last_price": last_price,
        "volume": volume,
        "volume_24h": volume_24h,
        "open_interest": open_interest,
        "close_time": m.get("close_time"),
        "expiration_time": m.get("expiration_time") or m.get("expected_expiration_time"),
        "status": m.get("status"),
        "result": m.get("result"),
        "previous_price": _dollars_to_cents(m.get("previous_price_dollars")) or m.get("previous_price"),
        "previous_yes_bid": _dollars_to_cents(m.get("previous_yes_bid_dollars")) or m.get("previous_yes_bid"),
        "previous_yes_ask": _dollars_to_cents(m.get("previous_yes_ask_dollars")) or m.get("previous_yes_ask"),
    }


class AuthenticatedKalshiClient:
    """
    Authenticated HTTP client for Kalshi Trading API.

    Uses RSA-PSS signatures for authentication and handles rate limiting
    with exponential backoff retries.

    Example:
        >>> config = KalshiConfig()
        >>> client = AuthenticatedKalshiClient(config)
        >>> await client.connect()
        >>> balance = await client.get_balance()
        >>> print(f"Available: ${balance['available']:.2f}")
    """

    # Rate limit: 60 requests per minute
    RATE_LIMIT_REQUESTS = 60
    RATE_LIMIT_WINDOW_SECONDS = 60
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0

    def __init__(self, config: KalshiConfig):
        """
        Initialize Kalshi client.

        Args:
            config: KalshiConfig with API credentials
        """
        self.config = config
        self.base_url = config.effective_base_url
        self._private_key = None
        self._client: Optional[httpx.AsyncClient] = None
        # Use deque with maxlen for bounded memory (prevents memory leak)
        self._request_times: Deque[float] = deque(maxlen=self.RATE_LIMIT_REQUESTS)

        # Circuit breaker for resilience against API failures
        self._circuit_breaker = CircuitBreaker(
            name="kalshi_api",
            config=CircuitBreakerConfig(
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=30.0,
            ),
        )

    async def connect(self) -> None:
        """
        Initialize connection and load private key.

        Raises:
            KalshiAuthError: If credentials are invalid or key cannot be loaded
        """
        # Validate credentials
        valid, error = self.config.validate_credentials()
        if not valid:
            raise KalshiAuthError(error, key_id=self.config.api_key_id)

        # Load private key
        key_path = self.config.private_key_path_resolved
        try:
            with open(key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
            logger.info("Private key loaded successfully")
        except Exception as e:
            raise KalshiAuthError(
                f"Failed to load private key: {e}",
                key_id=self.config.api_key_id,
            )

        # Create HTTP client with connection pool limits
        # Prevents resource exhaustion under heavy load
        limits = httpx.Limits(
            max_keepalive_connections=10,
            max_connections=20,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=10.0,
            pool=5.0,  # Time waiting for connection from pool
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=limits,
            headers={"Content-Type": "application/json"},
        )

        # Verify authentication with balance check
        try:
            await self.get_balance()
            logger.info("Kalshi API connection verified")
        except Exception as e:
            await self.disconnect()
            raise KalshiAuthError(f"Failed to verify API connection: {e}")

    async def disconnect(self) -> None:
        """Close HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Kalshi API client disconnected")

    def _sign_request(
        self,
        method: str,
        path: str,
        timestamp_ms: int,
    ) -> str:
        """
        Generate RSA-PSS signature for request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (without base URL)
            timestamp_ms: Unix timestamp in milliseconds

        Returns:
            Base64-encoded signature
        """
        if not self._private_key:
            raise KalshiAuthError("Private key not loaded")

        # Create message to sign: timestamp + method + path
        message = f"{timestamp_ms}{method}{path}".encode("utf-8")

        # Sign with RSA-PSS (salt_length = digest length per Kalshi docs)
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        return base64.b64encode(signature).decode("utf-8")

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate authentication headers for request.

        Args:
            method: HTTP method
            path: Request path (relative to base_url)

        Returns:
            Dict of headers to include in request
        """
        timestamp_ms = int(time.time() * 1000)

        # The signature must include the full path including /trade-api/v2
        # Strip query parameters for signing
        path_for_signing = path.split("?")[0]
        full_path = f"/trade-api/v2{path_for_signing}"

        signature = self._sign_request(method, full_path, timestamp_ms)

        return {
            "KALSHI-ACCESS-KEY": self.config.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        }

    async def _rate_limit(self) -> None:
        """Wait if necessary to respect rate limits.

        Uses a bounded deque to prevent memory leaks. Old entries are
        automatically removed when the deque reaches max capacity.
        """
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW_SECONDS

        # Remove entries older than the rate limit window
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

        # Wait if at limit
        if len(self._request_times) >= self.RATE_LIMIT_REQUESTS:
            oldest = self._request_times[0]
            wait_time = self.RATE_LIMIT_WINDOW_SECONDS - (now - oldest)
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)

        self._request_times.append(time.time())

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None,
        bypass_circuit_breaker: bool = False,
    ) -> Dict[str, Any]:
        """
        Make authenticated API request with retry logic and circuit breaker.

        Args:
            method: HTTP method
            path: Request path
            json: JSON body for POST/PUT
            params: Query parameters
            bypass_circuit_breaker: If True, skip circuit breaker check.
                Used for position-closing orders that MUST attempt delivery
                regardless of API health state.

        Returns:
            Parsed JSON response

        Raises:
            KalshiRateLimitError: If rate limited after retries
            KalshiTradingError: For other API errors
            CircuitOpenError: If circuit breaker is open
        """
        if not self._client:
            raise KalshiTradingError("Client not connected")

        # Round 8 P0 (Vasquez): Circuit breaker now observes actual HTTP outcomes.
        # Round 9 P0 (Tanaka): Closing orders bypass the circuit breaker.
        # A position-closing sell order is more important than protecting against
        # API degradation — the risk of holding a position through a flash crash
        # exceeds the risk of a failed API call. The breaker still records the
        # outcome (success/failure) to maintain state accuracy.
        #
        # Gate WITHOUT recording: the old `async with breaker: pass` probe
        # counted its own no-op as a success, closing the breaker after two
        # empty probes regardless of actual API health.
        if not bypass_circuit_breaker and not self._circuit_breaker.is_closed:
            try:
                await self._circuit_breaker.check_can_execute()
            except CircuitOpenError:
                raise KalshiTradingError(
                    "API circuit breaker is open - service may be degraded"
                )
        elif bypass_circuit_breaker and not self._circuit_breaker.is_closed:
            logger.warning(
                "Circuit breaker is OPEN but bypassing for critical order "
                "(position close). Attempting delivery anyway."
            )

        await self._rate_limit()

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                headers = self._get_auth_headers(method, path)

                response = await self._client.request(
                    method,
                    path,
                    headers=headers,
                    json=json,
                    params=params,
                )

                # Handle rate limiting.
                # Retry-After may be an HTTP-date rather than seconds —
                # int() raised uncaught ValueError; parse defensively and
                # cap the sleep so a hostile/buggy header can't stall us.
                if response.status_code == 429:
                    try:
                        retry_after = int(response.headers.get("Retry-After", 60))
                    except (ValueError, TypeError):
                        retry_after = 60
                    retry_after = max(1, min(retry_after, 120))
                    if attempt < self.MAX_RETRIES - 1:
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    last_error = KalshiRateLimitError(retry_after_seconds=retry_after)
                    break

                # 5xx: transient server errors — retry with backoff and
                # count toward the breaker (the docstring always promised
                # this; previously any 5xx failed the cycle immediately).
                if response.status_code >= 500:
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"Server error {response.status_code}, retrying in {delay}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    last_error = KalshiTradingError(
                        f"API error {response.status_code} after retries",
                    )
                    break

                # 4xx: client errors — OUR request was wrong (bad price,
                # insufficient balance). Raise immediately but never count
                # toward the breaker: five rejected orders must not cut off
                # market data and exit management for all strategies.
                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise KalshiTradingError(
                        f"API error {response.status_code}: {error_data.get('message', 'Unknown error')}",
                        details=error_data,
                    )

                # Success — record in circuit breaker and return
                await self._circuit_breaker.record_success()
                return response.json()

            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Request timeout, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                last_error = KalshiTradingError("Request timeout after retries")
                break

            except httpx.RequestError as e:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Request error: {e}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                last_error = KalshiTradingError(f"Request failed: {e}")
                break

        # All retries exhausted — record failure. Only 5xx/timeout/transport
        # errors reach here (4xx raises above without touching the breaker).
        # When bypass_circuit_breaker is True, still raise but don't record.
        if last_error is not None:
            if not bypass_circuit_breaker:
                await self._circuit_breaker.record_failure(last_error)
            raise last_error

    # -------------------------------------------------------------------------
    # Account Methods
    # -------------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.

        Returns:
            Dict with 'balance' (cash), 'available' (cash), 'portfolio_value' (max payout, NOT market value)
        """
        response = await self._request("GET", "/portfolio/balance")
        cash_cents = response.get("balance", 0)
        portfolio_cents = response.get("portfolio_value", 0)
        return {
            "balance": cash_cents / 100,  # Cash balance
            "available": cash_cents / 100,  # Cash available for trading
            "portfolio_value": portfolio_cents / 100,  # Max payout if all bets win (NOT mark-to-market)
        }

    async def check_exchange_status(self) -> Dict[str, Any]:
        """Check if the Kalshi exchange is currently open for trading.

        Returns:
            Dict with 'trading_active' (bool) and 'exchange_status' (str).
            Round 7 P0 (Vasquez): Fails CLOSED on API error. If we can't
            confirm the exchange is open, don't trade. Previous behavior
            (fail open) could place orders into a closed exchange.
        """
        try:
            response = await self._request("GET", "/exchange/status")
            trading_active = response.get("trading_active", True)
            exchange_status = response.get("exchange_status", "unknown")
            if not trading_active:
                logger.warning(
                    "Exchange not open for trading (status=%s)", exchange_status
                )
            return {
                "trading_active": trading_active,
                "exchange_status": exchange_status,
            }
        except Exception as e:
            logger.warning(
                "Exchange status check failed: %s — failing CLOSED (no trades until confirmed open)", e
            )
            return {"trading_active": False, "exchange_status": "error"}

    async def get_positions(self) -> List[Dict]:
        """
        Get all open positions with full Kalshi API fields.

        Returns:
            List of position dictionaries (all monetary values in cents)
        """
        response = await self._request("GET", "/portfolio/positions")
        positions = response.get("market_positions", [])
        return [_normalize_position(pos) for pos in positions]

    async def get_fills(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Get fill (execution) history from Kalshi.

        Args:
            ticker: Optional market ticker filter
            limit: Maximum results to return

        Returns:
            List of fill dictionaries
        """
        params: Dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker

        response = await self._request("GET", "/portfolio/fills", params=params)
        fills = response.get("fills", [])
        return [_normalize_fill(f) for f in fills]

    async def get_settlements(
        self,
        limit: int = 100,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        paginate: bool = False,
        max_pages: int = 25,
    ) -> List[Dict]:
        """
        Get settlement history — resolved market payouts.

        Args:
            limit: Maximum results per page (max 200)
            ticker: Optional market ticker filter
            min_ts: Optional Unix timestamp floor (only settlements after this time)
            paginate: If True, follow the cursor to fetch every page.
                Without this, weeks of downtime with >limit settlements
                silently dropped the oldest ones — journal trades stayed
                open forever and every downstream stat ran stale.
            max_pages: Safety cap on pages when paginating

        Returns:
            List of settlement dictionaries (monetary values in cents)
        """
        params: Dict[str, Any] = {"limit": min(limit, 200)}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts

        all_settlements: List[Dict] = []
        pages_fetched = 0
        while True:
            response = await self._request(
                "GET", "/portfolio/settlements", params=params
            )
            settlements = response.get("settlements", [])
            all_settlements.extend(_normalize_settlement(s) for s in settlements)
            pages_fetched += 1

            cursor = response.get("cursor")
            if not paginate or not cursor or not settlements or pages_fetched >= max_pages:
                break
            params["cursor"] = cursor

        if paginate and pages_fetched > 1:
            logger.debug(
                f"Paginated {pages_fetched} settlement pages, "
                f"{len(all_settlements)} total"
            )
        return all_settlements

    # -------------------------------------------------------------------------
    # Market Methods
    # -------------------------------------------------------------------------

    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
        paginate: bool = False,
        max_pages: int = 10,
    ) -> List[Dict]:
        """
        Get markets, optionally filtered by series.

        Args:
            series_ticker: Filter by series (e.g., "INXD")
            status: Filter by status ("open", "closed", "settled")
            limit: Maximum results per page
            paginate: If True, follow cursor to fetch multiple pages
            max_pages: Maximum pages to fetch when paginating

        Returns:
            List of market dictionaries
        """
        params = {"status": status, "limit": limit}
        if series_ticker and series_ticker != "*":
            params["series_ticker"] = series_ticker

        all_markets = []
        pages_fetched = 0

        while pages_fetched < (max_pages if paginate else 1):
            response = await self._request("GET", "/markets", params=params)
            markets = response.get("markets", [])

            # Debug: log when API returns zero markets so we can diagnose dead feeds
            if not markets and pages_fetched == 0:
                logger.warning(
                    "get_markets returned 0 results | series=%s status=%s | "
                    "response_keys=%s",
                    series_ticker or "(all)", status,
                    list(response.keys()) if response else "empty",
                )

            all_markets.extend([_normalize_market(m) for m in markets])

            pages_fetched += 1

            # Check for next page cursor
            cursor = response.get("cursor")
            if not paginate or not cursor or len(markets) < limit:
                break
            params["cursor"] = cursor

        if paginate and pages_fetched > 1:
            logger.debug(f"Paginated {pages_fetched} pages, {len(all_markets)} total markets")

        return all_markets

    async def get_market(self, ticker: str) -> Dict:
        """
        Get single market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Market dictionary

        Raises:
            MarketNotFoundError: If market doesn't exist
        """
        try:
            response = await self._request("GET", f"/markets/{ticker}")
            market = response.get("market", {})
            return _normalize_market(market)
        except KalshiTradingError as e:
            if "not found" in str(e).lower() or e.details.get("code") == "not_found":
                raise MarketNotFoundError(ticker)
            raise

    async def get_candlesticks(
        self,
        ticker: str,
        series_ticker: str,
        period_interval: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get OHLCV candlestick data for a market.

        Args:
            ticker: Market ticker (e.g., "KXBTC-26FEB0912-B79125")
            series_ticker: Series ticker (e.g., "KXBTC")
            period_interval: Candle period in minutes: 1, 60, or 1440
            start_ts: Unix timestamp start (defaults to 24h ago)
            end_ts: Unix timestamp end (defaults to now)

        Returns:
            List of candlestick dicts with OHLCV data
        """
        import time as _time

        if end_ts is None:
            end_ts = int(_time.time())
        if start_ts is None:
            start_ts = end_ts - 86400  # 24 hours

        params = {
            "period_interval": period_interval,
            "start_ts": start_ts,
            "end_ts": end_ts,
        }

        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        response = await self._request("GET", path, params=params)
        candles = response.get("candlesticks", [])

        return [
            {
                "end_period_ts": c.get("end_period_ts"),
                "open": c.get("price", {}).get("open"),
                "high": c.get("price", {}).get("high"),
                "low": c.get("price", {}).get("low"),
                "close": c.get("price", {}).get("close"),
                "volume": c.get("volume", 0),
                "open_interest": c.get("open_interest", 0),
            }
            for c in candles
        ]

    async def get_orderbook(self, ticker: str) -> Dict:
        """
        Get orderbook for a market.

        Args:
            ticker: Market ticker

        Returns:
            Dict with 'yes' and 'no' order books
        """
        response = await self._request("GET", f"/markets/{ticker}/orderbook")
        orderbook = response.get("orderbook", {})

        return {
            "yes": [
                {"price": level[0], "quantity": level[1]}
                for level in orderbook.get("yes", [])
            ],
            "no": [
                {"price": level[0], "quantity": level[1]}
                for level in orderbook.get("no", [])
            ],
        }

    # -------------------------------------------------------------------------
    # Order Methods
    # -------------------------------------------------------------------------

    async def create_limit_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        client_order_id: Optional[str] = None,
        bypass_circuit_breaker: bool = False,
    ) -> Dict:
        """
        Create a limit order.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Limit price in cents (1-99)
            client_order_id: Optional client-assigned order ID
            bypass_circuit_breaker: If True, attempt order even if circuit
                breaker is open. Used for position-closing sell orders.

        Returns:
            Order details including order_id

        Raises:
            KalshiOrderError: If order fails
        """
        payload = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": "limit",
            "yes_price": price_cents if side == "yes" else None,
            "no_price": price_cents if side == "no" else None,
        }

        # Always send a client_order_id: _request retries order POSTs on
        # timeout, and a timeout after Kalshi accepted the order would
        # otherwise double-fill. With a stable UUID per intent (same payload
        # on every retry), Kalshi dedupes server-side.
        if not client_order_id:
            client_order_id = str(uuid.uuid4())
        payload["client_order_id"] = client_order_id

        try:
            response = await self._request(
                "POST", "/portfolio/orders", json=payload,
                bypass_circuit_breaker=bypass_circuit_breaker,
            )
            order = response.get("order", {})

            logger.info(
                f"Order created: {ticker} {action} {count} {side} @ {price_cents}c | "
                f"ID: {order.get('order_id')}"
            )

            return _normalize_order(order)

        except KalshiTradingError as e:
            raise KalshiOrderError(
                str(e),
                ticker=ticker,
                side=side,
                details=e.details,
            )

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            await self._request("DELETE", f"/portfolio/orders/{order_id}")
            logger.info(f"Order cancelled: {order_id}")
            return True
        except KalshiTradingError as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def get_order(
        self, order_id: str, bypass_circuit_breaker: bool = False,
    ) -> Dict:
        """
        Get order details.

        Args:
            order_id: Order ID
            bypass_circuit_breaker: If True, don't trip circuit breaker on errors.
                Used during fill-polling where transient 404s are expected due to
                Kalshi's eventual consistency between write and query services.

        Returns:
            Order details dictionary
        """
        response = await self._request(
            "GET", f"/portfolio/orders/{order_id}",
            bypass_circuit_breaker=bypass_circuit_breaker,
        )
        order = response.get("order", {})
        return _normalize_order(order)

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get all orders, optionally filtered.

        Args:
            ticker: Filter by market ticker
            status: Filter by status ("resting", "canceled", "executed")

        Returns:
            List of order dictionaries
        """
        params = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status

        response = await self._request("GET", "/portfolio/orders", params=params)
        orders = response.get("orders", [])
        return [_normalize_order(o) for o in orders]

    async def cancel_all_orders(self, ticker: Optional[str] = None) -> int:
        """
        Cancel all resting orders, optionally for specific market.

        Args:
            ticker: Optional market ticker filter

        Returns:
            Number of orders cancelled
        """
        orders = await self.get_orders(ticker=ticker, status="resting")
        cancelled = 0

        for order in orders:
            if await self.cancel_order(order["order_id"]):
                cancelled += 1

        logger.info(f"Cancelled {cancelled} orders")
        return cancelled
