"""
CryExc Bridge - Lifecycle bridge between DeepStack's CryExc client and
the Kalshi trading bot.

Follows the same pattern as deepstack_integration.py:
- Adds DeepStack to sys.path
- Imports CryExcClient + CryptoSignalStore
- Provides connect/disconnect lifecycle
- Exposes signal stores to strategies via get_signal_store(symbol)

Symbol Mapping:
    Strategies use Kalshi crypto symbols (BTC, ETH, SOL).
    CryExc uses exchange symbols (BTCUSDT, ETHUSDT, SOLUSDT).
    This bridge handles the mapping.
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Add DeepStack to path (same pattern as deepstack_integration.py)
DEEPSTACK_PATH = os.getenv(
    "DEEPSTACK_PATH",
    "/Users/eddiebelaval/Development/id8/products/deepstack",
)
if DEEPSTACK_PATH not in sys.path:
    sys.path.insert(0, DEEPSTACK_PATH)

# Lazy imports to avoid triggering core.data.__init__.py which pulls
# heavy deps (pandas, etc.) that may not be in the Kalshi venv.
# These are resolved at import time of this module but use importlib
# to load specific files without the package __init__.
import importlib.util as _ilu

def _ensure_parent_packages(module_name: str):
    """Register stub parent packages in sys.modules for relative imports."""
    parts = module_name.rsplit(".", 1)
    if len(parts) < 2:
        return
    parent = parts[0]
    if parent not in sys.modules:
        import types
        # Walk up the chain: "core.data" needs "core" registered first
        _ensure_parent_packages(parent)
        pkg = types.ModuleType(parent)
        pkg.__path__ = []
        pkg.__package__ = parent
        sys.modules[parent] = pkg


def _load_deepstack_module(module_name: str, file_path: str):
    """Load a DeepStack module directly from file, bypassing __init__.py."""
    _ensure_parent_packages(module_name)
    spec = _ilu.spec_from_file_location(module_name, file_path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

_cryexc_mod = _load_deepstack_module(
    "core.data.cryexc_client",
    os.path.join(DEEPSTACK_PATH, "core", "data", "cryexc_client.py"),
)
_store_mod = _load_deepstack_module(
    "core.data.crypto_signal_store",
    os.path.join(DEEPSTACK_PATH, "core", "data", "crypto_signal_store.py"),
)

CryExcClient = _cryexc_mod.CryExcClient
CryptoSignalStore = _store_mod.CryptoSignalStore

logger = logging.getLogger(__name__)

# Kalshi symbol -> CryExc exchange symbol
SYMBOL_MAP: Dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

# Reverse map for lookups
REVERSE_SYMBOL_MAP: Dict[str, str] = {v: k for k, v in SYMBOL_MAP.items()}


class CryExcBridge:
    """
    Bridge between CryExc real-time data and the Kalshi trading bot.

    Manages the CryExcClient lifecycle and provides per-symbol signal stores
    that strategies consume.

    Example:
        >>> bridge = CryExcBridge(config)
        >>> await bridge.connect()
        >>> store = bridge.get_signal_store("BTC")
        >>> if store and not store.is_stale():
        ...     price = store.get_spot_price()
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize bridge from cryexc config block.

        Args:
            config: Dict from config.yaml 'cryexc' section:
                - url: WebSocket URL (default ws://localhost:8086/ws)
                - symbols: list of symbol configs
                - reconnect: reconnect settings
        """
        self._config = config
        self._url = config.get("url", "ws://localhost:8086/ws")

        # Reconnect settings
        reconnect = config.get("reconnect", {})
        self._reconnect_base = reconnect.get("base_seconds", 1.0)
        self._reconnect_max = reconnect.get("max_seconds", 30.0)

        # Build client
        self.client = CryExcClient(
            url=self._url,
            reconnect_base=self._reconnect_base,
            reconnect_max=self._reconnect_max,
        )

        # Per-symbol signal stores
        self._stores: Dict[str, CryptoSignalStore] = {}

        # Parse symbol configs
        self._symbol_configs = config.get("symbols", [])

        # Listen task handle
        self._listen_task: Optional[asyncio.Task] = None

        logger.info(
            f"CryExcBridge initialized: {self._url} | "
            f"{len(self._symbol_configs)} symbols configured"
        )

    async def connect(self) -> bool:
        """
        Connect to CryExc and subscribe to configured symbols.

        Returns True if connection succeeded.
        """
        # Create signal stores and wire callbacks
        for sym_config in self._symbol_configs:
            exchange_symbol = sym_config.get("symbol", "")
            if not exchange_symbol:
                continue

            store = CryptoSignalStore(exchange_symbol)

            # Wire store callbacks to client
            self.client.on_trade(store.on_trade)
            self.client.on_cvd(store.on_cvd)
            self.client.on_orderbook_stats(store.on_orderbook_stats)
            self.client.on_liquidation(store.on_liquidation)

            self._stores[exchange_symbol] = store

            # Also map by Kalshi symbol for convenience
            kalshi_sym = REVERSE_SYMBOL_MAP.get(exchange_symbol)
            if kalshi_sym:
                self._stores[kalshi_sym] = store

        # Connect
        connected = await self.client.connect()
        if not connected:
            logger.warning("CryExc connection failed — strategies will use fallback data")
            return False

        # Subscribe to each symbol
        for sym_config in self._symbol_configs:
            exchange_symbol = sym_config.get("symbol", "")
            exchanges = sym_config.get("exchanges", [])
            min_trade = sym_config.get("min_notional_trade", 0)
            min_liq = sym_config.get("min_notional_liq", 0)

            await self.client.subscribe(
                symbol=exchange_symbol,
                exchanges=exchanges,
                min_notional_trade=min_trade,
                min_notional_liq=min_liq,
            )

        # Start listen loop as background task
        self._listen_task = asyncio.create_task(self.client.listen_loop())

        logger.info(
            f"CryExc bridge connected: {len(self._stores)} stores active"
        )
        return True

    async def disconnect(self) -> None:
        """Disconnect client and cancel listen task."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        await self.client.disconnect()
        logger.info("CryExc bridge disconnected")

    def get_signal_store(self, symbol: str) -> Optional[CryptoSignalStore]:
        """
        Get the signal store for a symbol.

        Accepts both Kalshi symbols (BTC) and exchange symbols (BTCUSDT).

        Args:
            symbol: "BTC" or "BTCUSDT"

        Returns:
            CryptoSignalStore or None if not configured.
        """
        # Direct lookup (handles both BTC and BTCUSDT since we stored both)
        store = self._stores.get(symbol)
        if store:
            return store

        # Try mapping Kalshi -> exchange symbol
        exchange_sym = SYMBOL_MAP.get(symbol)
        if exchange_sym:
            return self._stores.get(exchange_sym)

        return None

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    def get_all_stats(self) -> Dict[str, Any]:
        """Get diagnostic stats for all stores."""
        stats = {}
        seen = set()
        for key, store in self._stores.items():
            if store.symbol not in seen:
                stats[store.symbol] = store.get_stats()
                seen.add(store.symbol)
        return stats
