"""
Kalshi Trading Bot Configuration

Pydantic-based configuration management for the Kalshi trading bot.
Supports multiple configuration sources:
1. YAML configuration files (config.yaml, profiles/*.yaml)
2. Environment variables with KALSHI_ prefix (backward compatible)
3. Programmatic configuration

Priority: YAML > Environment > Defaults
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# Default paths
DEFAULT_CONFIG_PATH = "./config.yaml"
DEFAULT_PROFILES_DIR = "./profiles"


class StrategyMarketConfigItem(BaseModel):
    """Configuration for a single market target in a strategy."""

    # Allow adding optional fields (e.g. "scan") without breaking parsing.
    model_config = ConfigDict(extra="allow")

    platform: str = Field(default="kalshi", description="Market platform name")
    series: str = Field(description="Series ticker, or '*' for no series filter")
    scan: bool = Field(
        default=True,
        description="Whether StrategyManager should fetch and scan this market list",
    )


class StrategyConfigItem(BaseModel):
    """Configuration for a single strategy in YAML."""

    name: str = Field(description="Strategy identifier")
    enabled: bool = Field(default=True, description="Whether strategy is active")
    markets: List[StrategyMarketConfigItem] = Field(
        default_factory=list,
        description="Markets to run this strategy on",
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy-specific configuration",
    )


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_position_size: float = Field(
        default=50.0,
        description="Maximum position size per trade in dollars",
        ge=1.0,
        le=10000.0,
    )
    daily_loss_limit: float = Field(
        default=100.0,
        description="Stop trading after this daily loss in dollars",
        ge=0.0,
    )
    kelly_fraction: float = Field(
        default=0.5,
        description="Fraction of Kelly criterion to use",
        ge=0.1,
        le=1.0,
    )
    min_position_size: float = Field(
        default=1.0,
        description="Minimum position size in dollars",
        ge=1.0,
    )
    max_position_pct: float = Field(
        default=5.0,
        description="Maximum position size as percentage of balance (e.g., 3.0 = 3%)",
        ge=0.1,
        le=100.0,
    )
    max_total_exposure_pct: float = Field(
        default=25.0,
        description="Maximum total exposure as percentage of balance (circuit breaker)",
        ge=1.0,
        le=100.0,
    )


class LearningConfig(BaseModel):
    """Learning loop configuration."""

    prior_strength: int = Field(
        default=20,
        description="Bayesian prior strength (k parameter)",
        ge=1,
        le=100,
    )
    decay_half_life: float = Field(
        default=30.0,
        description="Days until trade weight halves",
        ge=1.0,
        le=365.0,
    )
    auto_disable: bool = Field(
        default=False,
        description="Auto-disable critical strategies",
    )


class CryExcSymbolConfig(BaseModel):
    """Configuration for a single CryExc symbol subscription."""

    symbol: str = Field(description="Exchange symbol, e.g. BTCUSDT")
    exchanges: List[str] = Field(
        default_factory=list,
        description="Filter to specific exchanges, or empty for all",
    )
    min_notional_trade: float = Field(
        default=0,
        description="Minimum trade notional to relay",
        ge=0,
    )
    min_notional_liq: float = Field(
        default=0,
        description="Minimum liquidation notional to relay",
        ge=0,
    )


class CryExcReconnectConfig(BaseModel):
    """CryExc WebSocket reconnect parameters."""

    base_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    max_seconds: float = Field(default=30.0, ge=1.0, le=300.0)


class CryExcConfig(BaseModel):
    """CryExc real-time exchange data configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable CryExc integration (opt-in)",
    )
    url: str = Field(
        default="ws://localhost:8086/ws",
        description="CryExc WebSocket server URL",
    )
    symbols: List[CryExcSymbolConfig] = Field(
        default_factory=list,
        description="Symbols to subscribe to",
    )
    reconnect: CryExcReconnectConfig = Field(
        default_factory=CryExcReconnectConfig,
        description="Reconnect behavior",
    )


class BreakerConfig(BaseModel):
    """Circuit breaker configuration for raw-signal trading safeguards."""

    min_win_rate: float = Field(default=0.40, ge=0.0, le=1.0)
    win_rate_window: int = Field(default=20, ge=5, le=100)
    max_consecutive_losses: int = Field(default=5, ge=2, le=20)
    max_drawdown_pct: float = Field(default=0.10, ge=0.01, le=0.50)


