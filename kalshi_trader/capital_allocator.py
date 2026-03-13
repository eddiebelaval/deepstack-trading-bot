"""
Capital Allocator — Master Strategist Layer for DeepStack

Sits above GovernanceEngine. Answers: "Given our capital, regime, and
forward signals — what percentage of firepower goes where?"

Integrates the Principle Router (Council of Masters) for convergence/
divergence confirmation signals. When masters converge, conviction rises.
When they diverge, caution rises and reserve increases.

Thinks in centuries. Acts in cycles.

Capital Phases:
  SEED       ($0 - $500)       Build capital. Proven edges only. Survive.
  GROWTH     ($500 - $5K)      Diversify. Add regime-aware plays. Compound.
  FOUNDATION ($5K - $50K)      Shift toward preservation. Crisis readiness.
  COMPOUND   ($50K - $500K)    Let compounding work. Lower risk, higher size.
  DYNASTY    ($500K+)          Generational. Minimal drawdown. Think in decades.

Each phase has different allocation profiles per regime. The allocator
outputs weight maps that the StrategyManager uses for position sizing
instead of the naive equal-split.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CapitalPhase(Enum):
    SEED = "seed"
    GROWTH = "growth"
    FOUNDATION = "foundation"
    COMPOUND = "compound"
    DYNASTY = "dynasty"


@dataclass
class AllocationPlan:
    """Output of the Capital Allocator — weights per strategy."""

    phase: CapitalPhase
    regime: str
    thesis: str  # One-line market thesis driving this allocation
    weights: Dict[str, float]  # strategy_name -> weight (0.0 to 1.0, sum <= 1.0)
    reserve_pct: float  # Cash reserve percentage (dry powder)
    max_simultaneous: int  # Max concurrent positions across all strategies
    position_scale: float  # Multiplier on base position size (phase-dependent)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def deployed_pct(self) -> float:
        return sum(self.weights.values())

    def weight_for(self, strategy_name: str) -> float:
        return self.weights.get(strategy_name, 0.0)


# Phase thresholds (in dollars)
PHASE_THRESHOLDS = [
    (500, CapitalPhase.SEED),
    (5_000, CapitalPhase.GROWTH),
    (50_000, CapitalPhase.FOUNDATION),
    (500_000, CapitalPhase.COMPOUND),
]


def detect_phase(balance_dollars: float) -> CapitalPhase:
    """Determine capital phase from current balance."""
    for threshold, phase in PHASE_THRESHOLDS:
        if balance_dollars < threshold:
            return phase
    return CapitalPhase.DYNASTY


# ---------------------------------------------------------------------------
# Allocation Matrices — the strategic brain
#
# Each matrix maps (phase, regime) -> {strategy: weight, reserve, thesis}
# These encode Eddie's philosophy: centuries, not decades.
# ---------------------------------------------------------------------------

# Strategy categories for readability
PROVEN_KALSHI = ["calibration_edge", "high_probability_bonds"]
KALSHI_GROWTH = ["mean_reversion", "momentum", "settlement_betting"]
IBKR_OFFENSIVE = ["stock_momentum", "options_directional"]
IBKR_DEFENSIVE = ["crisis_alpha", "options_income"]
IBKR_FUTURES = ["futures_trend"]

# Master allocation profiles per phase
# Format: {regime: {strategies: {name: weight}, reserve: float, thesis: str, max_pos: int, scale: float}}
ALLOCATION_PROFILES: Dict[str, Dict[str, Any]] = {
    # ── SEED PHASE: Survive and build. Proven edges only. ─────────────────
    "seed": {
        "default": {
            "strategies": {"calibration_edge": 0.70, "high_probability_bonds": 0.20},
            "reserve": 0.10, "max_pos": 4, "scale": 0.8,
            "thesis": "Seed capital — maximize proven Kalshi edge, preserve dry powder",
        },
        "trending_up": {
            "strategies": {"calibration_edge": 0.60, "high_probability_bonds": 0.20, "momentum": 0.10},
            "reserve": 0.10, "max_pos": 5, "scale": 0.8,
            "thesis": "Seed + trend — lean into momentum while Kalshi edge compounds",
        },
        "trending_down": {
            "strategies": {"calibration_edge": 0.50, "high_probability_bonds": 0.25},
            "reserve": 0.25, "max_pos": 3, "scale": 0.6,
            "thesis": "Seed + downturn — tighten to proven edge, raise cash reserve",
        },
        "high_vol_choppy": {
            "strategies": {"calibration_edge": 0.50, "high_probability_bonds": 0.15},
            "reserve": 0.35, "max_pos": 3, "scale": 0.5,
            "thesis": "Seed + chaos — capital preservation paramount, only highest-conviction",
        },
        "mean_reverting": {
            "strategies": {"calibration_edge": 0.55, "high_probability_bonds": 0.20, "mean_reversion": 0.15},
            "reserve": 0.10, "max_pos": 5, "scale": 0.8,
            "thesis": "Seed + mean-revert — natural habitat for core strategies",
        },
        "low_vol_calm": {
            "strategies": {"calibration_edge": 0.65, "high_probability_bonds": 0.25},
            "reserve": 0.10, "max_pos": 5, "scale": 0.9,
            "thesis": "Seed + calm — ideal conditions, deploy aggressively within proven edges",
        },
    },

    # ── GROWTH PHASE: Diversify. Multi-asset. Compound. ───────────────────
    "growth": {
        "default": {
            "strategies": {
                "calibration_edge": 0.40, "high_probability_bonds": 0.10,
                "stock_momentum": 0.15, "mean_reversion": 0.10,
            },
            "reserve": 0.25, "max_pos": 6, "scale": 1.0,
            "thesis": "Growth — diversify across proven Kalshi + IBKR momentum",
        },
        "trending_up": {
            "strategies": {
                "calibration_edge": 0.30, "stock_momentum": 0.25,
                "momentum": 0.15, "options_directional": 0.10,
            },
            "reserve": 0.20, "max_pos": 7, "scale": 1.0,
            "thesis": "Growth + trend — ride the wave across asset classes",
        },
        "trending_down": {
            "strategies": {
                "calibration_edge": 0.30, "crisis_alpha": 0.25,
                "options_directional": 0.15, "high_probability_bonds": 0.10,
            },
            "reserve": 0.20, "max_pos": 6, "scale": 0.8,
            "thesis": "Growth + downturn — pivot to crisis alpha, protect capital",
        },
        "high_vol_choppy": {
            "strategies": {
                "calibration_edge": 0.35, "crisis_alpha": 0.15,
                "options_income": 0.15, "high_probability_bonds": 0.10,
            },
            "reserve": 0.25, "max_pos": 5, "scale": 0.7,
            "thesis": "Growth + chaos — sell premium, buy protection, keep Kalshi anchor",
        },
        "mean_reverting": {
            "strategies": {
                "calibration_edge": 0.30, "mean_reversion": 0.25,
                "stock_momentum": 0.15, "options_income": 0.10,
            },
            "reserve": 0.20, "max_pos": 7, "scale": 1.0,
            "thesis": "Growth + mean-revert — ideal for core strategies, expand allocation",
        },
        "low_vol_calm": {
            "strategies": {
                "calibration_edge": 0.35, "high_probability_bonds": 0.15,
                "options_income": 0.20, "stock_momentum": 0.10,
            },
            "reserve": 0.20, "max_pos": 7, "scale": 1.0,
            "thesis": "Growth + calm — sell premium aggressively, compound Kalshi edge",
        },
    },

    # ── FOUNDATION PHASE: Capital preservation + steady growth. ────────────
    "foundation": {
        "default": {
            "strategies": {
                "calibration_edge": 0.25, "stock_momentum": 0.15,
                "options_income": 0.15, "crisis_alpha": 0.05,
                "mean_reversion": 0.10, "high_probability_bonds": 0.05,
            },
            "reserve": 0.25, "max_pos": 8, "scale": 1.0,
            "thesis": "Foundation — balanced portfolio, always hedged, steady compounding",
        },
        "trending_up": {
            "strategies": {
                "stock_momentum": 0.25, "options_directional": 0.15,
                "calibration_edge": 0.20, "futures_trend": 0.10,
                "options_income": 0.10,
            },
            "reserve": 0.20, "max_pos": 10, "scale": 1.1,
            "thesis": "Foundation + trend — controlled aggression, futures for leverage",
        },
        "trending_down": {
            "strategies": {
                "crisis_alpha": 0.30, "options_directional": 0.15,
                "calibration_edge": 0.15, "options_income": 0.05,
                "high_probability_bonds": 0.05,
            },
            "reserve": 0.30, "max_pos": 7, "scale": 0.8,
            "thesis": "Foundation + downturn — crisis alpha leads, cash is king",
        },
        "high_vol_choppy": {
            "strategies": {
                "options_income": 0.25, "calibration_edge": 0.20,
                "crisis_alpha": 0.10, "high_probability_bonds": 0.10,
            },
            "reserve": 0.35, "max_pos": 6, "scale": 0.7,
            "thesis": "Foundation + chaos — sell premium (high IV), large cash buffer",
        },
        "mean_reverting": {
            "strategies": {
                "mean_reversion": 0.20, "calibration_edge": 0.20,
                "stock_momentum": 0.15, "options_income": 0.15,
                "futures_trend": 0.05,
            },
            "reserve": 0.25, "max_pos": 9, "scale": 1.0,
            "thesis": "Foundation + mean-revert — all systems nominal, full deployment",
        },
        "low_vol_calm": {
            "strategies": {
                "options_income": 0.25, "calibration_edge": 0.25,
                "stock_momentum": 0.10, "high_probability_bonds": 0.10,
            },
            "reserve": 0.30, "max_pos": 8, "scale": 1.0,
            "thesis": "Foundation + calm — premium selling paradise, stack income",
        },
    },

    # ── COMPOUND PHASE: Let the machine work. Low risk, high size. ────────
    "compound": {
        "default": {
            "strategies": {
                "calibration_edge": 0.15, "stock_momentum": 0.15,
                "options_income": 0.15, "crisis_alpha": 0.05,
                "mean_reversion": 0.10, "futures_trend": 0.05,
                "options_directional": 0.05,
            },
            "reserve": 0.30, "max_pos": 10, "scale": 1.2,
            "thesis": "Compound — diversified machine, let math work over decades",
        },
        "trending_down": {
            "strategies": {
                "crisis_alpha": 0.30, "options_directional": 0.15,
                "calibration_edge": 0.10, "options_income": 0.05,
            },
            "reserve": 0.40, "max_pos": 6, "scale": 0.8,
            "thesis": "Compound + downturn — protect the dynasty, crisis alpha leads",
        },
        "trending_up": {
            "strategies": {
                "stock_momentum": 0.20, "futures_trend": 0.10,
                "options_directional": 0.10, "calibration_edge": 0.15,
                "options_income": 0.10,
            },
            "reserve": 0.35, "max_pos": 8, "scale": 1.0,
            "thesis": "Compound + trend — ride it but never risk the base",
        },
        "high_vol_choppy": {
            "strategies": {
                "options_income": 0.20, "calibration_edge": 0.15,
                "crisis_alpha": 0.10,
            },
            "reserve": 0.55, "max_pos": 5, "scale": 0.6,
            "thesis": "Compound + chaos — massive cash reserve, only premium selling + hedges",
        },
        "mean_reverting": {
            "strategies": {
                "mean_reversion": 0.15, "calibration_edge": 0.15,
                "stock_momentum": 0.15, "options_income": 0.15,
                "futures_trend": 0.05,
            },
            "reserve": 0.35, "max_pos": 10, "scale": 1.0,
            "thesis": "Compound + mean-revert — full spectrum deployment, controlled",
        },
        "low_vol_calm": {
            "strategies": {
                "options_income": 0.25, "calibration_edge": 0.20,
                "stock_momentum": 0.10, "high_probability_bonds": 0.10,
            },
            "reserve": 0.35, "max_pos": 8, "scale": 1.0,
            "thesis": "Compound + calm — income machine, stack premium, protect base",
        },
    },

    # ── DYNASTY PHASE: Generational wealth. Never risk the base. ──────────
    "dynasty": {
        "default": {
            "strategies": {
                "options_income": 0.20, "calibration_edge": 0.10,
                "stock_momentum": 0.10, "crisis_alpha": 0.05,
                "high_probability_bonds": 0.05,
            },
            "reserve": 0.50, "max_pos": 8, "scale": 1.5,
            "thesis": "Dynasty — wealth preservation first, income second, growth third",
        },
        "trending_down": {
            "strategies": {
                "crisis_alpha": 0.25, "options_income": 0.05,
                "calibration_edge": 0.05,
            },
            "reserve": 0.65, "max_pos": 4, "scale": 0.5,
            "thesis": "Dynasty + downturn — fortress mode, protect at all costs",
        },
        "trending_up": {
            "strategies": {
                "stock_momentum": 0.15, "options_income": 0.15,
                "calibration_edge": 0.10, "futures_trend": 0.05,
            },
            "reserve": 0.55, "max_pos": 6, "scale": 1.0,
            "thesis": "Dynasty + trend — participate conservatively, never chase",
        },
        "high_vol_choppy": {
            "strategies": {"calibration_edge": 0.10, "options_income": 0.10},
            "reserve": 0.80, "max_pos": 3, "scale": 0.3,
            "thesis": "Dynasty + chaos — almost fully defensive, wait for clarity",
        },
        "mean_reverting": {
            "strategies": {
                "mean_reversion": 0.10, "calibration_edge": 0.10,
                "options_income": 0.15, "stock_momentum": 0.10,
            },
            "reserve": 0.55, "max_pos": 8, "scale": 1.0,
            "thesis": "Dynasty + mean-revert — comfortable environment, moderate deployment",
        },
        "low_vol_calm": {
            "strategies": {
                "options_income": 0.25, "calibration_edge": 0.15,
                "stock_momentum": 0.05, "high_probability_bonds": 0.05,
            },
            "reserve": 0.50, "max_pos": 7, "scale": 1.2,
            "thesis": "Dynasty + calm — income engine at full throttle, base untouched",
        },
    },
}


class CapitalAllocator:
    """
    Master strategist layer. Reads regime, forward signals, and capital phase
    to produce allocation plans that the trading loop follows.

    Integrates PrincipleRouter for convergence/divergence confirmation.
    When the council converges, sizing bias amplifies. When it diverges,
    reserve increases and sizing dampens — same confirmation shape as
    every other signal layer in DeepStack.

    Does NOT execute trades. Outputs AllocationPlan that StrategyManager consumes.
    """

    def __init__(self, principle_router=None, config: Optional[Dict] = None):
        self._config = config or {}
        self._current_plan: Optional[AllocationPlan] = None
        self._plan_history: Deque[AllocationPlan] = deque(maxlen=100)
        self._forward_signal_adjustments: Dict[str, float] = {}
        self._principle_router = principle_router

    @property
    def current_plan(self) -> Optional[AllocationPlan]:
        return self._current_plan

    @property
    def principle_router(self) -> Optional[Any]:
        """Read-only access to the PrincipleRouter for self-knowledge reporting."""
        return self._principle_router

    def compute_plan(
        self,
        balance_dollars: float,
        regime: str,
        regime_confidence: float,
        forward_signals: Optional[List[Any]] = None,
        strategy_fitness: Optional[Dict[str, float]] = None,
    ) -> AllocationPlan:
        """
        Compute a new allocation plan based on current state.

        Called every governance cycle (~60s). The plan is the bot's
        strategic thesis for the current market environment.
        """
        phase = detect_phase(balance_dollars)
        phase_key = phase.value

        # Get allocation profile for this phase + regime
        phase_profiles = ALLOCATION_PROFILES.get(phase_key, ALLOCATION_PROFILES["seed"])
        profile = phase_profiles.get(regime, phase_profiles["default"])

        base_weights = dict(profile["strategies"])
        reserve = profile["reserve"]
        thesis = profile["thesis"]
        max_pos = profile["max_pos"]
        scale = profile["scale"]

        # Adjust weights based on regime confidence
        # Low confidence -> shift toward reserve (don't commit on weak signal)
        if regime_confidence < 0.4:
            confidence_penalty = 0.4 - regime_confidence  # 0 to 0.4
            reserve = min(reserve + confidence_penalty * 0.3, 0.80)
            # Scale down all weights proportionally
            reduction = 1 - (confidence_penalty * 0.3)
            base_weights = {k: v * reduction for k, v in base_weights.items()}
            thesis += f" [low-confidence regime ({regime_confidence:.0%}), raised reserve]"

        # Adjust weights based on forward signals
        if forward_signals:
            base_weights, thesis = self._apply_forward_signals(
                base_weights, forward_signals, phase, thesis,
            )

        # Adjust weights based on live strategy fitness
        if strategy_fitness:
            base_weights = self._apply_fitness_adjustment(base_weights, strategy_fitness)

        # Convene council of masters for convergence/divergence confirmation
        if self._principle_router:
            verdict = self._principle_router.convene_council(
                phase=phase_key,
                regime=regime,
                regime_confidence=regime_confidence,
                forward_signals=forward_signals,
                strategy_fitness=strategy_fitness,
            )
            # Apply council adjustments:
            # 1. Sizing bias modulates position scale
            scale *= verdict.position_sizing_bias
            # 2. Reserve adjustment adds to cash reserve
            reserve = min(reserve + verdict.reserve_adjustment, 0.80)
            # 3. Enrich thesis with council wisdom
            thesis += f" | Council: {verdict.signal_label} — {verdict.thesis}"

        # Normalize weights so they don't exceed (1 - reserve)
        total_weight = sum(base_weights.values())
        max_deployable = 1.0 - reserve
        if total_weight > max_deployable:
            factor = max_deployable / total_weight
            base_weights = {k: v * factor for k, v in base_weights.items()}

        # Remove zero-weight strategies
        base_weights = {k: v for k, v in base_weights.items() if v > 0.01}

        plan = AllocationPlan(
            phase=phase,
            regime=regime,
            thesis=thesis,
            weights=base_weights,
            reserve_pct=reserve,
            max_simultaneous=max_pos,
            position_scale=scale,
        )

        # Archive previous plan
        if self._current_plan:
            self._plan_history.append(self._current_plan)

        self._current_plan = plan

        logger.info(
            "Capital Allocator | Phase: %s | Regime: %s | Deployed: %.0f%% | Reserve: %.0f%% | Strategies: %d | Thesis: %s",
            phase.value, regime, plan.deployed_pct * 100, reserve * 100,
            len(base_weights), thesis,
        )

        return plan

    def get_position_weight(self, strategy_name: str) -> float:
        """Get the current allocation weight for a strategy (0.0 if not allocated)."""
        if not self._current_plan:
            return 0.0
        return self._current_plan.weight_for(strategy_name)

    def get_max_positions(self) -> int:
        """Get max simultaneous positions from current plan."""
        if not self._current_plan:
            return 5
        return self._current_plan.max_simultaneous

    def get_position_scale(self) -> float:
        """Get position size multiplier from current plan."""
        if not self._current_plan:
            return 1.0
        return self._current_plan.position_scale

    def _apply_forward_signals(
        self,
        weights: Dict[str, float],
        signals: List[Any],
        phase: CapitalPhase,
        thesis: str,
    ) -> Tuple[Dict[str, float], str]:
        """Adjust weights based on forward signals from prediction markets."""
        for signal in signals:
            signal_type = getattr(signal, "signal_type", None)
            direction = getattr(signal, "direction", None)
            confidence = getattr(signal, "confidence", 0.0)

            if not signal_type or confidence < 0.3:
                continue

            # Rate shift signals (KXFED)
            if signal_type == "RATE_SHIFT":
                if direction == "bearish":
                    # Rate hike coming — boost crisis_alpha, reduce momentum
                    weights["crisis_alpha"] = weights.get("crisis_alpha", 0) + 0.10 * confidence
                    weights["stock_momentum"] = max(weights.get("stock_momentum", 0) - 0.05 * confidence, 0)
                    thesis += f" | Rate shift signal ({direction}, {confidence:.0%})"

            # Growth signals (KXGDP)
            elif signal_type == "GROWTH":
                if direction == "bearish":
                    weights["crisis_alpha"] = weights.get("crisis_alpha", 0) + 0.08 * confidence
                    weights["options_directional"] = weights.get("options_directional", 0) + 0.05 * confidence
                    thesis += f" | Growth warning ({confidence:.0%})"

            # Risk appetite signals (KXBTC/KXETH)
            elif signal_type == "RISK_APPETITE":
                if direction == "bullish":
                    weights["stock_momentum"] = weights.get("stock_momentum", 0) + 0.05 * confidence
                elif direction == "bearish":
                    weights["crisis_alpha"] = weights.get("crisis_alpha", 0) + 0.05 * confidence

        return weights, thesis

    def _apply_fitness_adjustment(
        self,
        weights: Dict[str, float],
        fitness: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Adjust weights based on live strategy fitness scores.

        Strategies with proven fitness get a boost. Strategies with poor
        fitness get reduced. This creates a feedback loop: perform well
        -> get more capital -> compound faster.
        """
        adjusted = {}
        for name, weight in weights.items():
            fit = fitness.get(name, 0.5)  # Default neutral
            # Scale weight by fitness: 0.3x at fitness=0, 1.0x at fitness=0.5, 1.5x at fitness=1.0
            fit_multiplier = 0.3 + (fit * 1.2)
            adjusted[name] = weight * fit_multiplier

        return adjusted

    def get_plan_summary(self) -> str:
        """Human-readable summary for Telegram/Captain's Log."""
        if not self._current_plan:
            return "No allocation plan computed yet."

        plan = self._current_plan
        lines = [
            f"Capital Phase: {plan.phase.value.upper()}",
            f"Market Regime: {plan.regime}",
            f"Thesis: {plan.thesis}",
            "",
            "Allocation:",
        ]

        for name, weight in sorted(plan.weights.items(), key=lambda x: -x[1]):
            bar_len = int(weight * 30)
            bar = "|" * bar_len + "." * (30 - bar_len)
            lines.append(f"  {name:<25s} [{bar}] {weight:.0%}")

        lines.append(f"  {'RESERVE':<25s} [{('|' * int(plan.reserve_pct * 30)):.<30s}] {plan.reserve_pct:.0%}")
        lines.append("")
        lines.append(f"Max positions: {plan.max_simultaneous} | Position scale: {plan.position_scale:.1f}x")
        lines.append(f"Deployed: {plan.deployed_pct:.0%} | Reserve: {plan.reserve_pct:.0%}")

        return "\n".join(lines)
