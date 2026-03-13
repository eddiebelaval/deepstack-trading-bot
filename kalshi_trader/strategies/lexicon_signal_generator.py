"""
Lexicon Signal Generator — Knowledge-to-Action Bridge for DeepStack

Reads current market regime + lexicon playbooks + arsenal indicators
and generates actionable strategy recommendations (enable/disable/caution).

Architecture:
    GovernanceEngine.current_regime
        -> LexiconSignalGenerator.generate_signals()
            1. Load regime playbook via consciousness.load_lexicon_for_regime()
            2. Load arsenal via consciousness.load_lexicon_topic("arsenal")
            3. Parse playbook -> extract Enable/Disable/Caution lists
            4. Cross-reference arsenal indicators -> boost confidence
            5. Apply contrarian bias from Eddie's playbook
        -> List[LexiconSignal]

Advisory mode: log signals + Telegram digest
Autonomous mode: GovernanceEngine applies signals via strategy_manager.enable/disable_strategy()

Does NOT replace StrategyRouter. StrategyRouter uses Bayesian priors from
observed trade outcomes. LexiconSignalGenerator provides a knowledge-based
overlay. Both inform, neither auto-executes in advisory mode.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .. import consciousness

logger = logging.getLogger(__name__)


@dataclass
class LexiconSignal:
    """A strategy recommendation derived from lexicon knowledge."""

    strategy_name: str
    action: str  # "enable", "disable", "caution"
    confidence: float  # 0.0 - 1.0
    reasoning: str  # Human-readable, for Telegram/logs
    titan_alignment: List[str] = field(default_factory=list)
    arsenal_support: List[str] = field(default_factory=list)
    regime: str = ""  # MarketRegime value that triggered this signal

    def __repr__(self) -> str:
        return (
            f"LexiconSignal({self.strategy_name}: {self.action} "
            f"conf={self.confidence:.2f} titans={len(self.titan_alignment)} "
            f"arsenal={len(self.arsenal_support)})"
        )


class LexiconSignalGenerator:
    """
    Generates strategy recommendations from lexicon knowledge.

    Parses regime playbook markdown to extract Enable/Disable/Caution lists,
    cross-references with arsenal indicators, and produces confidence-scored
    signals. Implements regime-change cache invalidation to avoid redundant
    re-parsing when the regime is stable.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the signal generator.

        Args:
            config: lexicon_signals section from config.yaml.
                Keys: enabled, mode, confidence_threshold,
                      telegram_digest, digest_interval_hours
        """
        self.enabled = config.get("enabled", True)
        self.mode = config.get("mode", "advisory")
        self.confidence_threshold = config.get("confidence_threshold", 0.6)
        self.telegram_digest = config.get("telegram_digest", True)
        self.digest_interval_hours = config.get("digest_interval_hours", 6)

        # Cache: avoid re-parsing if regime hasn't changed
        self._last_regime: Optional[str] = None
        self._last_signals: List[LexiconSignal] = []
        self._last_arsenal_mtime: float = 0
        self._last_digest_time: float = 0

        logger.info(
            "LexiconSignalGenerator initialized | mode=%s threshold=%.2f",
            self.mode, self.confidence_threshold,
        )

    def generate_signals(
        self,
        regime_value: str,
        active_strategies: Optional[List[str]] = None,
    ) -> List[LexiconSignal]:
        """
        Generate strategy signals for the current regime.

        Returns cached signals if regime hasn't changed and arsenal data
        is still fresh. Otherwise parses playbook and regenerates.

        Args:
            regime_value: MarketRegime value string (e.g., "trending_up")
            active_strategies: List of strategy names from config.yaml
                to filter signals. If None, returns all parsed signals.

        Returns:
            List of LexiconSignal objects, filtered by confidence threshold.
        """
        if not self.enabled:
            return []

        # Check cache: same regime + arsenal hasn't changed
        arsenal_changed = self._check_arsenal_freshness()
        if regime_value == self._last_regime and not arsenal_changed:
            return self._last_signals

        logger.info(
            "LexiconSignalGenerator: generating signals for regime=%s "
            "(previous=%s, arsenal_changed=%s)",
            regime_value, self._last_regime, arsenal_changed,
        )

        # Load regime playbook (includes tv-regime-map.md)
        playbook_text = consciousness.load_lexicon_for_regime(regime_value)
        if not playbook_text:
            logger.warning(
                "LexiconSignalGenerator: no playbook for regime '%s'",
                regime_value,
            )
            return []

        # Load arsenal data
        arsenal_text = consciousness.load_lexicon_topic("arsenal")

        # Parse playbook for strategy recommendations
        enable_list, disable_list, caution_list = self._parse_strategy_recommendations(
            playbook_text
        )

        # Parse titan alignment from playbook
        titan_map = self._parse_titan_alignment(playbook_text)

        # Parse arsenal indicators by category
        arsenal_by_category = self._parse_arsenal_categories(arsenal_text)

        # Build signals
        signals: List[LexiconSignal] = []

        for strategy_name in enable_list:
            if active_strategies and strategy_name not in active_strategies:
                continue
            supporting = self._get_supporting_indicators(
                strategy_name, arsenal_by_category, regime_value,
            )
            confidence = self._calculate_confidence(
                action="enable",
                strategy_name=strategy_name,
                titan_map=titan_map,
                arsenal_by_category=arsenal_by_category,
                regime_value=regime_value,
                supporting_indicators=supporting,
            )
            if confidence >= self.confidence_threshold:
                signals.append(LexiconSignal(
                    strategy_name=strategy_name,
                    action="enable",
                    confidence=confidence,
                    reasoning=self._build_reasoning(
                        strategy_name, "enable", regime_value,
                        titan_map, arsenal_by_category,
                    ),
                    titan_alignment=titan_map.get("primary", []) + titan_map.get("secondary", []),
                    arsenal_support=supporting,
                    regime=regime_value,
                ))

        for strategy_name in disable_list:
            if active_strategies and strategy_name not in active_strategies:
                continue
            signals.append(LexiconSignal(
                strategy_name=strategy_name,
                action="disable",
                confidence=0.8,  # Disable signals get high confidence — safety first
                reasoning=self._build_reasoning(
                    strategy_name, "disable", regime_value,
                    titan_map, arsenal_by_category,
                ),
                titan_alignment=titan_map.get("avoid", []),
                arsenal_support=[],
                regime=regime_value,
            ))

        for strategy_name in caution_list:
            if active_strategies and strategy_name not in active_strategies:
                continue
            signals.append(LexiconSignal(
                strategy_name=strategy_name,
                action="caution",
                confidence=0.5,
                reasoning=self._build_reasoning(
                    strategy_name, "caution", regime_value,
                    titan_map, arsenal_by_category,
                ),
                titan_alignment=[],
                arsenal_support=[],
                regime=regime_value,
            ))

        # Update cache
        self._last_regime = regime_value
        self._last_signals = signals

        logger.info(
            "LexiconSignalGenerator: %d signals (enable=%d, disable=%d, caution=%d)",
            len(signals),
            sum(1 for s in signals if s.action == "enable"),
            sum(1 for s in signals if s.action == "disable"),
            sum(1 for s in signals if s.action == "caution"),
        )

        return signals

    def format_digest(self, signals: List[LexiconSignal], regime_value: str) -> str:
        """
        Format signals as a Telegram-friendly digest.

        Args:
            signals: List of LexiconSignal objects to format.
            regime_value: Current regime for the header.

        Returns:
            Formatted string for Telegram.
        """
        if not signals:
            return f"[Lexicon Signals] Regime: {regime_value}\nNo actionable signals."

        lines = [f"[Lexicon Signals] Regime: {regime_value}", ""]

        for action in ("enable", "disable", "caution"):
            action_signals = [s for s in signals if s.action == action]
            if not action_signals:
                continue
            label = {"enable": "ENABLE", "disable": "DISABLE", "caution": "CAUTION"}[action]
            lines.append(f"{label}:")
            for sig in action_signals:
                titans = ", ".join(sig.titan_alignment[:3]) if sig.titan_alignment else "none"
                arsenal = f" | arsenal: {len(sig.arsenal_support)}" if sig.arsenal_support else ""
                lines.append(
                    f"  {sig.strategy_name} (conf: {sig.confidence:.0%}) "
                    f"— titans: {titans}{arsenal}"
                )
            lines.append("")

        return "\n".join(lines).strip()

    def should_send_digest(self) -> bool:
        """Check if enough time has passed since last Telegram digest."""
        if not self.telegram_digest:
            return False
        elapsed_hours = (time.time() - self._last_digest_time) / 3600
        return elapsed_hours >= self.digest_interval_hours

    def mark_digest_sent(self) -> None:
        """Mark that a Telegram digest was just sent."""
        self._last_digest_time = time.time()

    # ── Parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_strategy_recommendations(
        playbook_text: str,
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Parse Enable/Disable/Caution strategy lists from playbook markdown.

        Expected format in playbook:
            - **Enable:** `strategy_a` -- reasoning. `strategy_b` -- reasoning.
            - **Disable:** `strategy_c` -- reasoning.
            - **Caution:** `strategy_d` -- reasoning.

        Returns:
            Tuple of (enable_list, disable_list, caution_list) with strategy names.
        """
        enable_list: List[str] = []
        disable_list: List[str] = []
        caution_list: List[str] = []

        # Find the Strategy Recommendations section
        section_match = re.search(
            r"## Strategy Recommendations\s*\n(.*?)(?=\n## |\Z)",
            playbook_text,
            re.DOTALL,
        )
        if not section_match:
            return enable_list, disable_list, caution_list

        section = section_match.group(1)

        # Parse each action line — look for **Enable:**, **Disable:**, **Caution:**
        for line in section.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Determine which list this line belongs to
            target_list = None
            if re.search(r"\*\*Enable:?\*\*", line_stripped, re.IGNORECASE):
                target_list = enable_list
            elif re.search(r"\*\*Disable:?\*\*", line_stripped, re.IGNORECASE):
                target_list = disable_list
            elif re.search(r"\*\*Caution:?\*\*", line_stripped, re.IGNORECASE):
                target_list = caution_list

            if target_list is None:
                continue

            # Extract backtick-quoted strategy names from this line
            strategies = re.findall(r"`([^`]+)`", line_stripped)
            target_list.extend(strategies)

        return enable_list, disable_list, caution_list

    @staticmethod
    def _parse_titan_alignment(
        playbook_text: str,
    ) -> Dict[str, List[str]]:
        """
        Parse Titan Alignment section from playbook markdown.

        Expected format:
            - **Primary:** Musk, Jobs (...), Dalio (...)
            - **Secondary:** Burry (...)
            - **Avoid:** Buffett (...), Icahn (...)

        Returns:
            Dict with keys "primary", "secondary", "avoid",
            each mapping to a list of titan names.
        """
        result: Dict[str, List[str]] = {
            "primary": [],
            "secondary": [],
            "avoid": [],
        }

        section_match = re.search(
            r"## Titan Alignment\s*\n(.*?)(?=\n## |\Z)",
            playbook_text,
            re.DOTALL,
        )
        if not section_match:
            return result

        section = section_match.group(1)

        for line in section.splitlines():
            line_stripped = line.strip()
            for key in ("primary", "secondary", "avoid"):
                pattern = rf"\*\*{key.capitalize()}:?\*\*\s*(.*)"
                match = re.search(pattern, line_stripped, re.IGNORECASE)
                if match:
                    # Extract titan names — they appear before parenthetical explanations
                    # Format: "Icahn (buy the panic, ...), Burry (structural breaks...)"
                    # We need to split on commas that are NOT inside parentheses
                    raw = match.group(1)
                    # Remove parenthetical content first, then split
                    cleaned = re.sub(r"\([^)]*\)", "", raw)
                    for part in cleaned.split(","):
                        part = part.strip().lstrip("- ")
                        if part:
                            result[key].append(part)

        return result

    @staticmethod
    def _parse_arsenal_categories(
        arsenal_text: str,
    ) -> Dict[str, List[str]]:
        """
        Parse arsenal top performers into a category -> indicator names map.

        Reads the markdown table in tv-top-performers.md.

        Returns:
            Dict mapping category name to list of indicator names.
        """
        categories: Dict[str, List[str]] = {}
        if not arsenal_text:
            return categories

        # Parse markdown table rows: | Rank | Name | Composite | ... | Category |
        for line in arsenal_text.splitlines():
            line = line.strip()
            if not line.startswith("|") or line.startswith("|--") or line.startswith("| Rank"):
                continue

            cells = [c.strip() for c in line.split("|")]
            # cells[0] is empty (before first |), cells[-1] is empty (after last |)
            cells = [c for c in cells if c]

            if len(cells) >= 7:
                # Table format: Rank, Name, Composite, Avg Sharpe, Avg Return %, Tickers, Category
                name = cells[1]
                category = cells[6].lower()
                if name and name != "Awaiting population" and category:
                    categories.setdefault(category, []).append(name)

        return categories

    def _calculate_confidence(
        self,
        action: str,
        strategy_name: str,
        titan_map: Dict[str, List[str]],
        arsenal_by_category: Dict[str, List[str]],
        regime_value: str,
        supporting_indicators: Optional[List[str]] = None,
    ) -> float:
        """
        Calculate confidence score for an enable signal.

        Base: 0.6 (playbook recommends it)
        +0.1 per supporting arsenal indicator (capped at +0.2)
        +0.05 per aligned titan (capped at +0.1)
        Max: 0.9

        Args:
            action: Signal action type.
            strategy_name: Strategy being evaluated.
            titan_map: Parsed titan alignment from playbook.
            arsenal_by_category: Parsed arsenal indicator categories.
            regime_value: Current regime.
            supporting_indicators: Precomputed supporting indicators (avoids re-lookup).

        Returns:
            Confidence score between 0.0 and 0.9.
        """
        if action != "enable":
            return 0.8 if action == "disable" else 0.5

        base = 0.6

        # Arsenal boost: count indicators supporting this strategy in this regime
        if supporting_indicators is None:
            supporting_indicators = self._get_supporting_indicators(
                strategy_name, arsenal_by_category, regime_value
            )
        arsenal_boost = min(len(supporting_indicators) * 0.1, 0.2)

        # Titan boost: count primary + secondary titans
        titan_count = len(titan_map.get("primary", [])) + len(titan_map.get("secondary", []))
        titan_boost = min(titan_count * 0.05, 0.1)

        confidence = min(base + arsenal_boost + titan_boost, 0.9)
        return round(confidence, 2)

    @staticmethod
    def _get_supporting_indicators(
        strategy_name: str,
        arsenal_by_category: Dict[str, List[str]],
        regime_value: str,
    ) -> List[str]:
        """
        Find arsenal indicators that support a given strategy in a regime.

        Maps strategy names to relevant indicator categories, then returns
        indicator names from those categories.
        """
        # Strategy -> relevant indicator categories
        strategy_category_map: Dict[str, List[str]] = {
            "momentum": ["momentum", "trend", "breakout"],
            "calibration_edge": ["volume", "sentiment", "oscillator"],
            "mean_reversion": ["mean reversion", "oscillator"],
            "news_sentiment_fade": ["sentiment", "volatility"],
            "correlated_event_arbitrage": ["volume", "sentiment"],
            "high_probability_bonds": ["volatility", "volume"],
            "crypto_intraday": ["momentum", "volatility", "breakout"],
            "bear_macro": ["trend", "momentum"],
            "weather_aggregation": ["sentiment"],
            "domain_specialization": ["momentum", "mean reversion"],
            "tv_signals": ["momentum", "trend", "oscillator", "volatility"],
        }

        relevant_categories = strategy_category_map.get(strategy_name, [])
        supporting: List[str] = []

        for cat in relevant_categories:
            supporting.extend(arsenal_by_category.get(cat, []))

        return supporting[:5]  # Cap at 5 for readability

    @staticmethod
    def _build_reasoning(
        strategy_name: str,
        action: str,
        regime_value: str,
        titan_map: Dict[str, List[str]],
        arsenal_by_category: Dict[str, List[str]],
    ) -> str:
        """Build human-readable reasoning string for a signal."""
        regime_display = regime_value.replace("_", " ").title()

        if action == "enable":
            titans = titan_map.get("primary", [])[:2]
            titan_str = f" Aligned: {', '.join(titans)}." if titans else ""
            return f"Regime playbook recommends {strategy_name} in {regime_display}.{titan_str}"

        elif action == "disable":
            avoid = titan_map.get("avoid", [])[:2]
            avoid_str = f" Counter-aligned: {', '.join(avoid)}." if avoid else ""
            return f"Regime playbook disables {strategy_name} in {regime_display}.{avoid_str}"

        else:  # caution
            return f"Caution on {strategy_name} in {regime_display} — review parameters before use."

    def _check_arsenal_freshness(self) -> bool:
        """
        Check if arsenal file has been modified since last signal generation.

        Returns True if arsenal data changed (cache should be invalidated).
        """
        from pathlib import Path

        arsenal_path = (
            Path(__file__).parent.parent / "mind" / "lexicon" / "arsenal" / "tv-top-performers.md"
        )

        try:
            current_mtime = arsenal_path.stat().st_mtime
        except FileNotFoundError:
            return False

        if current_mtime != self._last_arsenal_mtime:
            self._last_arsenal_mtime = current_mtime
            return True

        return False
