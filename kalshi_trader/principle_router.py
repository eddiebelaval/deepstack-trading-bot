"""
Principle Router — Dynamic Master Selection for DeepStack

Sits between GovernanceEngine and Capital Allocator. Given the current
regime, capital phase, and forward signals, selects which masters'
principles apply and resolves conflicts.

The synthesis.md has the static matrix. This module makes it runtime.

Conflict Resolution Rules:
  1. Phase trumps regime — at SEED, survival masters override aggressors
  2. Evidence trumps philosophy — data beats opinion (Simons principle)
  3. Caution trumps aggression — avoid stupidity > seek brilliance (Munger)
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MasterRole(Enum):
    """Functional role a master serves in the council."""
    POSITION_SIZER = "position_sizer"
    REGIME_READER = "regime_reader"
    EDGE_FINDER = "edge_finder"
    RISK_MANAGER = "risk_manager"
    SYSTEM_BUILDER = "system_builder"


@dataclass
class MasterDirective:
    """A specific directive from a master for the current context."""
    master: str
    role: MasterRole
    directive: str  # One-line actionable instruction
    weight: float  # 0.0 to 1.0 — how strongly this master's voice applies
    caution_level: float  # 0.0 (aggressive) to 1.0 (maximum caution)


@dataclass
class CouncilVerdict:
    """Output of the Principle Router — the council has spoken."""
    phase: str
    regime: str
    active_masters: List[MasterDirective]
    thesis: str  # Synthesized thesis from active masters
    caution_level: float  # Aggregate caution (0-1)
    position_sizing_bias: float  # <1.0 = more cautious, >1.0 = more aggressive
    reserve_adjustment: float  # Additional reserve % to add (0.0 to 0.3)
    convergence_score: float  # 0.0 = total divergence, 1.0 = total convergence
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def primary_voices(self) -> List[str]:
        """Names of masters with weight > 0.6."""
        return [m.master for m in self.active_masters if m.weight > 0.6]

    @property
    def caution_voices(self) -> List[str]:
        """Masters urging caution (caution_level > 0.7)."""
        return [m.master for m in self.active_masters if m.caution_level > 0.7]

    @property
    def signal_label(self) -> str:
        """Human label for convergence state."""
        if self.convergence_score >= 0.8:
            return "STRONG CONVERGENCE"
        elif self.convergence_score >= 0.6:
            return "CONVERGENCE"
        elif self.convergence_score >= 0.4:
            return "NEUTRAL"
        elif self.convergence_score >= 0.2:
            return "DIVERGENCE"
        else:
            return "STRONG DIVERGENCE"

    def get_summary(self) -> str:
        """Human-readable summary for Captain's Log / Telegram."""
        voices = ", ".join(f"{m.master} ({m.weight:.0%})" for m in self.active_masters[:5])
        return (
            f"Council: {voices} | "
            f"Caution: {self.caution_level:.0%} | "
            f"Sizing bias: {self.position_sizing_bias:.2f}x | "
            f"{self.signal_label} ({self.convergence_score:.0%}) | "
            f"Thesis: {self.thesis}"
        )


# ---------------------------------------------------------------------------
# Master Profiles — what each master brings to the table
# ---------------------------------------------------------------------------

