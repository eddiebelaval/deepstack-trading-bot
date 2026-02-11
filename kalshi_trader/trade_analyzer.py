"""
Trade Analyzer — Claude Intelligence Layer for DeepStack

Sends trade journal data to Claude for qualitative strategy analysis.
Returns structured recommendations: Kelly fractions (auto-apply),
strategy flags + parameter suggestions (human review).

Follows the same httpx + Anthropic REST pattern as LLMProvider
(strategies/data_providers/llm.py) but requests JSON output
for reliable structured parsing.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are a prediction market strategy analyst reviewing a trading bot's performance data.

Your job: assess each strategy independently, detect cross-strategy patterns, and provide actionable recommendations.

## Analysis Framework

For EACH strategy in the data:
1. **Win rate context**: Is the observed win rate consistent with the strategy's thesis? Is it trending up or down?
2. **Entry timing**: Are entries happening at good prices, or is the bot chasing? Look at entry_price_cents relative to exit outcomes.
3. **Exit quality**: Are exits optimal? Look at exit_reason — are stop losses being hit too often vs take profits? Are settlements dominating?
4. **P&L distribution**: Is the strategy making money from a few big wins or consistent small wins? Which is healthier for this strategy type?

Cross-strategy patterns to detect:
- Time-of-day effects (if timestamps show clustering)
- Market regime sensitivity (are all strategies losing simultaneously?)
- Correlation between strategies (are they taking the same directional bets?)

## Kelly Fraction Guidance

Calculate recommended Kelly fraction per strategy using:
  kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
  recommended = kelly * 0.5  (half-Kelly for safety)

If a strategy has negative expected value, recommend kelly = 0.0 (disable sizing).

## Output Format

You MUST respond with valid JSON matching this exact schema:
{
  "strategy_assessments": [
    {
      "strategy_name": "string",
      "verdict": "healthy | underperforming | no_edge | insufficient_data",
      "reasoning": "2-3 sentence explanation",
      "kelly_suggestion": 0.0,
      "parameter_flags": [
        {
          "param": "parameter_name",
          "current": 0,
          "suggested": 0,
          "reason": "why this change"
        }
      ]
    }
  ],
  "patterns_detected": ["string"],
  "risk_flags": ["string"],
  "overall_summary": "2-3 sentence portfolio-level summary",
  "confidence": "high | medium | low"
}

Be direct. No hedging. If data is insufficient, say so. If a strategy is losing money, say it plainly.\
"""


@dataclass
class StrategyAssessment:
    strategy_name: str
    verdict: str  # "healthy", "underperforming", "no_edge", "insufficient_data"
    reasoning: str
    kelly_suggestion: float
    parameter_flags: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalysisResult:
    strategy_assessments: List[StrategyAssessment]
    patterns_detected: List[str]
    risk_flags: List[str]
    overall_summary: str
    confidence: str  # "high", "medium", "low"
    raw_response: str = ""


