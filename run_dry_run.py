#!/usr/bin/env python3
"""
Dry-run script with full multi-strategy + cross-platform support
"""
import asyncio
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from kalshi_trader.config import load_config, get_strategy_configs
from kalshi_trader.kalshi_client import AuthenticatedKalshiClient
from kalshi_trader.deepstack_integration import DeepStackIntegration
from kalshi_trader.journal import TradeJournal
from kalshi_trader.strategy_manager import StrategyManager
from markets.kalshi import KalshiMarket
from markets.polymarket import PolymarketMarket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    """Run dry-run mode"""
    logger.info("=" * 60)
    logger.info("KALSHI TRADING BOT - DRY RUN MODE")
    logger.info("=" * 60)
    
    # Load config
    config = load_config()
    logger.info(f"Loaded config: {config.max_position_size=}, {config.daily_loss_limit=}")
    
    # Initialize Kalshi client
    kalshi_client = AuthenticatedKalshiClient(config)
    await kalshi_client.connect()
    
    # Verify connection
    balance = await kalshi_client.get_balance()
    logger.info(f"✅ Kalshi API connected | Balance: ${balance.get('balance', 0):.2f}")
    
    # Initialize markets
    kalshi_market = KalshiMarket(config.model_dump())
    polymarket_market = PolymarketMarket({})
    
    markets = {
        'kalshi': kalshi_market,
        'polymarket': polymarket_market,
    }
    logger.info(f"✅ Initialized {len(markets)} market clients")
    
    # Initialize risk management
    deepstack = DeepStackIntegration(config, kalshi_client)
    await deepstack.update_balance()
    logger.info("✅ DeepStack risk management initialized")
    
    # Initialize strategy manager
    strategy_configs = get_strategy_configs(config)
    strategy_manager = StrategyManager(
        strategy_configs=strategy_configs,
        markets=markets,
        config=config,
    )
    logger.info(f"✅ StrategyManager: {strategy_manager}")
    
    # Initialize journal
    journal = TradeJournal(config.journal_db_path)
    logger.info("✅ Trade journal initialized")
    
    # Trading loop
    logger.info("-" * 60)
    logger.info("Starting scan loop (DRY RUN - no trades will be placed)")
    logger.info(f"Poll interval: {config.poll_interval_seconds}s")
    logger.info("-" * 60)
    
    scan_count = 0
    try:
        while True:
            scan_count += 1
            logger.info(f"\n[SCAN #{scan_count}] Starting opportunity scan...")
            
            # Update balance
            await deepstack.update_balance()
            
            # Scan for opportunities across all strategies
            opportunities = await strategy_manager.scan_all_opportunities()
            
            if opportunities:
                logger.info(f"🎯 Found {len(opportunities)} opportunities!")
                
                # Rank and display top opportunities
                ranked = await strategy_manager.rank_opportunities(opportunities)
                
                for i, opp in enumerate(ranked[:5], 1):
                    logger.info(f"  #{i} [{opp.strategy}] {opp.ticker} | "
                               f"{opp.side.upper()} @ {opp.entry_price_cents}¢ | "
                               f"Score: {opp.score:.1f} | "
                               f"Reason: {opp.reasoning[:80]}")
                
                if len(ranked) > 5:
                    logger.info(f"  ... and {len(ranked) - 5} more")
            else:
                logger.info("No opportunities found this scan")
            
            logger.info(f"Waiting {config.poll_interval_seconds}s until next scan...")
            await asyncio.sleep(config.poll_interval_seconds)
            
    except KeyboardInterrupt:
        logger.info("\n\nShutdown requested - stopping gracefully...")
    except Exception as e:
        logger.error(f"Error in trading loop: {e}", exc_info=True)
    finally:
        # Cleanup
        logger.info("=" * 60)
        logger.info(f"DRY RUN COMPLETE - {scan_count} scans performed")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
