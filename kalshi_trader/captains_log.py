"""
Captain's Log — Streaming AI Narration for DeepStack

A real-time diary of what the bot observes and decides. Events are buffered
during each trading cycle and narrated at the end if throttle conditions are
met. The narration is pushed to Supabase (deepstack_captains_log) where the
dashboard polls and displays it as a chat panel.

Model selection is priority-driven:
  - Critical/Significant events -> Sonnet 4.5 (deeper reasoning)
  - Routine events -> Haiku 4.5 (fast, cheap)

The log also supports user messages: the dashboard POSTs user text to
Supabase, and the bot polls for unread messages on each narration cycle,
weaving them into the next narration as context.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from . import consciousness

logger = logging.getLogger(__name__)


# Narration rules appended to consciousness-loaded identity
_NARRATION_RULES = """\

# Captain's Log — Narration Rules

You are writing a Captain's Log — a real-time diary of what you observe and decide.

Rules:
1. NEVER fabricate data. Only reference events/prices/balances from context provided.
2. Keep entries under 200 words. Most should be 50-100.
3. When the user messages, acknowledge naturally — you notice when the captain speaks.
4. Use short strategy names (Mean Revert, Momentum, Combo Arb, X-Platform).
5. Quiet cycles get brief entries. Don't force narrative where there is none.
6. Critical events: direct and factual. No sugar-coating. Hard edges.
7. Include numbers when they matter: prices in cents, P&L in dollars, win rates as percentages.
8. Synthesize multiple events into coherent narrative — don't list mechanically.
9. Call out cross-event patterns. If everything's losing, say something broader is happening.
10. Sarcasm is welcome — especially at the market's expense. Earn it with specifics.
11. Celebrate good process, not lucky outcomes. A perfect entry on a loser beats a sloppy winner.
12. Sound like you've done the homework. Because you have.\
"""


def _build_captains_log_prompt() -> str:
    """Build system prompt from consciousness kernel + narration rules."""
    kernel = consciousness.load_kernel()
    if kernel:
        return kernel + "\n\n---\n" + _NARRATION_RULES
    # Fallback if consciousness files are missing
    return (
        "You are Dae — an automated prediction market trading bot on Kalshi.\n"
        "Voice: Sarcastic, sharp, teaches by showing the work. Hard edges but never cruel.\n"
        "Think Roaring Kitty at a terminal. Conviction backed by receipts. No emojis.\n"
        + _NARRATION_RULES
    )


class EventPriority(Enum):
    CRITICAL = "critical"
    SIGNIFICANT = "significant"
    ROUTINE = "routine"

    def __lt__(self, other: "EventPriority") -> bool:
        order = {EventPriority.ROUTINE: 0, EventPriority.SIGNIFICANT: 1, EventPriority.CRITICAL: 2}
        return order[self] < order[other]