class TradeAnalyzer:
    """
    Claude-powered trade analysis engine.

    Sends structured trade data to Claude and parses strategy-level
    recommendations. Uses the same httpx + Anthropic REST API pattern
    as the existing LLMProvider.
    """

    MAX_CALLS_PER_MINUTE = 5
    CACHE_TTL_SECONDS = 1800  # 30 minutes — analysis doesn't change fast

    def __init__(self, config: Dict[str, Any]):
        analysis_cfg = config.get("analysis", {})
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._model = analysis_cfg.get("model", "claude-sonnet-4-5-20250929")
        self._auto_apply_kelly = analysis_cfg.get("auto_apply_kelly", True)
        self._auto_apply_params = analysis_cfg.get("auto_apply_params", False)
        self._min_trades = analysis_cfg.get("min_trades_for_analysis", 10)

        self._client: Optional[httpx.AsyncClient] = None
        self._call_timestamps: List[float] = []
        self._cache: Dict[str, Tuple[float, AnalysisResult]] = {}

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=60.0,  # Analysis responses can be lengthy
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    def _check_rate_limit(self) -> bool:
        now = time.time()
        self._call_timestamps = [
            ts for ts in self._call_timestamps if now - ts < 60
        ]
        return len(self._call_timestamps) < self.MAX_CALLS_PER_MINUTE

    async def analyze(
        self,
        trade_export: Dict[str, Any],
        current_config: Dict[str, Any],
    ) -> AnalysisResult:
        """
        Run Claude analysis on exported trade data.

        Args:
            trade_export: Output of TradeJournal.export_for_analysis()
            current_config: Current bot config dict (strategies + risk params)

        Returns:
            AnalysisResult with per-strategy assessments and recommendations
        """
        total_trades = trade_export.get("summary", {}).get("total_trades", 0)
        if total_trades < self._min_trades:
            return AnalysisResult(
                strategy_assessments=[],
                patterns_detected=[],
                risk_flags=[],
                overall_summary=(
                    f"Insufficient data: {total_trades} trades "
                    f"(minimum {self._min_trades} required for analysis)"
                ),
                confidence="low",
            )

        if not self.is_available:
            logger.warning("TradeAnalyzer: no ANTHROPIC_API_KEY, skipping analysis")
            return AnalysisResult(
                strategy_assessments=[],
                patterns_detected=[],
                risk_flags=[],
                overall_summary="Analysis unavailable: no API key configured",
                confidence="low",
            )

        # Check cache
        cache_key = f"{trade_export.get('period', {})}:{total_trades}"
        if cache_key in self._cache:
            cached_time, cached_result = self._cache[cache_key]
            if time.time() - cached_time < self.CACHE_TTL_SECONDS:
                return cached_result

        if not self._check_rate_limit():
            logger.warning("TradeAnalyzer: rate limit reached")
            return AnalysisResult(
                strategy_assessments=[],
                patterns_detected=[],
                risk_flags=[],
                overall_summary="Analysis rate-limited, try again in a minute",
                confidence="low",
            )

        try:
            user_message = self._build_user_message(trade_export, current_config)
            result = await self._call_claude(user_message)
            self._cache[cache_key] = (time.time(), result)
            return result
        except Exception as e:
            logger.error(f"TradeAnalyzer failed: {e}")
            return AnalysisResult(
                strategy_assessments=[],
                patterns_detected=[],
                risk_flags=[],
                overall_summary=f"Analysis failed: {str(e)[:200]}",
                confidence="low",
            )

    def _build_user_message(
        self,
        trade_export: Dict[str, Any],
        current_config: Dict[str, Any],
    ) -> str:
        """Build the user message with trade data and current config."""
        lines = []

        # Period and summary
        period = trade_export.get("period", {})
        summary = trade_export.get("summary", {})
        lines.append(f"## Trade Data ({period.get('start', '?')} to {period.get('end', '?')})")
        lines.append("")
        lines.append("### Portfolio Summary")
        lines.append(f"- Total trades: {summary.get('total_trades', 0)}")
        lines.append(f"- Win rate: {summary.get('win_rate', 0):.1%}")
        lines.append(f"- Total P&L: {summary.get('total_pnl_cents', 0)}c (${summary.get('total_pnl_cents', 0) / 100:.2f})")
        lines.append(f"- Profit factor: {summary.get('profit_factor', 0):.2f}")
        lines.append(f"- Avg winner: {summary.get('avg_winner_cents', 0):.1f}c")
        lines.append(f"- Avg loser: {summary.get('avg_loser_cents', 0):.1f}c")
        lines.append("")

        # Per-strategy breakdown
        by_strategy = trade_export.get("by_strategy", {})
        for strat_name, strat_data in by_strategy.items():
            stats = strat_data.get("stats", {})
            trades = strat_data.get("trades", [])

            lines.append(f"### Strategy: {strat_name}")
            lines.append(f"- Trades: {stats.get('total_trades', 0)}")
            lines.append(f"- Win rate: {stats.get('win_rate', 0):.1%}")
            lines.append(f"- Total P&L: {stats.get('total_pnl_cents', 0)}c")
            lines.append(f"- Avg P&L: {stats.get('avg_pnl_cents', 0):.1f}c")
            lines.append("")

            # Trade details table (capped to avoid token explosion)
            display_trades = trades[:50]
            lines.append("| Ticker | Side | Action | Entry | Exit | P&L | Exit Reason | Reasoning |")
            lines.append("|--------|------|--------|-------|------|-----|-------------|-----------|")
            for t in display_trades:
                entry = t.get("fill_price_cents") or t.get("entry_price_cents", "?")
                exit_p = t.get("exit_price_cents", "-")
                pnl = t.get("pnl_cents", "-")
                pnl_str = f"{pnl:+d}c" if isinstance(pnl, int) else str(pnl)
                exit_reason = (t.get("exit_reason") or "-")[:40]
                reasoning = (t.get("reasoning") or "-")[:60]
                lines.append(
                    f"| {t.get('market_ticker', '?')} "
                    f"| {t.get('side', '?')} "
                    f"| {t.get('action', '?')} "
                    f"| {entry}c "
                    f"| {exit_p}c "
                    f"| {pnl_str} "
                    f"| {exit_reason} "
                    f"| {reasoning} |"
                )
            if len(trades) > 50:
                lines.append(f"| ... {len(trades) - 50} more trades omitted ... |")
            lines.append("")

        # Current config context
        lines.append("### Current Configuration")
        risk_cfg = current_config.get("risk", {})
        lines.append(f"- Kelly fraction: {risk_cfg.get('kelly_fraction', 'not set')}")
        lines.append(f"- Max position: ${risk_cfg.get('max_position_size', 'not set')}")
        lines.append(f"- Daily loss limit: ${risk_cfg.get('daily_loss_limit', 'not set')}")
        lines.append("")

        # Strategy-specific configs
        strategies_cfg = current_config.get("strategies", [])
        enabled = [s for s in strategies_cfg if s.get("enabled")]
        if enabled:
            lines.append("#### Enabled Strategy Parameters")
            for s in enabled:
                name = s.get("name", "?")
                cfg = s.get("config", {})
                params = ", ".join(f"{k}={v}" for k, v in cfg.items())
                lines.append(f"- **{name}**: {params}")
            lines.append("")

        return "\n".join(lines)

    async def _call_claude(self, user_message: str) -> AnalysisResult:
        """Make the Claude API call and parse the response."""
        client = await self._get_client()
        self._call_timestamps.append(time.time())

        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": self._model,
                "max_tokens": 4096,
                "system": ANALYSIS_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
        )
        resp.raise_for_status()

        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "").strip()

        return self._parse_response(text)

    def _parse_response(self, text: str) -> AnalysisResult:
        """Parse Claude's JSON response into an AnalysisResult."""
        # Strip markdown code fences if present
        cleaned = text
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse analysis JSON: {e}")
            return AnalysisResult(
                strategy_assessments=[],
                patterns_detected=[],
                risk_flags=[],
                overall_summary=f"Parse error — raw response preserved",
                confidence="low",
                raw_response=text,
            )

        assessments = []
        for a in parsed.get("strategy_assessments", []):
            assessments.append(StrategyAssessment(
                strategy_name=a.get("strategy_name", "unknown"),
                verdict=a.get("verdict", "insufficient_data"),
                reasoning=a.get("reasoning", ""),
                kelly_suggestion=float(a.get("kelly_suggestion", 0.0)),
                parameter_flags=a.get("parameter_flags", []),
            ))

        return AnalysisResult(
            strategy_assessments=assessments,
            patterns_detected=parsed.get("patterns_detected", []),
            risk_flags=parsed.get("risk_flags", []),
            overall_summary=parsed.get("overall_summary", ""),
            confidence=parsed.get("confidence", "low"),
            raw_response=text,
        )

    def format_report(self, result: AnalysisResult) -> str:
        """Format an AnalysisResult as a human-readable report."""
        lines = [
            "=== Trade Analysis Report ===",
            "",
            f"Confidence: {result.confidence}",
            f"Summary: {result.overall_summary}",
            "",
        ]

        if result.strategy_assessments:
            lines.append("--- Strategy Assessments ---")
            for a in result.strategy_assessments:
                lines.append(f"\n  [{a.verdict.upper()}] {a.strategy_name}")
                lines.append(f"  {a.reasoning}")
                lines.append(f"  Kelly suggestion: {a.kelly_suggestion:.2f}")
                if a.parameter_flags:
                    for pf in a.parameter_flags:
                        lines.append(
                            f"    -> {pf['param']}: {pf.get('current')} -> "
                            f"{pf.get('suggested')} ({pf.get('reason', '')})"
                        )

        if result.patterns_detected:
            lines.append("\n--- Patterns Detected ---")
            for p in result.patterns_detected:
                lines.append(f"  - {p}")

        if result.risk_flags:
            lines.append("\n--- Risk Flags ---")
            for r in result.risk_flags:
                lines.append(f"  ! {r}")

        return "\n".join(lines)

    def get_kelly_adjustments(self, result: AnalysisResult) -> Dict[str, float]:
        """
        Extract Kelly fraction adjustments from analysis.

        Only returns adjustments if auto_apply_kelly is enabled.
        """
        if not self._auto_apply_kelly:
            return {}

        adjustments = {}
        for a in result.strategy_assessments:
            if a.kelly_suggestion >= 0:
                adjustments[a.strategy_name] = a.kelly_suggestion
        return adjustments

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
