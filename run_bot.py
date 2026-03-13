#!/usr/bin/env python3
"""
Kalshi Trading Bot - Entry Point

Run this script to start the trading bot.

Usage:
    # Basic (legacy mode - single mean-reversion strategy)
    python run_bot.py

    # Multi-strategy mode
    python run_bot.py --multi

    # With specific profile
    python run_bot.py --profile=aggressive

    # With specific strategies
    python run_bot.py --strategies=mean_reversion,momentum

    # Combined
    python run_bot.py --profile=scalper --strategies=momentum

Environment Variables Required:
    KALSHI_API_KEY_ID      - Your Kalshi API key ID
    KALSHI_PRIVATE_KEY_PATH - Path to your RSA private key (default: ./kalshi_private_key.pem)

Optional Environment Variables:
    KALSHI_MAX_POSITION     - Max position size in dollars (default: 50)
    KALSHI_DAILY_LOSS_LIMIT - Daily loss limit in dollars (default: 100)
    KALSHI_JOURNAL_DB       - Path to SQLite journal (default: ./trade_journal.db)
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

# Add the project directory to the Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

# Load environment variables from .env file if it exists
env_file = project_dir / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

from kalshi_trader import KalshiTradingBot
from kalshi_trader.config import load_config, get_strategy_configs, load_profile


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kalshi Trading Bot - Multi-Strategy Plugin Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_bot.py                              # Legacy mode (single strategy)
    python run_bot.py --multi                      # Multi-strategy from config.yaml
    python run_bot.py --profile=aggressive         # Use aggressive profile
    python run_bot.py --strategies=momentum        # Run only momentum strategy
    python run_bot.py --list-strategies            # Show available strategies
    python run_bot.py --list-profiles              # Show available profiles
        """
    )

    parser.add_argument(
        "--multi",
        action="store_true",
        help="Enable multi-strategy mode via StrategyManager",
    )

    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Load a profile from profiles/ directory (conservative, aggressive, scalper)",
    )

    parser.add_argument(
        "--strategies",
        type=str,
        default=None,
        help="Comma-separated list of strategies to enable (overrides config.yaml)",
    )

    parser.add_argument(
        "--config",
        type=str,
        default="./config.yaml",
        help="Path to config.yaml file",
    )

    parser.add_argument(
        "--list-strategies",
        action="store_true",
        help="List available strategies and exit",
    )

    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profiles and exit",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan for opportunities but don't place trades",
    )

    parser.add_argument(
        "--paper-trade",
        action="store_true",
        help="Run full pipeline with simulated fills — no real orders, real journal entries",
    )

    parser.add_argument(
        "--paper-balance",
        type=float,
        default=None,
        help="Simulated balance for paper trading (e.g., --paper-balance 500). Implies --paper-trade.",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    return parser.parse_args()


def list_strategies():
    """List available strategies."""
    try:
        from strategies import STRATEGY_REGISTRY
        print("\nAvailable Strategies:")
        print("-" * 50)
        for name, cls in STRATEGY_REGISTRY.items():
            instance = cls({})
            print(f"  {name}")
            print(f"    {instance.description}")
            edge = instance.calculate_edge()
            print(f"    EV: {edge['expected_value_cents']:+.2f}c | Kelly: {edge['kelly_pct']:.1%}")
            print()
    except ImportError as e:
        print(f"Error loading strategies: {e}")


def list_profiles():
    """List available profiles."""
    profiles_dir = Path(__file__).parent / "profiles"
    print("\nAvailable Profiles:")
    print("-" * 50)

    if not profiles_dir.exists():
        print("  No profiles directory found")
        return

    for profile_file in sorted(profiles_dir.glob("*.yaml")):
        profile_name = profile_file.stem
        # Load and display profile info
        try:
            import yaml
            with open(profile_file) as f:
                data = yaml.safe_load(f) or {}

            desc = data.get("description", "No description")
            risk = data.get("risk", {})
            max_pos = risk.get("max_position_size", "N/A")
            kelly = risk.get("kelly_fraction", "N/A")

            print(f"  {profile_name}")
            print(f"    {desc}")
            print(f"    Max position: ${max_pos} | Kelly: {kelly}")
            print()
        except Exception as e:
            print(f"  {profile_name} (error loading: {e})")


def build_strategy_configs(args, base_configs):
    """Build strategy configs based on CLI args."""
    if not args.strategies:
        return base_configs

    # Parse comma-separated strategy names
    requested = [s.strip() for s in args.strategies.split(",")]

    # Filter configs to only requested strategies
    filtered = []
    for config in base_configs:
        if config["name"] in requested:
            config["enabled"] = True
            filtered.append(config)

    # Add any missing strategies with defaults
    existing_names = {c["name"] for c in filtered}
    for name in requested:
        if name not in existing_names:
            filtered.append({
                "name": name,
                "enabled": True,
                "markets": [{"platform": "kalshi", "series": "INXD"}],
                "config": {},
            })

    return filtered


def _acquire_pidlock() -> bool:
    """Prevent duplicate bot instances. Returns True if lock acquired."""
    pidfile = Path(__file__).parent / ".bot.pid"
    if pidfile.exists():
        try:
            old_pid = int(pidfile.read_text().strip())
            # Check if process is actually running
            os.kill(old_pid, 0)
            # Process exists — refuse to start
            print(f"ERROR: Bot already running (PID {old_pid}). Kill it first or delete {pidfile}")
            return False
        except (ProcessLookupError, ValueError):
            # Stale PID file — clean up and continue
            pass
        except PermissionError:
            # Process exists but we can't signal it — still refuse
            print(f"ERROR: Bot already running (PID {pidfile.read_text().strip()}).")
            return False

    pidfile.write_text(str(os.getpid()))

    # Clean up PID file on exit
    def _cleanup(*_):
        try:
            pidfile.unlink(missing_ok=True)
        except Exception:
            pass

    import atexit
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))
    return True