MASTER_PROFILES: Dict[str, Dict] = {
    # Position Sizers
    "thorp": {
        "role": MasterRole.POSITION_SIZER,
        "regimes": {"all": 0.7, "low_vol_calm": 0.9, "mean_reverting": 0.8},
        "phases": {"seed": 0.9, "growth": 0.8, "foundation": 0.7, "compound": 0.9, "dynasty": 0.7},
        "caution_base": 0.6,
        "directive_templates": {
            "seed": "Fractional Kelly only. Ruin probability at low bankrolls is disproportionately high.",
            "growth": "Standard Kelly fractions. Edge is established, let compounding begin.",
            "compound": "Kelly at scale — mathematical inevitability. Let the formula work.",
            "default": "The edge must be quantifiable. If you can't express it as a number, pass.",
        },
    },
    "druckenmiller": {
        "role": MasterRole.POSITION_SIZER,
        "regimes": {"trending_up": 0.9, "trending_down": 0.8, "mean_reverting": 0.5, "high_vol_choppy": 0.4, "low_vol_calm": 0.3},
        "phases": {"seed": 0.5, "growth": 0.8, "foundation": 0.7, "compound": 0.5, "dynasty": 0.3},
        "caution_base": 0.2,
        "directive_templates": {
            "trending_up": "Go for the jugular. Thesis confirmed, asymmetry clear — deploy.",
            "trending_down": "Short aggressively if thesis is confirmed. First loss is the best loss.",
            "seed": "Preservation of capital enables future aggression. Take ONLY asymmetric bets.",
            "default": "Seek asymmetric risk/reward. Risk $1 to make $5. If you can't define the asymmetry, pass.",
        },
    },
    "buffett": {
        "role": MasterRole.POSITION_SIZER,
        "regimes": {"low_vol_calm": 0.9, "mean_reverting": 0.8, "trending_up": 0.4, "high_vol_choppy": 0.3, "trending_down": 0.5},
        "phases": {"seed": 0.9, "growth": 0.7, "foundation": 0.8, "compound": 0.9, "dynasty": 0.9},
        "caution_base": 0.7,
        "directive_templates": {
            "seed": "Rule #1: Don't lose money. Only fat pitches with enormous margin of safety.",
            "low_vol_calm": "Patience rewarded. Wait for fat pitches. Time is the friend of the wonderful trade.",
            "mean_reverting": "Buy the dip. Margin of safety on reversion plays.",
            "default": "20-slot punch card thinking. Only take the BEST trades. Say no to 99%.",
        },
    },
    # Regime Readers
    "dalio": {
        "role": MasterRole.REGIME_READER,
        "regimes": {"all": 0.6, "mean_reverting": 0.7, "low_vol_calm": 0.7},
        "phases": {"seed": 0.3, "growth": 0.7, "foundation": 0.9, "compound": 0.8, "dynasty": 0.9},
        "caution_base": 0.5,
        "directive_templates": {
            "seed": "Can't diversify with $159. Accept concentration risk on proven edge.",
            "growth": "Begin diversifying across uncorrelated strategies. Risk-parity sizing.",
            "foundation": "Full all-weather deployment. Multiple strategies, inverse-volatility sized.",
            "default": "Balance risk across uncorrelated bets. Know where you are in the debt cycle.",
        },
    },
    "marks": {
        "role": MasterRole.REGIME_READER,
        "regimes": {"high_vol_choppy": 0.9, "trending_down": 0.8, "low_vol_calm": 0.7, "trending_up": 0.6, "mean_reverting": 0.5},
        "phases": {"seed": 0.6, "growth": 0.7, "foundation": 0.9, "compound": 0.8, "dynasty": 0.9},
        "caution_base": 0.7,
        "directive_templates": {
            "low_vol_calm": "Perversity of risk — calm = highest hidden risk. Don't get complacent.",
            "trending_up": "Which stage of the bull? Stage 3 = euphoria = sell zone.",
            "trending_down": "Which stage of the bear? Stage 3 = despair = buy zone.",
            "high_vol_choppy": "The pendulum is swinging. Know the direction before positioning.",
            "default": "Second-level thinking. What does the crowd believe, and why are they wrong?",
        },
    },
    "templeton": {
        "role": MasterRole.REGIME_READER,
        "regimes": {"trending_down": 0.9, "low_vol_calm": 0.6, "mean_reverting": 0.5, "trending_up": 0.4, "high_vol_choppy": 0.4},
        "phases": {"seed": 0.7, "growth": 0.6, "foundation": 0.8, "compound": 0.7, "dynasty": 0.9},
        "caution_base": 0.6,
        "directive_templates": {
            "trending_down": "Maximum pessimism territory. This IS the buy zone.",
            "trending_up": "Optimism maturing? Watch for euphoria signals. Prepare to reduce.",
            "default": "Don't interrupt compounding. Patience measured in years, not hours.",
        },
    },
    # Edge Finders
    "simons": {
        "role": MasterRole.EDGE_FINDER,
        "regimes": {"all": 0.7, "low_vol_calm": 0.8, "mean_reverting": 0.8},
        "phases": {"seed": 0.5, "growth": 0.7, "foundation": 0.8, "compound": 0.9, "dynasty": 0.8},
        "caution_base": 0.5,
        "directive_templates": {
            "seed": "Insufficient capital for many small bets. Focus on the single best pattern.",
            "compound": "Law of large numbers territory. Many small bets across strategies.",
            "default": "Signal in the noise. Sample size is sacred. No stories, only data.",
        },
    },
    "burry": {
        "role": MasterRole.EDGE_FINDER,
        "regimes": {"high_vol_choppy": 0.9, "trending_down": 0.8, "mean_reverting": 0.5, "trending_up": 0.2, "low_vol_calm": 0.2},
        "phases": {"seed": 0.4, "growth": 0.6, "foundation": 0.8, "compound": 0.7, "dynasty": 0.6},
        "caution_base": 0.5,
        "directive_templates": {
            "high_vol_choppy": "Structural breaks create dislocations. Read the fine print.",
            "trending_down": "Contrarian with evidence. The crowd hasn't done the math.",
            "seed": "Can't afford carry cost of being early. Only short time-to-settlement trades.",
            "default": "Read the primary sources — settlement rules, data methodology, contract specs.",
        },
    },
    "gill": {
        "role": MasterRole.EDGE_FINDER,
        "regimes": {"mean_reverting": 0.8, "trending_down": 0.7, "low_vol_calm": 0.4, "trending_up": 0.3, "high_vol_choppy": 0.3},
        "phases": {"seed": 0.7, "growth": 0.8, "foundation": 0.5, "compound": 0.4, "dynasty": 0.3},
        "caution_base": 0.3,
        "directive_templates": {
            "mean_reverting": "Deep fundamental analysis on reversion plays. Asymmetric conviction.",
            "trending_down": "Has the thesis changed? If no, hold. If yes, cut immediately.",
            "default": "Simple thesis, deep conviction. Do the homework nobody else does.",
        },
    },
    "cohen": {
        "role": MasterRole.EDGE_FINDER,
        "regimes": {"mean_reverting": 0.7, "trending_down": 0.6, "low_vol_calm": 0.6, "trending_up": 0.3, "high_vol_choppy": 0.3},
        "phases": {"seed": 0.6, "growth": 0.7, "foundation": 0.8, "compound": 0.6, "dynasty": 0.5},
        "caution_base": 0.5,
        "directive_templates": {
            "mean_reverting": "Turnaround conditions. Fix what's broken, not what's working.",
            "default": "Lean operations. Cut what doesn't work. Double down on what does.",
        },
    },
    # Risk Managers
    "taleb": {
        "role": MasterRole.RISK_MANAGER,
        "regimes": {"high_vol_choppy": 0.9, "trending_down": 0.8, "low_vol_calm": 0.6, "trending_up": 0.4, "mean_reverting": 0.4},
        "phases": {"seed": 0.8, "growth": 0.6, "foundation": 0.8, "compound": 0.9, "dynasty": 1.0},
        "caution_base": 0.7,
        "directive_templates": {
            "high_vol_choppy": "Antifragile strategies profit FROM chaos. Deploy crisis_alpha.",
            "low_vol_calm": "Buy cheap protection NOW. Calm is when insurance is cheapest.",
            "seed": "Maximum fragility. Run ONLY robust strategies. No fragile plays.",
            "dynasty": "The goal is to never go back to being poor. Maximum antifragility.",
            "default": "Via negativa — improve by removing fragilities, not adding features.",
        },
    },
    "livermore": {
        "role": MasterRole.RISK_MANAGER,
        "regimes": {"trending_up": 0.9, "trending_down": 0.8, "low_vol_calm": 0.7, "high_vol_choppy": 0.2, "mean_reverting": 0.3},
        "phases": {"seed": 0.9, "growth": 0.7, "foundation": 0.6, "compound": 0.7, "dynasty": 0.9},
        "caution_base": 0.6,
        "directive_templates": {
            "trending_up": "Pyramid into winners. The line of least resistance is clear.",
            "trending_down": "Line of least resistance is down. Don't fight it — or sit out.",
            "high_vol_choppy": "Go fishing. No clear direction. Trading here is gambling.",
            "low_vol_calm": "Patience rewarded. Wait for the setup. The big money is in the sitting.",
            "seed": "Protect capital above all. Livermore went bankrupt sizing too big too early.",
            "default": "The market is never wrong, opinions are. Sit tight until the setup is undeniable.",
        },
    },
    "soros": {
        "role": MasterRole.RISK_MANAGER,
        "regimes": {"trending_up": 0.8, "trending_down": 0.8, "high_vol_choppy": 0.9, "mean_reverting": 0.3, "low_vol_calm": 0.2},
        "phases": {"seed": 0.6, "growth": 0.8, "foundation": 0.7, "compound": 0.8, "dynasty": 0.7},
        "caution_base": 0.4,
        "directive_templates": {
            "trending_up": "Reflexive boom — how far from equilibrium? Ride but watch for the bust.",
            "trending_down": "Reflexive bust — correction can be violent. Size for the snap-back.",
            "high_vol_choppy": "Far-from-equilibrium. The correction will be violent. Position accordingly.",
            "default": "Test thesis with a probe. If confirmed, scale. If disconfirmed, cut immediately.",
        },
    },
    # System Builders
    "musk": {
        "role": MasterRole.SYSTEM_BUILDER,
        "regimes": {"all": 0.5},
        "phases": {"seed": 0.5, "growth": 0.7, "foundation": 0.6, "compound": 0.8, "dynasty": 0.6},
        "caution_base": 0.3,
        "directive_templates": {
            "default": "First principles. What's the fundamental edge mechanism? Build the factory.",
        },
    },
    "jobs": {
        "role": MasterRole.SYSTEM_BUILDER,
        "regimes": {"low_vol_calm": 0.8, "mean_reverting": 0.6, "all": 0.4},
        "phases": {"seed": 0.9, "growth": 0.6, "foundation": 0.7, "compound": 0.6, "dynasty": 0.8},
        "caution_base": 0.7,
        "directive_templates": {
            "seed": "Focus. Two strategies max. Kill everything that isn't excellent.",
            "dynasty": "Say no to the hundred other good ideas. Small and excellent beats large and adequate.",
            "default": "Simplicity. Focus. Is this adding value or adding complexity?",
        },
    },
    "icahn": {
        "role": MasterRole.SYSTEM_BUILDER,
        "regimes": {"high_vol_choppy": 0.9, "trending_down": 0.8, "mean_reverting": 0.4, "trending_up": 0.2, "low_vol_calm": 0.2},
        "phases": {"seed": 0.3, "growth": 0.5, "foundation": 0.8, "compound": 0.6, "dynasty": 0.5},
        "caution_base": 0.3,
        "directive_templates": {
            "high_vol_choppy": "Forced selling creates dislocations. Be the buyer of last resort.",
            "trending_down": "Buy the blood. The last seller at the bottom is your best counterparty.",
            "seed": "Can't be activist with $159. Watch for forced selling micro-patterns.",
            "default": "Buy the hated. Consensus comfort = no edge.",
        },
    },
}


