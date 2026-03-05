"""
Seas — Multi-Regime Synthetic Data Generator

Generates market snapshots under 5 distinct "sea conditions" (market regimes)
using a modified Ornstein-Uhlenbeck process with drift and spike injection:

    dX = theta * (mu - X) * dt + sigma * dW + drift * dt

Each sea condition tunes these parameters to create data that activates
different trading strategies:

    mean_reverting:   Strong pull to center, tight range
    trending_up:      Persistent uptrend, prices climb
    trending_down:    Persistent downtrend, prices fall
    high_vol_choppy:  Large swings, sudden spikes
    low_vol_calm:     Near-expiry calm with prices at extremes

Output format matches BacktestRunner.generate_synthetic() exactly, so
snapshots can be fed directly into the existing arena engine.
"""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SeaCondition:
    """Parameters defining a single sea (market regime).

    Ornstein-Uhlenbeck parameters:
        mu:        Long-run mean price (cents, 1-99)
        theta:     Mean-reversion strength (0=random walk, 1=snap to mu)
        sigma:     Per-step volatility (std dev in cents)
        drift:     Directional bias per step (cents)

    Market microstructure:
        spread_base:      Base bid-ask spread in cents
        volume_mean:      Mean volume per timestep
        spike_prob:       Probability of a spike event per step
        spike_magnitude:  Spike size as multiplier of sigma
    """

    name: str
    mu: float = 50.0
    theta: float = 0.05
    sigma: float = 2.0
    drift: float = 0.0
    spread_base: int = 2
    volume_mean: int = 500
    spike_prob: float = 0.0
    spike_magnitude: float = 3.0


# Five canonical sea conditions
SEAS: Dict[str, SeaCondition] = {
    "mean_reverting": SeaCondition(
        name="mean_reverting",
        mu=50.0,
        theta=0.15,
        sigma=2.0,
        drift=0.0,
        spread_base=2,
        volume_mean=500,
        spike_prob=0.0,
        spike_magnitude=0.0,
    ),
    "trending_up": SeaCondition(
        name="trending_up",
        mu=70.0,
        theta=0.02,
        sigma=2.5,
        drift=0.4,
        spread_base=3,
        volume_mean=600,
        spike_prob=0.01,
        spike_magnitude=2.0,
    ),
    "trending_down": SeaCondition(
        name="trending_down",
        mu=30.0,
        theta=0.02,
        sigma=2.5,
        drift=-0.4,
        spread_base=3,
        volume_mean=600,
        spike_prob=0.01,
        spike_magnitude=2.0,
    ),
    "high_vol_choppy": SeaCondition(
        name="high_vol_choppy",
        mu=50.0,
        theta=0.05,
        sigma=6.0,
        drift=0.0,
        spread_base=4,
        volume_mean=800,
        spike_prob=0.03,
        spike_magnitude=3.0,
    ),
    "low_vol_calm": SeaCondition(
        name="low_vol_calm",
        mu=93.0,
        theta=0.10,
        sigma=0.5,
        drift=0.0,
        spread_base=1,
        volume_mean=300,
        spike_prob=0.0,
        spike_magnitude=0.0,
    ),
}

ALL_SEA_NAMES = list(SEAS.keys())