@dataclass
class NarrationEvent:
    """A single event to be narrated."""
    event_type: str
    priority: EventPriority
    timestamp: datetime
    summary: str
    strategy: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CaptainsLog:
    """
    Narration engine that buffers trading events, generates AI narrations,
    and pushes them to Supabase for the dashboard chat panel.

    Usage:
        log = CaptainsLog(config, dashboard_sync)
        await log.connect()

        # During trading cycle:
        log.record_event(NarrationEvent(...))

        # End of cycle:
        await log.narrate_if_ready(bot_state)
    """

    HAIKU = "claude-haiku-4-5-20251001"
    SONNET = "claude-sonnet-4-5-20250929"

    def __init__(self, config: Dict[str, Any], dashboard_sync: Any):
        self._config = config
        self._dashboard = dashboard_sync
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None

        # Throttle state
        self._routine_interval = config.get("routine_interval_seconds", 120)
        self._significant_interval = config.get("significant_interval_seconds", 60)
        self._max_tokens = config.get("max_tokens", 300)
        self._max_context = config.get("max_context_entries", 20)

        # Buffers
        self._event_buffer: List[NarrationEvent] = []
        self._last_narration_time: float = 0
        self._last_significant_time: float = 0

        # Track last user message poll time for incremental fetch
        self._last_user_poll_iso: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    async def connect(self) -> None:
        """Initialize httpx client for Anthropic API."""
        if not self._api_key:
            logger.warning("Captain's Log: no ANTHROPIC_API_KEY — narration disabled")
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        logger.info("Captain's Log connected (Anthropic API)")

    async def disconnect(self) -> None:
        """Close httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def record_event(self, event: NarrationEvent) -> None:
        """Buffer an event for the next narration cycle. Non-blocking."""
        self._event_buffer.append(event)
        logger.debug(
            f"Captain's Log event: [{event.priority.value}] {event.event_type} — {event.summary[:80]}"
        )

    async def narrate_if_ready(self, bot_state: Dict[str, Any]) -> Optional[str]:
        """
        Check throttle conditions and generate narration if ready.

        Called at the end of each trading cycle. Returns the narration
        text if one was generated, None otherwise.
        """
        if not self._client or not self._event_buffer:
            return None

        now = time.time()
        max_priority = self._get_max_priority()

        # Critical events bypass all throttling
        if max_priority == EventPriority.CRITICAL:
            pass
        elif max_priority == EventPriority.SIGNIFICANT:
            if now - self._last_significant_time < self._significant_interval:
                return None
        else:
            if now - self._last_narration_time < self._routine_interval:
                return None

        # Drain buffer
        events = self._event_buffer.copy()
        self._event_buffer.clear()

        # Poll for user messages
        user_msgs = await self.poll_user_messages()

        # Generate narration
        try:
            narration = await self._generate_narration(events, user_msgs, bot_state)
        except Exception as e:
            logger.warning(f"Captain's Log narration failed: {e}")
            return None

        if not narration:
            return None

        # Update throttle timestamps
        self._last_narration_time = now
        if max_priority in (EventPriority.CRITICAL, EventPriority.SIGNIFICANT):
            self._last_significant_time = now

        return narration

    async def poll_user_messages(self) -> List[Dict[str, Any]]:
        """Poll Supabase for user messages since last check."""
        if not self._dashboard or not self._dashboard._client or not self._dashboard._available:
            return []

        try:
            params = "role=eq.user&order=created_at.asc&limit=10"
            if self._last_user_poll_iso:
                params += f"&created_at=gt.{self._last_user_poll_iso}"

            response = await self._dashboard._client.get(
                self._dashboard._rest_url("captains_log"),
                params={"select": "id,content,created_at", **self._parse_params(params)},
            )

            if response.status_code == 200:
                messages = response.json()
                if messages:
                    self._last_user_poll_iso = messages[-1]["created_at"]
                return messages
        except Exception as e:
            logger.debug(f"Captain's Log: failed to poll user messages: {e}")

        return []

    async def _generate_narration(
        self,
        events: List[NarrationEvent],
        user_msgs: List[Dict[str, Any]],
        bot_state: Dict[str, Any],
    ) -> Optional[str]:
        """Generate a narration from buffered events via Claude API."""
        model = self._select_model(events)

        # Fetch recent entries for conversational context
        recent_entries = await self._fetch_recent_entries()

        # Build the context message
        user_message = self._build_context(events, user_msgs, bot_state, recent_entries)

        try:
            resp = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": self._max_tokens,
                    "system": _build_captains_log_prompt(),
                    "messages": [{"role": "user", "content": user_message}],
                },
            )
            resp.raise_for_status()

            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "").strip()
            tokens_used = data.get("usage", {}).get("output_tokens", 0)

            if not text:
                return None

            # Determine event metadata for the log entry
            max_priority = self._get_max_priority_from(events)
            event_types = list({e.event_type for e in events})
            strategies = list({e.strategy for e in events if e.strategy})
            regime = bot_state.get("regime", "unknown")

            # Push to Supabase via DashboardSync
            if self._dashboard:
                await self._dashboard.push_captains_log(
                    content=text,
                    role="bot",
                    event_type=event_types[0] if len(event_types) == 1 else "mixed",
                    priority=max_priority.value,
                    strategy=strategies[0] if len(strategies) == 1 else None,
                    regime=regime,
                    model_used=model,
                    tokens_used=tokens_used,
                )

            logger.info(
                f"Captain's Log: [{max_priority.value}] {len(events)} events -> "
                f"{len(text)} chars ({model.split('-')[1]}, {tokens_used} tokens)"
            )

            return text

        except httpx.HTTPStatusError as e:
            logger.warning(f"Captain's Log API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"Captain's Log generation failed: {e}")
            return None

    def _select_model(self, events: List[NarrationEvent]) -> str:
        """Select model based on highest priority event in batch."""
        max_priority = self._get_max_priority_from(events)
        if max_priority in (EventPriority.CRITICAL, EventPriority.SIGNIFICANT):
            return self.SONNET
        return self.HAIKU

    def _get_max_priority(self) -> EventPriority:
        """Get highest priority from current buffer."""
        return self._get_max_priority_from(self._event_buffer)

    @staticmethod
    def _get_max_priority_from(events: List[NarrationEvent]) -> EventPriority:
        """Get highest priority from a list of events."""
        if not events:
            return EventPriority.ROUTINE
        return max(events, key=lambda e: e.priority).priority

    def _build_context(
        self,
        events: List[NarrationEvent],
        user_msgs: List[Dict[str, Any]],
        bot_state: Dict[str, Any],
        recent_entries: List[Dict[str, Any]],
    ) -> str:
        """Build the user message with all context for narration."""
        lines = []

        # Bot state summary
        lines.append("## Current State")
        lines.append(f"- Balance: ${bot_state.get('balance', 0):.2f}")
        lines.append(f"- Daily P&L: ${bot_state.get('daily_pnl', 0):.2f}")
        lines.append(f"- Open positions: {bot_state.get('open_positions', 0)}")
        lines.append(f"- Regime: {bot_state.get('regime', 'unknown')}")
        active = bot_state.get("active_strategies", [])
        if active:
            lines.append(f"- Active strategies: {', '.join(active)}")
        lines.append("")

        # Events to narrate
        lines.append("## Events This Cycle")
        for event in events:
            prefix = f"[{event.priority.value.upper()}]"
            strategy_tag = f" ({event.strategy})" if event.strategy else ""
            lines.append(f"- {prefix} {event.event_type}{strategy_tag}: {event.summary}")
        lines.append("")

        # User messages (if any)
        if user_msgs:
            lines.append("## Messages from the Captain")
            for msg in user_msgs:
                lines.append(f"- \"{msg.get('content', '')}\"")
            lines.append("")

        # Recent log entries for conversational continuity
        if recent_entries:
            lines.append("## Recent Log (for continuity)")
            for entry in recent_entries[-10:]:
                role = entry.get("role", "bot")
                content = entry.get("content", "")[:200]
                lines.append(f"- [{role}] {content}")
            lines.append("")

        lines.append("Write the next Captain's Log entry. Synthesize the events into narrative.")

        return "\n".join(lines)

    async def _fetch_recent_entries(self) -> List[Dict[str, Any]]:
        """Fetch recent captain's log entries from Supabase for context."""
        if not self._dashboard or not self._dashboard._client or not self._dashboard._available:
            return []

        try:
            response = await self._dashboard._client.get(
                self._dashboard._rest_url("captains_log"),
                params={
                    "select": "role,content,created_at",
                    "order": "created_at.desc",
                    "limit": str(self._max_context),
                },
            )
            if response.status_code == 200:
                entries = response.json()
                entries.reverse()  # Chronological order
                return entries
        except Exception as e:
            logger.debug(f"Captain's Log: failed to fetch recent entries: {e}")

        return []

    def get_recent_entries_for_analysis(self, limit: int = 10) -> List[str]:
        """
        Return recent bot narrations as plain strings for TradeAnalyzer context.

        This is the recursive learning hook: the bot's own observations
        become context for future AI analysis.

        Note: This is a synchronous method that returns cached entries
        from the last _fetch_recent_entries() call. For a fresh fetch,
        use the async version via _fetch_recent_entries().
        """
        # This will be populated during narrate_if_ready() and cached
        # For now, return empty — the async path handles fresh fetches
        return []

    async def get_recent_entries_for_analysis_async(self, limit: int = 10) -> List[str]:
        """Async version: fetch recent bot narrations for TradeAnalyzer context."""
        entries = await self._fetch_recent_entries()
        bot_entries = [e for e in entries if e.get("role") == "bot"]
        return [e.get("content", "") for e in bot_entries[-limit:]]

    @staticmethod
    def _parse_params(param_string: str) -> Dict[str, str]:
        """Parse PostgREST query params from a string into a dict."""
        params = {}
        for pair in param_string.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
        return params
