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
import random
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError
from .config import KalshiConfig
from .exceptions import (
    KalshiAuthError,
    KalshiOrderError,
    KalshiRateLimitError,
    KalshiTradingError,
    MarketNotFoundError,
)

logger = logging.getLogger(__name__)


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
    ) -> Dict[str, Any]:
        """
        Make authenticated API request with retry logic and circuit breaker.

        Args:
            method: HTTP method
            path: Request path
            json: JSON body for POST/PUT
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            KalshiRateLimitError: If rate limited after retries
            KalshiTradingError: For other API errors
            CircuitOpenError: If circuit breaker is open
        """
        if not self._client:
            raise KalshiTradingError("Client not connected")

        for attempt in range(self.MAX_RETRIES):
            try:
                # Circuit breaker wraps the whole request so failures are counted.
                async with self._circuit_breaker:
                    await self._rate_limit()

                    headers = self._get_auth_headers(method, path)
                    response = await self._client.request(
                        method,
                        path,
                        headers=headers,
                        json=json,
                        params=params,
                    )

                    # Handle rate limiting
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        if attempt < self.MAX_RETRIES - 1:
                            logger.warning(f"Rate limited, waiting {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        raise KalshiRateLimitError(retry_after_seconds=retry_after)

                    # Handle other errors
                    if response.status_code >= 400:
                        error_data = response.json() if response.content else {}
                        raise KalshiTradingError(
                            f"API error {response.status_code}: {error_data.get('message', 'Unknown error')}",
                            details=error_data,
                        )

                    return response.json()

            except CircuitOpenError:
                raise KalshiTradingError(
                    "API circuit breaker is open - service may be degraded"
                )

            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    delay *= random.uniform(0.8, 1.2)
                    logger.warning(f"Request timeout, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise KalshiTradingError("Request timeout after retries")

            except httpx.RequestError as e:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    delay *= random.uniform(0.8, 1.2)
                    logger.warning(f"Request error: {e}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise KalshiTradingError(f"Request failed: {e}")

    # -------------------------------------------------------------------------
    # Account Methods
    # -------------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.

        Returns:
            Dict with 'balance', 'available', 'portfolio_value'
        """
        response = await self._request("GET", "/portfolio/balance")
        return {
            "balance": response.get("balance", 0) / 100,  # Convert cents to dollars
            "available": response.get("balance", 0) / 100,  # Kalshi v2 API uses "balance" for available cash
            "portfolio_value": response.get("portfolio_value", 0) / 100,
        }

    async def get_positions(self) -> List[Dict]:
        """
        Get all open positions.

        Returns:
            List of position dictionaries
        """
        response = await self._request("GET", "/portfolio/positions")
        positions = response.get("market_positions", [])

        return [
            {
                "ticker": pos.get("ticker"),
                "market_ticker": pos.get("market_ticker"),
                "position": pos.get("position", 0),  # Positive=yes, Negative=no
                "resting_orders_count": pos.get("resting_orders_count", 0),
                "total_traded": pos.get("total_traded", 0),
                "realized_pnl": pos.get("realized_pnl", 0) / 100,
            }
            for pos in positions
        ]

    # -------------------------------------------------------------------------
    # Market Methods
    # -------------------------------------------------------------------------

    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Get markets, optionally filtered by series.

        Args:
            series_ticker: Filter by series (e.g., "INXD")
            status: Filter by status ("open", "closed", "settled")
            limit: Maximum results to return

        Returns:
            List of market dictionaries
        """
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker

        response = await self._request("GET", "/markets", params=params)
        markets = response.get("markets", [])

        return [
            {
                "ticker": m.get("ticker"),
                "title": m.get("title"),
                "yes_bid": m.get("yes_bid", 0),  # In cents
                "yes_ask": m.get("yes_ask", 0),
                "no_bid": m.get("no_bid", 0),
                "no_ask": m.get("no_ask", 0),
                "last_price": m.get("last_price", 0),
                "volume": m.get("volume", 0),
                "volume_24h": m.get("volume_24h", 0),
                "open_interest": m.get("open_interest", 0),
                "close_time": m.get("close_time"),
                "expiration_time": m.get("expiration_time"),
                "status": m.get("status"),
            }
            for m in markets
        ]

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
            return {
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "yes_bid": market.get("yes_bid", 0),
                "yes_ask": market.get("yes_ask", 0),
                "no_bid": market.get("no_bid", 0),
                "no_ask": market.get("no_ask", 0),
                "last_price": market.get("last_price", 0),
                "volume": market.get("volume", 0),
                "status": market.get("status"),
            }
        except KalshiTradingError as e:
            if "not found" in str(e).lower() or e.details.get("code") == "not_found":
                raise MarketNotFoundError(ticker)
            raise

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

        if client_order_id:
            payload["client_order_id"] = client_order_id

        try:
            response = await self._request("POST", "/portfolio/orders", json=payload)
            order = response.get("order", {})

            logger.info(
                f"Order created: {ticker} {action} {count} {side} @ {price_cents}c | "
                f"ID: {order.get('order_id')}"
            )

            return {
                "order_id": order.get("order_id"),
                "ticker": order.get("ticker"),
                "side": order.get("side"),
                "action": order.get("action"),
                "count": order.get("count"),
                "price": order.get("yes_price") or order.get("no_price"),
                "status": order.get("status"),
                "created_time": order.get("created_time"),
            }

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

    async def get_order(self, order_id: str) -> Dict:
        """
        Get order details.

        Args:
            order_id: Order ID

        Returns:
            Order details dictionary
        """
        response = await self._request("GET", f"/portfolio/orders/{order_id}")
        order = response.get("order", {})

        return {
            "order_id": order.get("order_id"),
            "ticker": order.get("ticker"),
            "side": order.get("side"),
            "action": order.get("action"),
            "count": order.get("count"),
            "remaining_count": order.get("remaining_count"),
            "price": order.get("yes_price") or order.get("no_price"),
            "status": order.get("status"),
            "created_time": order.get("created_time"),
            "expiration_time": order.get("expiration_time"),
        }

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

        return [
            {
                "order_id": o.get("order_id"),
                "ticker": o.get("ticker"),
                "side": o.get("side"),
                "action": o.get("action"),
                "count": o.get("count"),
                "remaining_count": o.get("remaining_count"),
                "price": o.get("yes_price") or o.get("no_price"),
                "status": o.get("status"),
            }
            for o in orders
        ]

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