class SeaGenerator:
    """Generate synthetic market snapshots for each sea condition.

    Uses the same output format as BacktestRunner.generate_synthetic()
    so snapshots can be fed directly into the arena engine without adapters.
    """

    def __init__(self, interval_minutes: int = 60):
        self.interval_minutes = interval_minutes

    def generate_sea(
        self,
        condition: SeaCondition,
        timesteps: int = 10000,
        seed: Optional[int] = None,
        start_time: Optional[datetime] = None,
    ) -> List[Dict]:
        """Generate snapshots for a single sea condition.

        Args:
            condition: SeaCondition parameters for this regime.
            timesteps: Number of time periods to generate.
            seed: Random seed for reproducibility.
            start_time: Starting timestamp (defaults to 2026-01-01 09:30 UTC).

        Returns:
            List of snapshot dicts matching BacktestRunner format.
        """
        if seed is not None:
            random.seed(seed)

        now = start_time or datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
        delta = timedelta(minutes=self.interval_minutes)
        price = float(condition.mu)
        snapshots: List[Dict] = []

        ticker = f"ARENA-{condition.name.upper()}"

        for _ in range(timesteps):
            # Modified O-U step: dX = theta*(mu-X)*dt + sigma*dW + drift*dt
            mean_pull = condition.theta * (condition.mu - price)
            noise = random.gauss(0, condition.sigma)
            step = mean_pull + noise + condition.drift

            # Spike injection
            if condition.spike_prob > 0 and random.random() < condition.spike_prob:
                sign = random.choice([-1, 1])
                step += sign * condition.spike_magnitude * condition.sigma

            price += step
            price = max(1.0, min(99.0, price))

            price_int = int(round(price))
            half_spread = max(1, condition.spread_base // 2)

            yes_bid = max(1, price_int - half_spread)
            yes_ask = min(99, price_int + half_spread)
            no_price = 100 - price_int
            no_bid = max(1, no_price - half_spread)
            no_ask = min(99, no_price + half_spread)

            vol = max(0, int(
                condition.volume_mean
                + random.gauss(0, condition.volume_mean * 0.3)
            ))

            snapshots.append({
                "_timestamp": now,
                "ticker": ticker,
                "title": f"Synthetic {condition.name} Market",
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "no_bid": no_bid,
                "no_ask": no_ask,
                "last_price": price_int,
                "volume": vol,
                "volume_24h": vol,
                "open_interest": vol * 2,
                "status": "open",
                "close_time": (now + timedelta(days=7)).isoformat(),
            })
            now += delta

        logger.info(
            f"Generated {len(snapshots)} snapshots for sea '{condition.name}' "
            f"(mu={condition.mu}, theta={condition.theta}, "
            f"sigma={condition.sigma}, drift={condition.drift})"
        )
        return snapshots

    def generate_all_seas(
        self,
        timesteps_per_sea: int = 10000,
        seed: Optional[int] = None,
        regimes: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        """Generate snapshots for all (or a subset of) sea conditions.

        Args:
            timesteps_per_sea: Data points per sea.
            seed: Base seed (each sea gets seed+i for independence).
            regimes: Subset of regime names (default: all 5).

        Returns:
            Dict mapping regime name to list of snapshots.
        """
        names = regimes or ALL_SEA_NAMES
        result: Dict[str, List[Dict]] = {}

        for i, name in enumerate(names):
            condition = SEAS.get(name)
            if condition is None:
                logger.warning(f"Unknown sea '{name}', skipping")
                continue

            sea_seed = (seed + i) if seed is not None else None
            result[name] = self.generate_sea(
                condition,
                timesteps=timesteps_per_sea,
                seed=sea_seed,
            )

        logger.info(
            f"Generated {len(result)} seas, "
            f"{timesteps_per_sea} timesteps each"
        )
        return result

    def generate_voyage(
        self,
        timesteps: int = 50000,
        seed: Optional[int] = None,
    ) -> List[Dict]:
        """Generate a voyage — concatenated seas with regime transitions.

        Divides timesteps evenly across all 5 seas, concatenated in order.
        Useful for mixed-condition testing where strategies must adapt
        to changing regimes within a single data stream.

        Args:
            timesteps: Total timesteps across all seas.
            seed: Random seed for reproducibility.

        Returns:
            Single list of snapshots spanning all regimes sequentially.
        """
        per_sea = timesteps // len(ALL_SEA_NAMES)
        remainder = timesteps % len(ALL_SEA_NAMES)
        voyage: List[Dict] = []
        current_time = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)

        for i, name in enumerate(ALL_SEA_NAMES):
            condition = SEAS[name]
            count = per_sea + (1 if i < remainder else 0)
            sea_seed = (seed + i) if seed is not None else None

            snapshots = self.generate_sea(
                condition,
                timesteps=count,
                seed=sea_seed,
                start_time=current_time,
            )
            voyage.extend(snapshots)

            if snapshots:
                current_time = snapshots[-1]["_timestamp"] + timedelta(
                    minutes=self.interval_minutes
                )

        logger.info(
            f"Generated voyage: {len(voyage)} total snapshots "
            f"across {len(ALL_SEA_NAMES)} seas"
        )
        return voyage