class PrincipleRouter:
    """
    Dynamically selects which masters' principles apply to the current
    market context. Resolves conflicts and outputs a CouncilVerdict.

    Called by Capital Allocator after governance detects regime.
    """

    def __init__(self):
        self._last_verdict: Optional[CouncilVerdict] = None
        self._verdict_history: Deque[CouncilVerdict] = deque(maxlen=50)
        self._last_context: Optional[Tuple[str, str, float]] = None

    @property
    def last_verdict(self) -> Optional[CouncilVerdict]:
        return self._last_verdict

    def convene_council(
        self,
        phase: str,
        regime: str,
        regime_confidence: float,
        forward_signals: Optional[List] = None,
        strategy_fitness: Optional[Dict[str, float]] = None,
    ) -> CouncilVerdict:
        """
        Convene the council of masters for the current context.

        Returns a CouncilVerdict with active masters, thesis, and adjustments.
        Skips recomputation if context (phase, regime, confidence) is unchanged.
        """
        # Convergence guard: skip if context unchanged
        context = (phase, regime, round(regime_confidence, 2))
        if self._last_verdict and self._last_context == context:
            return self._last_verdict

        # Score each master for this context
        scored: List[Tuple[str, float, float]] = []  # (name, relevance, caution)

        for name, profile in MASTER_PROFILES.items():
            relevance = self._score_master(name, profile, phase, regime, regime_confidence)
            caution = profile["caution_base"]

            # Phase-based caution override (Rule 1: phase trumps regime)
            if phase == "seed":
                caution = max(caution, 0.6)  # Minimum caution at SEED
            elif phase == "dynasty":
                caution = max(caution, 0.5)  # Minimum caution at DYNASTY

            scored.append((name, relevance, caution))

        # Sort by relevance, take top voices
        scored.sort(key=lambda x: x[1], reverse=True)

        # Select active masters: ensure role diversity
        active_masters: List[MasterDirective] = []
        roles_filled: Dict[MasterRole, int] = {}

        for name, relevance, caution in scored:
            if relevance < 0.3:
                continue

            profile = MASTER_PROFILES[name]
            role = profile["role"]

            # Cap at 2 masters per role for diversity
            if roles_filled.get(role, 0) >= 2:
                continue

            # Get contextual directive
            templates = profile["directive_templates"]
            directive = (
                templates.get(phase)
                or templates.get(regime)
                or templates.get("default", "No specific directive.")
            )

            active_masters.append(MasterDirective(
                master=name,
                role=role,
                directive=directive,
                weight=min(relevance, 1.0),
                caution_level=caution,
            ))
            roles_filled[role] = roles_filled.get(role, 0) + 1

            if len(active_masters) >= 7:
                break

        # Resolve conflicts and synthesize
        convergence = self._compute_convergence(active_masters)
        caution_level = self._compute_aggregate_caution(active_masters, phase, regime_confidence)
        sizing_bias = self._compute_sizing_bias(active_masters, phase, regime_confidence, convergence)
        reserve_adj = self._compute_reserve_adjustment(caution_level, regime_confidence, convergence)
        thesis = self._synthesize_thesis(active_masters, phase, regime)

        verdict = CouncilVerdict(
            phase=phase,
            regime=regime,
            active_masters=active_masters,
            thesis=thesis,
            caution_level=caution_level,
            position_sizing_bias=sizing_bias,
            reserve_adjustment=reserve_adj,
            convergence_score=convergence,
        )

        # Archive
        if self._last_verdict:
            self._verdict_history.append(self._last_verdict)
        self._last_verdict = verdict
        self._last_context = context

        logger.info(
            "Council convened | Phase: %s | Regime: %s | Voices: %s | Caution: %.0f%% | Sizing: %.2fx | %s (%.0f%%) | Thesis: %s",
            phase, regime,
            ", ".join(v.master for v in active_masters[:4]),
            caution_level * 100,
            sizing_bias,
            verdict.signal_label,
            convergence * 100,
            thesis[:80],
        )

        return verdict

    def _score_master(
        self,
        name: str,
        profile: Dict,
        phase: str,
        regime: str,
        regime_confidence: float,
    ) -> float:
        """Score a master's relevance for the current context (0.0 to 1.0)."""
        # Regime fit
        regime_scores = profile.get("regimes", {})
        regime_fit = regime_scores.get(regime, regime_scores.get("all", 0.3))

        # Phase fit
        phase_scores = profile.get("phases", {})
        phase_fit = phase_scores.get(phase, 0.5)

        # Weighted blend: phase 60%, regime 40% (phase trumps regime)
        raw_score = (phase_fit * 0.6) + (regime_fit * 0.4)

        # Low regime confidence boosts cautious masters, penalizes aggressive ones
        if regime_confidence < 0.4:
            caution = profile.get("caution_base", 0.5)
            if caution > 0.5:
                raw_score *= 1.2  # Cautious masters get a boost in uncertainty
            else:
                raw_score *= 0.8  # Aggressive masters get penalized

        return min(raw_score, 1.0)

    def _compute_convergence(self, masters: List[MasterDirective]) -> float:
        """
        Compute convergence score from council agreement.

        Same shape as every other confirmation signal in DeepStack:
        convergence = masters agree → high conviction.
        divergence = masters disagree → uncertainty, reduce exposure.

        Measured by inverse standard deviation of caution levels.
        Low spread = convergence (score → 1.0).
        High spread = divergence (score → 0.0).
        """
        if len(masters) < 2:
            return 0.5  # Not enough voices to measure agreement

        cautions = [m.caution_level for m in masters]
        mean = sum(cautions) / len(cautions)
        variance = sum((c - mean) ** 2 for c in cautions) / len(cautions)
        std_dev = variance ** 0.5

        # Map std_dev to convergence score:
        # std_dev=0 → perfect agreement → convergence=1.0
        # std_dev=0.3+ → strong disagreement → convergence=0.0
        # Linear mapping between 0 and 0.3
        convergence = max(0.0, 1.0 - (std_dev / 0.3))
        return min(convergence, 1.0)

    def _compute_aggregate_caution(
        self,
        masters: List[MasterDirective],
        phase: str,
        regime_confidence: float,
    ) -> float:
        """Compute aggregate caution level. Rule 3: caution trumps aggression."""
        if not masters:
            return 0.5

        # Weighted average of caution levels by master weight
        total_weight = sum(m.weight for m in masters)
        if total_weight == 0:
            return 0.5

        weighted_caution = sum(m.caution_level * m.weight for m in masters) / total_weight

        # Phase floor: SEED and DYNASTY have minimum caution
        phase_floors = {"seed": 0.6, "dynasty": 0.5, "compound": 0.4}
        floor = phase_floors.get(phase, 0.3)
        weighted_caution = max(weighted_caution, floor)

        # Low regime confidence raises caution
        if regime_confidence < 0.4:
            confidence_penalty = 0.4 - regime_confidence
            weighted_caution = min(weighted_caution + confidence_penalty * 0.3, 0.9)

        return weighted_caution

    def _compute_sizing_bias(
        self,
        masters: List[MasterDirective],
        phase: str,
        regime_confidence: float,
        convergence: float = 0.5,
    ) -> float:
        """
        Compute position sizing bias.

        < 1.0 = more cautious than default (reduce position sizes)
        = 1.0 = default sizing
        > 1.0 = more aggressive (increase position sizes, capped at 1.3)

        Convergence amplifies: high convergence boosts bias toward its
        natural direction. Divergence dampens toward 1.0 (neutral).
        """
        if not masters:
            return 1.0

        # Start at 1.0 (neutral)
        bias = 1.0

        # Aggressive masters push up, cautious masters push down
        for m in masters:
            if m.caution_level < 0.3:
                bias += 0.05 * m.weight  # Druckenmiller, Gill push sizing up
            elif m.caution_level > 0.7:
                bias -= 0.05 * m.weight  # Buffett, Taleb, Marks push sizing down

        # Convergence/divergence confirmation:
        # High convergence (>0.7) amplifies the bias direction by up to 10%
        # Low convergence (<0.3) dampens toward neutral by up to 15%
        if convergence >= 0.7:
            amplify = 1.0 + (convergence - 0.7) * 0.33  # Up to ~1.10x at convergence=1.0
            bias = 1.0 + (bias - 1.0) * amplify
        elif convergence < 0.3:
            dampen = 0.5 + convergence * 1.67  # 0.5x at conv=0, 1.0x at conv=0.3
            bias = 1.0 + (bias - 1.0) * dampen

        # Phase constraints
        phase_caps = {"seed": 0.9, "dynasty": 0.95, "growth": 1.15, "compound": 1.1}
        cap = phase_caps.get(phase, 1.2)
        bias = min(bias, cap)
        bias = max(bias, 0.5)  # Never less than 50% of default

        # Low confidence reduces further
        if regime_confidence < 0.4:
            bias *= 0.85

        return bias

    def _compute_reserve_adjustment(
        self, caution_level: float, regime_confidence: float, convergence: float = 0.5,
    ) -> float:
        """Compute additional reserve % to add based on caution, confidence, and convergence."""
        # Higher caution = higher reserve
        base_adj = max(0, (caution_level - 0.5) * 0.3)

        # Low confidence adds more reserve
        if regime_confidence < 0.4:
            base_adj += 0.1

        # Divergence adds reserve (council disagrees = uncertainty = hold cash)
        if convergence < 0.3:
            base_adj += 0.08  # Divergent council → extra 8% reserve
        elif convergence >= 0.8:
            base_adj = max(0, base_adj - 0.05)  # Strong convergence → reduce reserve slightly

        return min(base_adj, 0.3)  # Cap at 30% additional reserve

    def _synthesize_thesis(self, masters: List[MasterDirective], phase: str, regime: str) -> str:
        """Synthesize a thesis from the active masters' directives."""
        if not masters:
            return f"{phase.upper()} phase, {regime} regime — no council available."

        # Masters are already sorted by relevance (weight) from convene_council
        top = masters[:3]
        parts = []
        for m in top:
            # Shorten directive for thesis
            short = m.directive.split(".")[0] if "." in m.directive else m.directive
            parts.append(f"{m.master}: {short}")

        return " | ".join(parts)

    def get_verdict_summary(self) -> str:
        """Human-readable summary for Telegram / Captain's Log."""
        if not self._last_verdict:
            return "No council verdict yet."
        return self._last_verdict.get_summary()