def main():
    """Main entry point."""
    args = parse_args()

    # Handle list commands
    if args.list_strategies:
        list_strategies()
        return

    if args.list_profiles:
        list_profiles()
        return

    # Configure logging
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("=" * 60)
    print("DAE — Kalshi Trading Bot")
    print("The Craftsman Who Never Sleeps")
    print("=" * 60)
    print()

    # Load configuration
    config = load_config(
        config_path=args.config,
        profile=args.profile,
    )

    # Display settings
    print(f"Market Series:      {config.market_series}")
    print(f"Max Position:       ${config.max_position_size:.2f}")
    print(f"Daily Loss Limit:   ${config.daily_loss_limit:.2f}")
    print(f"Kelly Fraction:     {config.kelly_fraction:.0%}")
    print(f"Take Profit:        +{config.take_profit_cents}c")
    print(f"Stop Loss:          -{config.stop_loss_cents}c")
    print(f"Poll Interval:      {config.poll_interval_seconds}s")
    print()

    # Determine mode
    use_multi = args.multi or args.profile or args.strategies

    if use_multi:
        print(f"Mode:               Multi-Strategy")
        if args.profile:
            print(f"Profile:            {args.profile}")

        # Get strategy configs
        strategy_configs = get_strategy_configs()

        # Apply CLI overrides
        if args.strategies:
            strategy_configs = build_strategy_configs(args, strategy_configs)
            enabled = [c["name"] for c in strategy_configs if c.get("enabled", True)]
            print(f"Strategies:         {', '.join(enabled)}")
        else:
            enabled = [c["name"] for c in strategy_configs if c.get("enabled", True)]
            print(f"Strategies:         {', '.join(enabled)}")
    else:
        print(f"Mode:               Legacy (single strategy)")
        strategy_configs = None

    print()

    # Validate credentials
    valid, error = config.validate_credentials()
    if not valid:
        print(f"ERROR: {error}")
        print()
        print("Please ensure you have:")
        print("  1. Set KALSHI_API_KEY_ID in .env or environment")
        print("  2. Placed your private key at ./kalshi_private_key.pem")
        print()
        sys.exit(1)

    # Show credentials are configured without revealing sensitive details
    print(f"API Key:            [configured]")
    print(f"Private Key:        [configured]")
    print(f"Journal DB:         [configured]")
    print()

    # --paper-balance implies --paper-trade
    if args.paper_balance is not None:
        args.paper_trade = True

    if args.paper_trade and args.dry_run:
        print("ERROR: --paper-trade and --dry-run are mutually exclusive")
        print("  --dry-run: logs only, no journal entries")
        print("  --paper-trade: simulated fills, real journal entries")
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN MODE - Will scan but not place trades")
        print()
    elif args.paper_trade:
        print("PAPER TRADE MODE - Simulated fills, real journal tracking")
        print("  Orders: SIMULATED (instant fill at signal price)")
        print("  Journal: REAL (tagged paper_trade=true)")
        print("  Risk/Kelly: REAL (updates normally)")
        print("  API: Market data only (no order placement)")
        if args.paper_balance:
            print(f"  Balance: SIMULATED (${args.paper_balance:.2f})")
        print()

    # Acquire PID lock — prevents double-instance (causes duplicate Telegram replies)
    if not _acquire_pidlock():
        sys.exit(1)

    print("Starting bot... (Ctrl+C to stop)")
    print("-" * 60)

    # Run the bot
    bot = KalshiTradingBot(
        config,
        use_strategy_manager=use_multi,
        strategy_configs=strategy_configs,
        dry_run=args.dry_run,
        paper_trade=args.paper_trade,
        paper_balance=args.paper_balance,
    )
    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
