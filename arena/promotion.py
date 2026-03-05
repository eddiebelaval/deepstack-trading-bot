"""
Promotion Pipeline — Tournament Rankings to Config Updates

Evaluates strategy rankings against thresholds and generates
recommendations (promote_paper, promote_live, demote, hold).
Can optionally apply changes to config.yaml with safety guards.

Safety:
    - Max 5 strategies enabled at once (capital concentration)
    - Backup config.yaml -> config.yaml.bak before any write
    - --apply flag required for actual writes (dry-run default)
"""

import logging
import shutil
import statistics
from pathlib import Path
from typing import List

import yaml

from arena.config import ArenaConfig
from arena.models import PromotionCandidate, StrategyScore

logger = logging.getLogger(__name__)

# Project root config.yaml
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class PromotionPipeline:
    """Evaluate tournament rankings and generate config.yaml updates."""

    def __init__(self, config: ArenaConfig, config_path: Path = _CONFIG_PATH):
        self.config = config
        self.config_path = config_path

    def evaluate(
        self, rankings: List[StrategyScore]
    ) -> List[PromotionCandidate]:
        """Evaluate rankings against thresholds.

        Returns a list of PromotionCandidate with recommendations.
        """
        candidates = []

        for score in rankings:
            rec = "hold"
            if score.composite_score >= self.config.promote_live_threshold:
                rec = "promote_live"
            elif score.composite_score >= self.config.promote_paper_threshold:
                rec = "promote_paper"
            elif score.composite_score <= self.config.demote_threshold:
                rec = "demote"

            candidates.append(PromotionCandidate(
                strategy_name=score.strategy_name,
                avg_composite_score=score.composite_score,
                avg_win_rate=score.win_rate,
                avg_sharpe=score.sharpe_ratio,
                avg_profit_factor=score.profit_factor,
                avg_max_drawdown_pct=score.max_drawdown_pct,
                avg_pnl_cents=score.avg_pnl_cents,
                total_trades_across_windows=score.total_trades,
                recommendation=rec,
            ))

        return candidates

    def generate_diff(self, candidates: List[PromotionCandidate]) -> str:
        """Generate a human-readable diff of proposed changes."""
        lines = []
        divider = "-" * 60

        lines.append("")
        lines.append("  PROMOTION RECOMMENDATIONS")
        lines.append("  " + divider)

        promote_live = [c for c in candidates if c.recommendation == "promote_live"]
        promote_paper = [c for c in candidates if c.recommendation == "promote_paper"]
        demote = [c for c in candidates if c.recommendation == "demote"]
        hold = [c for c in candidates if c.recommendation == "hold"]

        if promote_live:
            lines.append("")
            lines.append("  PROMOTE TO LIVE:")
            for c in promote_live:
                lines.append(
                    f"    + {c.strategy_name:<28} "
                    f"score={c.avg_composite_score:.1f}  "
                    f"wr={c.avg_win_rate:.0%}  "
                    f"pnl={c.avg_pnl_cents:+.1f}c/trade"
                )

        if promote_paper:
            lines.append("")
            lines.append("  PROMOTE TO PAPER TRADE:")
            for c in promote_paper:
                lines.append(
                    f"    ~ {c.strategy_name:<28} "
                    f"score={c.avg_composite_score:.1f}  "
                    f"wr={c.avg_win_rate:.0%}  "
                    f"pnl={c.avg_pnl_cents:+.1f}c/trade"
                )

        if demote:
            lines.append("")
            lines.append("  DEMOTE (DISABLE):")
            for c in demote:
                lines.append(
                    f"    - {c.strategy_name:<28} "
                    f"score={c.avg_composite_score:.1f}  "
                    f"wr={c.avg_win_rate:.0%}  "
                    f"pnl={c.avg_pnl_cents:+.1f}c/trade"
                )

        if hold:
            lines.append("")
            lines.append("  HOLD (NO CHANGE):")
            for c in hold:
                lines.append(
                    f"    = {c.strategy_name:<28} "
                    f"score={c.avg_composite_score:.1f}"
                )

        lines.append("")
        lines.append("  " + divider)

        # Count proposed enables
        would_enable = len(promote_live)
        if would_enable > self.config.max_enabled_strategies:
            lines.append(
                f"  WARNING: {would_enable} strategies exceed max "
                f"({self.config.max_enabled_strategies}). "
                f"Only top {self.config.max_enabled_strategies} will be enabled."
            )

        return "\n".join(lines)

    def apply(self, candidates: List[PromotionCandidate]) -> None:
        """Apply promotion changes to config.yaml.

        Creates a backup at config.yaml.bak before writing.
        Respects max_enabled_strategies limit.
        """
        if not self.config_path.exists():
            logger.error(f"Config file not found: {self.config_path}")
            return

        # Backup
        backup_path = self.config_path.with_suffix(".yaml.bak")
        shutil.copy2(self.config_path, backup_path)
        logger.info(f"Backed up config to {backup_path}")

        # Load current config
        with open(self.config_path) as f:
            config_data = yaml.safe_load(f)

        strategies = config_data.get("strategies", [])
        strategy_map = {s["name"]: s for s in strategies}

        # Determine which to enable (top N by score, must be promote_live)
        to_enable = sorted(
            [c for c in candidates if c.recommendation == "promote_live"],
            key=lambda c: c.avg_composite_score,
            reverse=True,
        )[:self.config.max_enabled_strategies]

        to_enable_names = {c.strategy_name for c in to_enable}
        to_demote_names = {
            c.strategy_name
            for c in candidates
            if c.recommendation == "demote"
        }

        changes = []
        for strat in strategies:
            name = strat["name"]
            was_enabled = strat.get("enabled", False)

            if name in to_enable_names and not was_enabled:
                strat["enabled"] = True
                changes.append(f"ENABLED:  {name}")
            elif name in to_demote_names and was_enabled:
                strat["enabled"] = False
                changes.append(f"DISABLED: {name}")

        # Write updated config
        with open(self.config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

        for change in changes:
            logger.info(f"Config: {change}")

        if not changes:
            logger.info("No config changes needed")