class YAMLConfig(BaseModel):
    """Full YAML configuration structure."""

    profile: Optional[str] = Field(
        default=None,
        description="Profile name to load from profiles/",
    )
    strategies: List[StrategyConfigItem] = Field(
        default_factory=list,
        description="List of strategy configurations",
    )
    risk: RiskConfig = Field(
        default_factory=RiskConfig,
        description="Risk management settings",
    )
    learning: LearningConfig = Field(
        default_factory=LearningConfig,
        description="Learning loop settings",
    )
    breaker: BreakerConfig = Field(
        default_factory=BreakerConfig,
        description="Circuit breaker thresholds",
    )
    cryexc: CryExcConfig = Field(
        default_factory=CryExcConfig,
        description="CryExc real-time exchange data settings",
    )


class KalshiConfig(BaseModel):
    """
    Configuration for Kalshi Trading Bot.

    Loads from environment variables with KALSHI_ prefix.
    All monetary values are in dollars.

    Example:
        >>> config = KalshiConfig()
        >>> print(f"Max position: ${config.max_position_size}")
    """

    # API Authentication
    api_key_id: str = Field(
        default_factory=lambda: os.getenv("KALSHI_API_KEY_ID", ""),
        description="Kalshi API key ID from dashboard",
    )
    private_key_path: str = Field(
        default_factory=lambda: os.getenv(
            "KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem"
        ),
        description="Path to RSA private key PEM file",
    )

    # Trading Parameters
    max_position_size: float = Field(
        default_factory=lambda: float(os.getenv("KALSHI_MAX_POSITION", "50")),
        description="Maximum position size per trade in dollars",
        ge=1.0,
        le=10000.0,
    )
    daily_loss_limit: float = Field(
        default_factory=lambda: float(os.getenv("KALSHI_DAILY_LOSS_LIMIT", "100")),
        description="Stop trading after this daily loss in dollars",
        ge=0.0,
    )
    kelly_fraction: float = Field(
        default=0.5,
        description="Fraction of Kelly criterion to use (0.5 = half-Kelly)",
        ge=0.1,
        le=1.0,
    )
    min_position_size: float = Field(
        default=1.0,
        description="Minimum position size in dollars (Kalshi minimum)",
        ge=1.0,
    )

    # Market Selection
    market_series: str = Field(
        default="INXD",
        description="Market series to trade (INXD = S&P 500 hourly)",
    )
    min_volume: int = Field(
        default=100,
        description="Minimum market volume to consider",
        ge=0,
    )

    # Strategy Parameters
    price_floor_cents: int = Field(
        default=45,
        description="Minimum price in cents for mean-reversion trades",
        ge=1,
        le=99,
    )
    price_ceiling_cents: int = Field(
        default=55,
        description="Maximum price in cents for mean-reversion trades",
        ge=1,
        le=99,
    )
    take_profit_cents: int = Field(
        default=8,
        description="Take profit threshold in cents (8c for positive EV)",
        ge=1,
    )
    stop_loss_cents: int = Field(
        default=5,
        description="Stop loss threshold in cents (5c for better risk:reward)",
        ge=1,
    )

    # Operational
    poll_interval_seconds: int = Field(
        default=60,
        description="Seconds between trading cycles",
        ge=10,
        le=3600,
    )
    api_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2"
        ),
        description="Kalshi API base URL",
    )
    use_demo: bool = Field(
        default=False,
        description="Use demo API instead of production",
    )

    # Database
    journal_db_path: str = Field(
        default_factory=lambda: os.getenv(
            "KALSHI_JOURNAL_DB",
            "./trade_journal.db",
        ),
        description="Path to SQLite trade journal database",
    )

    # Learning Loop
    learning_prior_strength: int = Field(
        default=20,
        description="How many trades the prior is 'worth' in Bayesian blending (k parameter)",
        ge=1,
        le=100,
    )
    learning_decay_half_life: float = Field(
        default=30.0,
        description="Days until a trade's weight halves in the decay function",
        ge=1.0,
        le=365.0,
    )
    learning_auto_disable: bool = Field(
        default=False,
        description="Auto-disable strategies that reach critical health (off by default — flag only)",
    )

    # Circuit Breaker Thresholds
    breaker_min_win_rate: float = Field(
        default=0.40,
        description="Trip breaker if raw win rate falls below this (0-1)",
        ge=0.0,
        le=1.0,
    )
    breaker_win_rate_window: int = Field(
        default=20,
        description="Number of recent trades to evaluate for win rate breaker",
        ge=5,
        le=100,
    )
    breaker_max_consecutive_losses: int = Field(
        default=5,
        description="Trip breaker after this many consecutive losses",
        ge=2,
        le=20,
    )
    breaker_max_drawdown_pct: float = Field(
        default=0.10,
        description="Trip breaker if strategy drawdown exceeds this (0-1)",
        ge=0.01,
        le=0.50,
    )

    @field_validator("private_key_path")
    @classmethod
    def expand_key_path(cls, v: str) -> str:
        """Expand ~ in path and validate file exists."""
        expanded = os.path.expanduser(v)
        return expanded

    @field_validator("price_ceiling_cents")
    @classmethod
    def validate_price_range(cls, v: int, info) -> int:
        """Ensure ceiling > floor."""
        floor = info.data.get("price_floor_cents", 45)
        if v <= floor:
            raise ValueError(f"price_ceiling_cents ({v}) must be > price_floor_cents ({floor})")
        return v

    @property
    def private_key_path_resolved(self) -> Path:
        """Get resolved private key path."""
        return Path(os.path.expanduser(self.private_key_path))

    @property
    def demo_base_url(self) -> str:
        """Demo API URL."""
        return "https://demo-api.kalshi.co/trade-api/v2"

    @property
    def effective_base_url(self) -> str:
        """Get the effective API URL based on demo flag."""
        return self.demo_base_url if self.use_demo else self.api_base_url

    def validate_credentials(self) -> tuple[bool, str]:
        """
        Validate that API credentials are configured.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.api_key_id:
            return False, "KALSHI_API_KEY_ID not set"

        key_path = self.private_key_path_resolved
        if not key_path.exists():
            return False, f"Private key not found: {key_path}"

        return True, ""

    class Config:
        """Pydantic model configuration."""

        extra = "ignore"
        validate_default = True


def load_config(
    config_path: Optional[str] = None,
    profile: Optional[str] = None,
) -> KalshiConfig:
    """
    Load configuration from YAML and/or environment variables.

    Configuration priority (highest to lowest):
    1. Explicit parameters
    2. YAML config file
    3. Profile YAML file
    4. Environment variables
    5. Defaults

    Args:
        config_path: Path to config.yaml (default: ./config.yaml)
        profile: Profile name to load (overrides YAML profile setting)

    Returns:
        KalshiConfig instance with validated settings

    Raises:
        ValueError: If configuration is invalid
    """
    config_dict: Dict[str, Any] = {}
    yaml_config: Optional[YAMLConfig] = None

    # Try to load YAML config
    config_path = config_path or DEFAULT_CONFIG_PATH
    config_file = Path(config_path)

    if config_file.exists():
        try:
            with open(config_file) as f:
                raw_config = yaml.safe_load(f) or {}

            yaml_config = YAMLConfig(**raw_config)
            logger.info(f"Loaded configuration from {config_file}")

            # Apply risk settings from YAML
            if yaml_config.risk:
                config_dict["max_position_size"] = yaml_config.risk.max_position_size
                config_dict["daily_loss_limit"] = yaml_config.risk.daily_loss_limit
                config_dict["kelly_fraction"] = yaml_config.risk.kelly_fraction
                config_dict["min_position_size"] = yaml_config.risk.min_position_size

            # Apply learning settings from YAML
            if yaml_config.learning:
                config_dict["learning_prior_strength"] = yaml_config.learning.prior_strength
                config_dict["learning_decay_half_life"] = yaml_config.learning.decay_half_life
                config_dict["learning_auto_disable"] = yaml_config.learning.auto_disable

            # Apply breaker settings from YAML
            if yaml_config.breaker:
                config_dict["breaker_min_win_rate"] = yaml_config.breaker.min_win_rate
                config_dict["breaker_win_rate_window"] = yaml_config.breaker.win_rate_window
                config_dict["breaker_max_consecutive_losses"] = yaml_config.breaker.max_consecutive_losses
                config_dict["breaker_max_drawdown_pct"] = yaml_config.breaker.max_drawdown_pct

        except Exception as e:
            logger.warning(f"Failed to load YAML config: {e}")
            yaml_config = None

    # Load profile if specified
    profile_name = profile or (yaml_config.profile if yaml_config else None)
    if profile_name:
        profile_config = load_profile(profile_name)
        if profile_config:
            # Merge profile settings (profile overrides base YAML)
            config_dict.update(profile_config)

    # Environment variables still work (backward compatibility)
    # They're handled by default_factory in KalshiConfig
    if not config_dict:
        # No YAML found, using env vars
        logger.info("Using environment variables for configuration")

    return KalshiConfig(**config_dict)


def load_profile(profile_name: str, profiles_dir: str = DEFAULT_PROFILES_DIR) -> Dict[str, Any]:
    """
    Load a profile YAML file.

    Args:
        profile_name: Name of profile (without .yaml extension)
        profiles_dir: Directory containing profile files

    Returns:
        Profile configuration dict, empty if not found
    """
    profile_path = Path(profiles_dir) / f"{profile_name}.yaml"

    if not profile_path.exists():
        logger.warning(f"Profile not found: {profile_path}")
        return {}

    try:
        with open(profile_path) as f:
            profile_data = yaml.safe_load(f) or {}

        logger.info(f"Loaded profile: {profile_name}")

        # Extract risk settings into flat config
        config = {}
        if "risk" in profile_data:
            risk = profile_data["risk"]
            if "max_position_size" in risk:
                config["max_position_size"] = risk["max_position_size"]
            if "daily_loss_limit" in risk:
                config["daily_loss_limit"] = risk["daily_loss_limit"]
            if "kelly_fraction" in risk:
                config["kelly_fraction"] = risk["kelly_fraction"]

        return config

    except Exception as e:
        logger.warning(f"Failed to load profile {profile_name}: {e}")
        return {}


def load_yaml_config(config_path: str = DEFAULT_CONFIG_PATH) -> Optional[YAMLConfig]:
    """
    Load and parse YAML configuration file.

    Args:
        config_path: Path to config.yaml

    Returns:
        YAMLConfig instance or None if not found/invalid
    """
    config_file = Path(config_path)

    if not config_file.exists():
        return None

    try:
        with open(config_file) as f:
            raw_config = yaml.safe_load(f) or {}

        return YAMLConfig(**raw_config)
    except Exception as e:
        logger.error(f"Failed to parse YAML config: {e}")
        return None


def get_strategy_configs(
    yaml_config: Optional[YAMLConfig] = None,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> List[Dict[str, Any]]:
    """
    Get strategy configurations from YAML.

    Args:
        yaml_config: Pre-loaded YAMLConfig or None
        config_path: Path to config.yaml if yaml_config not provided

    Returns:
        List of strategy configuration dicts
    """
    if yaml_config is None:
        yaml_config = load_yaml_config(config_path)

    if yaml_config is None or not yaml_config.strategies:
        # Return default mean-reversion strategy
        return [
            {
                "name": "mean_reversion",
                "enabled": True,
                "markets": [{"platform": "kalshi", "series": "INXD"}],
                "config": {
                    "price_floor_cents": 45,
                    "price_ceiling_cents": 55,
                    "take_profit_cents": 8,
                    "stop_loss_cents": 5,
                    "min_volume": 100,
                },
            }
        ]

    return [s.model_dump() for s in yaml_config.strategies]


def create_default_config_yaml(output_path: str = DEFAULT_CONFIG_PATH) -> None:
    """
    Create a default config.yaml file.

    Args:
        output_path: Where to write the file
    """
    default_config = """# Kalshi Trading Bot Configuration
# See profiles/ for risk profile options

profile: null  # Or: conservative, aggressive, scalper

strategies:
  - name: mean_reversion
    enabled: true
    markets:
      - platform: kalshi
        series: INXD
    config:
      price_floor_cents: 45
      price_ceiling_cents: 55
      take_profit_cents: 8
      stop_loss_cents: 5
      min_volume: 100

risk:
  max_position_size: 50
  daily_loss_limit: 100
  kelly_fraction: 0.5
"""

    with open(output_path, "w") as f:
        f.write(default_config)

    logger.info(f"Created default config at {output_path}")
