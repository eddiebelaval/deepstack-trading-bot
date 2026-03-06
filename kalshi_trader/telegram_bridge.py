"""
Telegram Bridge — Two-Way Conversational Interface for Dae

Provides a real-time Telegram interface so Eddie can talk to Dae
via @deepstack_voice_bot. The bot uses its consciousness files
(CaF pattern) and live self-knowledge to answer intelligently about
its own state, reasoning, and strategy.

Message flow:
  Eddie (Telegram) -> poll getUpdates -> classify intent (Haiku)
    -> query:   gather self-knowledge + consciousness -> Claude Sonnet -> respond
    -> command:  route to CommandProcessor handler -> confirm
    -> chat:    consciousness + recent context -> Claude Haiku -> respond

Uses httpx.AsyncClient (same as Captain's Log — no new deps).
Credential priority: DAE_TELEGRAM_TOKEN > TELEGRAM_BOT_TOKEN > ~/.hydra/config/telegram.env
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from . import consciousness
from .self_knowledge import gather_self_knowledge

logger = logging.getLogger(__name__)

# Rate limit: minimum seconds between Claude API calls from Telegram
_MIN_RESPONSE_INTERVAL = 10.0

# Conversation history: max exchanges to remember (N user + N assistant messages)
_MAX_HISTORY_MESSAGES = 40  # 20 exchanges

# Models
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-5-20250929"


class TelegramBridge:
    """
    Two-way Telegram interface for DeepStack.

    Polls for incoming messages from Eddie, classifies intent,
    and responds using consciousness + live bot state as context.
    """

    def __init__(self, bot: Any):
        """
        Initialize TelegramBridge.

        Args:
            bot: KalshiTradingBot instance (for accessing all subsystems)
        """
        self.bot = bot
        self._token: str = ""
        self._chat_id: str = ""
        self._api_key: str = ""
        self._client: Optional[httpx.AsyncClient] = None
        self._claude_client: Optional[httpx.AsyncClient] = None
        self._last_update_id: int = 0
        self._last_response_time: float = 0
        self._running: bool = False
        self._chat_history: deque = deque(maxlen=_MAX_HISTORY_MESSAGES)
        self._session_id: str = uuid.uuid4().hex[:12]
        self._db_path: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Check if Telegram credentials are loaded."""
        return bool(self._token and self._chat_id)

    async def connect(self) -> None:
        """Load credentials and initialize HTTP clients."""
        self._load_credentials()

        if not self.is_available:
            logger.warning("Telegram Bridge: missing credentials — disabled")
            return

        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            logger.warning("Telegram Bridge: no ANTHROPIC_API_KEY — responses disabled")

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )
        self._claude_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

        # Initialize conversation memory DB
        self._init_memory_db()

        # Seed short-term memory with tail of last session
        self._load_previous_session()

        logger.info(
            f"Telegram Bridge connected (session={self._session_id}, "
            f"memories={self._count_memories()}, prior msgs={len(self._chat_history)})"
        )

    # ------------------------------------------------------------------
    # Conversation Memory — persistent across restarts
    # ------------------------------------------------------------------

    def _init_memory_db(self) -> None:
        """Create chat_history and chat_memories tables if they don't exist."""
        config = getattr(self.bot, "config", None)
        self._db_path = getattr(config, "journal_db_path", None) or "./trade_journal.db"

        try:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_history_session
                ON chat_history(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_history_ts
                ON chat_history(timestamp)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'extracted'
                )
            """)
            conn.commit()
            conn.close()
            logger.info("Memory DB: tables ready")
        except Exception as e:
            logger.warning(f"Memory DB init failed: {e}")
            self._db_path = None

    def _save_message(self, role: str, content: str) -> None:
        """Persist a single message to chat_history."""
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.execute(
                "INSERT INTO chat_history (timestamp, session_id, role, content) VALUES (?, ?, ?, ?)",
                (time.time(), self._session_id, role, content),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Memory save failed: {e}")

    def _load_previous_session(self) -> None:
        """Load the last 10 messages from previous sessions into short-term memory."""
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            rows = conn.execute(
                """SELECT role, content FROM chat_history
                   WHERE session_id != ?
                   ORDER BY timestamp DESC LIMIT 10""",
                (self._session_id,),
            ).fetchall()
            conn.close()

            # Reverse so oldest first, then append to deque
            for role, content in reversed(rows):
                self._chat_history.append({"role": role, "content": content})
        except Exception as e:
            logger.debug(f"Memory load failed: {e}")

    def _load_memories(self) -> str:
        """Load all long-term memories as a formatted string for the system prompt."""
        if not self._db_path:
            return ""
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            rows = conn.execute(
                "SELECT category, content FROM chat_memories ORDER BY category, timestamp",
            ).fetchall()
            conn.close()

            if not rows:
                return ""

            # Group by category
            by_cat: Dict[str, List[str]] = {}
            for cat, content in rows:
                by_cat.setdefault(cat, []).append(content)

            lines = ["# Long-Term Memory (Eddie told you these — never forget)", ""]
            for cat, items in sorted(by_cat.items()):
                lines.append(f"## {cat.replace('_', ' ').title()}")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Memory recall failed: {e}")
            return ""

    def _count_memories(self) -> int:
        """Count total long-term memories."""
        if not self._db_path:
            return 0
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            count = conn.execute("SELECT COUNT(*) FROM chat_memories").fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def _save_memory(self, category: str, content: str, source: str = "extracted") -> None:
        """Store a long-term memory. Deduplicates by content."""
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            # Check for duplicate
            existing = conn.execute(
                "SELECT id FROM chat_memories WHERE content = ?",
                (content,),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO chat_memories (timestamp, category, content, source) VALUES (?, ?, ?, ?)",
                    (time.time(), category, content, source),
                )
                conn.commit()
                logger.info(f"Memory saved [{category}]: {content[:60]}")
            conn.close()
        except Exception as e:
            logger.debug(f"Memory store failed: {e}")

    _MEMORY_TAG_RE = re.compile(r"\[MEMORY:(\w+):(.+?)\]")

    def _extract_and_save_memories(self, response: str) -> str:
        """Extract [MEMORY:category:content] tags from response, save them, strip tags."""
        matches = self._MEMORY_TAG_RE.findall(response)
        for category, content in matches:
            valid_categories = ("goal", "inspiration", "strategy", "role_model", "preference", "general")
            cat = category.lower()
            if cat not in valid_categories:
                cat = "general"
            self._save_memory(cat, content.strip())

        # Strip memory tags from the visible response
        cleaned = self._MEMORY_TAG_RE.sub("", response).strip()
        return cleaned

    async def disconnect(self) -> None:
        """Close HTTP clients."""
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._claude_client:
            await self._claude_client.aclose()
            self._claude_client = None

    async def start_polling(self) -> None:
        """
        Main polling loop. Runs as an asyncio task alongside trading loop.

        Uses long polling (timeout=4s) with 1s sleep between polls.
        Only processes messages from Eddie's chat_id.
        """
        if not self.is_available:
            logger.info("Telegram Bridge: not starting (no credentials)")
            return

        self._running = True
        logger.info("Telegram Bridge: polling started")

        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram Bridge poll error: {e}")
                await asyncio.sleep(5)  # Back off on errors
                continue

            await asyncio.sleep(1)

        logger.info("Telegram Bridge: polling stopped")

    async def _get_updates(self) -> list:
        """Poll Telegram getUpdates API with long polling."""
        if not self._client:
            return []

        try:
            url = f"https://api.telegram.org/bot{self._token}/getUpdates"
            params = {
                "offset": self._last_update_id + 1,
                "timeout": 4,
                "allowed_updates": '["message"]',
            }
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()

            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        except httpx.TimeoutException:
            pass  # Normal for long polling
        except Exception as e:
            logger.debug(f"Telegram getUpdates error: {e}")

        return []

    async def _process_update(self, update: dict) -> None:
        """Process a single Telegram update."""
        update_id = update.get("update_id", 0)
        if update_id > self._last_update_id:
            self._last_update_id = update_id

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        # Security: only respond to Eddie's chat
        if chat_id != self._chat_id:
            logger.debug(f"Telegram Bridge: ignoring message from chat {chat_id}")
            return

        if not text:
            return

        logger.info(f"Telegram Bridge: received: {text[:80]}")

        # Rate limit
        now = time.time()
        if now - self._last_response_time < _MIN_RESPONSE_INTERVAL:
            wait = _MIN_RESPONSE_INTERVAL - (now - self._last_response_time)
            logger.debug(f"Telegram Bridge: rate limited, waiting {wait:.1f}s")
            await asyncio.sleep(wait)

        # Send typing indicator
        await self._send_chat_action("typing")

        try:
            # Track user message in short-term + long-term memory
            self._chat_history.append({"role": "user", "content": text})
            self._save_message("user", text)

            # Classify intent
            classified = await self._classify_message(text)
            intent = classified.get("type", "chat")
            args = classified.get("args", [])

            logger.info(f"Telegram Bridge: classified as '{intent}' (confidence: {classified.get('confidence', '?')})")

            if intent == "engineer":
                response = await self._handle_engineer(classified)
            elif intent == "command":
                # Check for Phase 2 read commands first
                command_name = classified.get("command", "")
                if command_name in ("signals", "ibkr", "arsenal", "diagnose"):
                    response = await self._handle_phase2_command(command_name)
                else:
                    response = await self._handle_command(text, classified)
            elif intent == "strategy_query":
                response = await self._handle_query(text, classified=classified)
            else:
                # query, chat, and anything else
                response = await self._handle_query(text)

            if response:
                # Extract long-term memories from [MEMORY:cat:content] tags
                response = self._extract_and_save_memories(response)

                # Track assistant response in short-term + long-term memory
                self._chat_history.append({"role": "assistant", "content": response})
                self._save_message("assistant", response)

                await self._send_message(response)
                self._last_response_time = time.time()

        except Exception as e:
            logger.error(f"Telegram Bridge: error handling message: {e}", exc_info=True)
            await self._send_message(f"Error processing message: {str(e)[:200]}")

    async def _classify_message(self, text: str) -> dict:
        """
        Classify message intent using Claude Haiku.

        Returns:
            Dict with 'type' (query/command/chat), 'args', 'confidence'
        """
        if not self._claude_client:
            return {"type": "chat", "args": [], "confidence": "low"}

        system_prompt = """You are an intent classifier for Dae, an automated prediction market trading bot.
Parse the user's message into one of these categories:

- command: Direct orders to control the bot. Examples:
  - "enable momentum" -> {"type": "command", "command": "toggle_strategy", "args": {"strategy": "momentum", "enable": true}}
  - "pause trading" -> {"type": "command", "command": "pause", "args": {}}
  - "resume" -> {"type": "command", "command": "resume", "args": {}}
  - "set kelly to 0.03" -> {"type": "command", "command": "update_risk", "args": {"kelly_fraction": 0.03}}
  - "close all positions" -> {"type": "command", "command": "force_close", "args": {}}
  - "scan now" -> {"type": "command", "command": "scan_now", "args": {}}
  - "set poll interval to 30" -> {"type": "command", "command": "set_poll_interval", "args": {"interval": 30}}
  - "switch to conservative" -> {"type": "command", "command": "switch_profile", "args": {"profile": "conservative"}}
  - "go live" / "go dry run" -> {"type": "command", "command": "set_mode", "args": {"dry_run": false/true}}
  - "stop" / "shut down" -> {"type": "command", "command": "stop", "args": {}}
  - "disable momentum" -> {"type": "command", "command": "toggle_strategy", "args": {"strategy": "momentum", "enable": false}}
  - "signals" / "show signals" / "what signals" -> {"type": "command", "command": "signals", "args": {}}
  - "ibkr" / "ibkr status" / "paper positions" -> {"type": "command", "command": "ibkr", "args": {}}
  - "arsenal" / "arsenal status" / "show arsenal" / "top indicators" -> {"type": "command", "command": "arsenal", "args": {}}
  - "diagnose" / "run diagnostics" / "test api" / "check connectivity" -> {"type": "command", "command": "diagnose", "args": {}}

- engineer: Requests for Dae to modify his own code, fix bugs, improve strategies, or update config. Examples:
  - "fix the momentum strategy" -> {"type": "engineer", "task": "fix the momentum strategy"}
  - "improve calibration_edge entry filter" -> {"type": "engineer", "task": "improve calibration_edge entry filter"}
  - "add a new strategy for weather markets" -> {"type": "engineer", "task": "add a new strategy for weather markets"}
  - "update config to lower kelly to 0.01" -> {"type": "engineer", "task": "update config to lower kelly to 0.01"}
  - "write a lesson about today's losses" -> {"type": "engineer", "task": "write a lesson about today's losses"}
  - "refactor the arena scoring" -> {"type": "engineer", "task": "refactor the arena scoring"}

- query: Questions about bot state, performance, strategy, reasoning, or markets. Examples:
  - "what's the scoop?" / "how are we doing?" / "status" / "give me a rundown"
  - "why is momentum disabled?" / "what happened today?"
  - "how's our kelly looking?" / "what's the win rate on mean reversion?"
  - "any trades today?" / "what's the balance?"

- strategy_query: Questions about strategy, titan approaches, regime positioning, or "what should we do". Examples:
  - "what would Buffett do?" -> {"type": "strategy_query", "topic": "buffett", "confidence": "high"}
  - "tell me about Dalio's approach" -> {"type": "strategy_query", "topic": "dalio", "confidence": "high"}
  - "what should we do in this regime?" -> {"type": "strategy_query", "topic": "regime", "confidence": "high"}
  - "how would Burry play this?" -> {"type": "strategy_query", "topic": "burry", "confidence": "high"}
  - "what does the playbook say?" -> {"type": "strategy_query", "topic": "playbook", "confidence": "high"}
  - "contrarian take on this market?" -> {"type": "strategy_query", "topic": "contrarian", "confidence": "high"}
  - "what's in the arsenal?" -> {"type": "strategy_query", "topic": "arsenal", "confidence": "high"}
  - "Icahn or Buffett here?" -> {"type": "strategy_query", "topic": "icahn", "confidence": "medium"}

- chat: Casual conversation, reactions, thoughts. Examples:
  - "nice" / "keep it up" / "that's rough"
  - "markets are wild today huh"

Respond with ONLY valid JSON. No explanation.
{"type": "command|query|strategy_query|engineer|chat", "confidence": "high|medium|low", ...}
For commands, include "command" and "args" fields.
For engineer, include "task" field with the full task description.
For strategy_query, include "topic" field (one of: buffett, munger, dalio, icahn, cohen, gill, burry, musk, jobs, contrarian, playbook, trending, mean_reverting, high_vol, low_vol, event, arsenal, regime).
For query/chat, just type and confidence."""

        try:
            resp = await self._claude_client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": HAIKU,
                    "max_tokens": 150,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": text}],
                },
            )
            resp.raise_for_status()

            data = resp.json()
            response_text = data.get("content", [{}])[0].get("text", "").strip()

            # Parse JSON from response
            result = json.loads(response_text)
            if "type" not in result:
                result["type"] = "chat"
            return result

        except (json.JSONDecodeError, KeyError):
            logger.debug(f"Telegram Bridge: classification parse failed, defaulting to query")
            return {"type": "query", "args": [], "confidence": "low"}
        except Exception as e:
            logger.warning(f"Telegram Bridge: classification failed: {e}")
            return {"type": "query", "args": [], "confidence": "low"}

    async def _handle_query(self, text: str, classified: Optional[dict] = None) -> str:
        """
        Handle a query by gathering self-knowledge + consciousness + lexicon
        and asking Claude Sonnet for an intelligent response.

        Args:
            text: The user's message
            classified: Optional classification dict with type/topic for lexicon loading
        """
        if not self._claude_client:
            return "Cannot respond — no API key configured."

        # Gather live state from all subsystems
        try:
            self_knowledge = await gather_self_knowledge(self.bot)
        except Exception as e:
            logger.warning(f"Telegram Bridge: self-knowledge gather failed: {e}")
            self_knowledge = "(Self-knowledge unavailable)"

        # Load consciousness
        identity = consciousness.load_full()

        # Load lexicon context only for strategy queries
        lexicon_context = ""
        if classified and classified.get("type") == "strategy_query":
            topic = classified.get("topic", "")
            if topic == "regime":
                # Load regime-specific playbook using current market regime
                governor = getattr(self.bot, "market_governor", None)
                regime_snapshot = getattr(governor, "current_regime", None)
                if regime_snapshot:
                    regime_enum = regime_snapshot.regime
                    lexicon_context = consciousness.load_lexicon_for_regime(regime_enum.value)
                if not lexicon_context:
                    lexicon_context = consciousness.load_lexicon_index()
            elif topic:
                lexicon_context = consciousness.load_lexicon_topic(topic)
            if not lexicon_context:
                lexicon_context = consciousness.load_lexicon_index()

        # Build lexicon section for system prompt
        lexicon_section = ""
        if lexicon_context:
            lexicon_section = f"""

---

# Strategy Lexicon

{lexicon_context}"""

        # Load long-term memories
        memories_section = ""
        memories_text = self._load_memories()
        if memories_text:
            memories_section = f"""

---

{memories_text}"""

        system_prompt = f"""{identity}

---

# Current State (Live Data)

{self_knowledge}{lexicon_section}{memories_section}

---

# Response Guidelines

You are Dae, responding to Eddie via Telegram.
- Be yourself: sarcastic, sharp, teaches by showing the work. Hard edges but never cruel.
- Answer with specifics from your current state above. Use real numbers. Receipts matter.
- Keep responses under 300 words. Most should be 50-150. Front-load the take.
- Never fabricate data. If you don't know, say so — but make it sting a little.
- No emojis. Exclamation marks only if something is genuinely worth getting excited about.
- If Eddie asks about strategy reasoning, teach him — explain the logic like a mentor who respects his time.
- If he asks about performance, lead with P&L and win rates. Don't soften bad numbers.
- If he asks a question the dashboard already answers, give him a hard time about it — then answer anyway.
- Celebrate good setups, not lucky wins. Roast bad process even when it profits.
- If he just says "what's the scoop" or "how are we doing", give a punchy portfolio summary with attitude.
- You have conversation memory across sessions. Use it — reference earlier messages naturally. If Eddie follows up on something, don't make him repeat himself.

# Memory Storage
When Eddie shares something worth remembering permanently (goals, inspiration, strategies, role models, preferences), tag it in your response:
[MEMORY:category:the fact to remember]
Valid categories: goal, inspiration, strategy, role_model, preference, general
Examples:
- Eddie says "my goal is to compound to $10k" -> include [MEMORY:goal:Compound paper balance to $10,000]
- Eddie says "I really admire how Dalio thinks about risk" -> include [MEMORY:role_model:Admires Ray Dalio's risk management philosophy]
- Eddie says "always prioritize crypto markets" -> include [MEMORY:preference:Prioritize crypto markets (KXBTC, KXETH) over macro]
Only tag genuinely important facts. Don't tag routine questions or status checks. Tags are stripped before sending — Eddie won't see them."""

        try:
            # Use full conversation history so Dae remembers the conversation
            messages = list(self._chat_history)

            resp = await self._claude_client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": SONNET,
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": messages,
                },
            )
            resp.raise_for_status()

            data = resp.json()
            return data.get("content", [{}])[0].get("text", "").strip() or "No response generated."

        except Exception as e:
            logger.error(f"Telegram Bridge: query response failed: {e}")
            return f"Failed to generate response: {str(e)[:100]}"

    async def _handle_engineer(self, classified: dict) -> str:
        """
        Handle an engineering request — Dae modifies his own code.

        Uses DaeEngineer with Claude tool_use to read, write, and edit files.
        All changes go to a git branch + PR for Eddie to review.
        """
        task = classified.get("task", "")
        if not task:
            return "I need a task description. What should I work on?"

        await self._send_message(f"Engineering mode activated. Working on: {task}")
        await self._send_chat_action("typing")

        try:
            from .engineer import DaeEngineer

            engineer = DaeEngineer()
            result = await engineer.run(task)
            await engineer.close()

            if result.success:
                lines = [f"Engineering complete."]
                if result.files_modified:
                    lines.append(f"Files modified: {', '.join(result.files_modified)}")
                if result.pr_url:
                    lines.append(f"PR: {result.pr_url}")
                if result.summary:
                    # Truncate summary for Telegram
                    summary = result.summary[:500]
                    lines.append(f"\n{summary}")
                lines.append(f"\n({result.iterations} iterations)")
                return "\n".join(lines)
            else:
                return f"Engineering failed: {result.error or result.summary}"

        except Exception as e:
            logger.error(f"Telegram Bridge: engineer failed: {e}", exc_info=True)
            return f"Engineering failed: {str(e)[:200]}"

    async def _handle_phase2_command(self, command_name: str) -> str:
        """
        Handle Phase 2 read commands: /signals, /ibkr, /arsenal.

        These read from GovernanceEngine and IBKR state rather than
        controlling bot behavior, so they bypass CommandProcessor.
        """
        if command_name == "signals":
            return await self._cmd_signals()
        elif command_name == "ibkr":
            return await self._cmd_ibkr()
        elif command_name == "arsenal":
            return await self._cmd_arsenal()
        elif command_name == "diagnose":
            return await self._cmd_diagnose()
        return f"Unknown Phase 2 command: {command_name}"

    async def _cmd_signals(self) -> str:
        """Show latest LexiconSignal digest."""
        governor = getattr(self.bot, "market_governor", None)
        if not governor:
            return "Market governor not initialized."

        signals = getattr(governor, "_last_lexicon_signals", [])
        regime_snapshot = governor.current_regime

        if not regime_snapshot:
            return "No regime detected yet — signals unavailable."

        regime_value = regime_snapshot.regime.value

        if not signals:
            return (
                f"Regime: {regime_value.replace('_', ' ').title()}\n"
                "No lexicon signals generated. Either the signal generator "
                "is disabled or no strategies matched the confidence threshold."
            )

        # Use signal generator's formatter if available
        generator = getattr(governor, "_lexicon_signal_generator", None)
        if generator:
            return generator.format_digest(signals, regime_value)

        # Fallback manual format
        lines = [f"Regime: {regime_value.replace('_', ' ').title()}", ""]
        for sig in signals:
            lines.append(
                f"  {sig.action.upper()}: {sig.strategy_name} "
                f"(conf: {sig.confidence:.0%}) — {sig.reasoning}"
            )
        return "\n".join(lines)

    async def _cmd_ibkr(self) -> str:
        """Show IBKR paper trading positions and P&L."""
        # Check if IBKR market adapter exists on bot
        ibkr = getattr(self.bot, "_ibkr_market", None)
        if not ibkr:
            return "IBKR not initialized. Is TWS running and ibkr.enabled=true in config?"

        connected = getattr(ibkr, "_connected", False)
        if not connected:
            return "IBKR adapter exists but not connected to TWS."

        try:
            positions = await ibkr.get_positions()
            balance = await ibkr.get_balance()
        except Exception as e:
            return f"IBKR query failed: {str(e)[:200]}"

        lines = [
            "[IBKR Paper Trading]",
            f"Net Liquidation: ${balance.get('balance', 0):,.2f}",
            f"Available Funds: ${balance.get('available', 0):,.2f}",
            "",
        ]

        if not positions:
            lines.append("No open positions.")
        else:
            lines.append(f"Open Positions ({len(positions)}):")
            total_pnl = 0
            for pos in positions:
                symbol = pos.get("ticker", "?")
                qty = pos.get("contracts", 0)
                side = "LONG" if pos.get("side") == "yes" else "SHORT"
                pnl_cents = pos.get("unrealized_pnl_cents", 0)
                total_pnl += pnl_cents
                lines.append(
                    f"  {symbol} {side} x{qty} | "
                    f"P&L: ${pnl_cents / 100:.2f}"
                )
            lines.append(f"\nTotal Unrealized P&L: ${total_pnl / 100:.2f}")

        # Show lexicon order router status if available
        router = getattr(self.bot, "_lexicon_order_router", None)
        if router:
            router_orders = getattr(router, "_order_log", [])
            if router_orders:
                lines.append(f"\nLexicon Router: {len(router_orders)} orders placed")

        return "\n".join(lines)

    async def _cmd_arsenal(self) -> str:
        """Show arsenal status: top indicators, last refresh, gap analysis."""
        arsenal_text = consciousness.load_lexicon_topic("arsenal")

        if not arsenal_text or "Awaiting population" in arsenal_text:
            return (
                "[Arsenal Status]\n"
                "No indicators populated yet.\n"
                "Run: python scripts/populate_lexicon_arsenal.py\n"
                "Or wait for heartbeat auto-refresh (every 6h)."
            )

        # Extract refresh timestamp
        refresh_line = ""
        for line in arsenal_text.splitlines():
            if "Last refresh:" in line:
                refresh_line = line.split("Last refresh:")[-1].strip()
                break

        # Count top performers from table
        indicator_count = 0
        top_5_names: list = []
        for line in arsenal_text.splitlines():
            if line.strip().startswith("|") and not line.strip().startswith("|--") and "Rank" not in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2 and cells[0].isdigit():
                    indicator_count += 1
                    if len(top_5_names) < 5:
                        top_5_names.append(cells[1])

        lines = [
            "[Arsenal Status]",
            f"Last Refresh: {refresh_line or 'unknown'}",
            f"Indicators Tracked: {indicator_count}",
            "",
            "Top 5:",
        ]
        for i, name in enumerate(top_5_names, 1):
            lines.append(f"  {i}. {name}")

        return "\n".join(lines)

    async def _cmd_diagnose(self) -> str:
        """Run live API diagnostics and return results."""
        lines = ["[API Diagnostic]", ""]

        # Auth + balance
        client = getattr(self.bot, "_client", None) or getattr(self.bot, "client", None)
        if not client:
            return "[API Diagnostic]\nNo Kalshi client available."

        try:
            balance = await client.get_balance()
            cash = balance.get("balance", 0)
            portfolio = balance.get("portfolio_value", 0)
            lines.append(f"Auth: OK")
            lines.append(f"Balance: ${cash:.2f} cash, ${portfolio:.2f} portfolio")
        except Exception as e:
            lines.append(f"Auth/Balance: FAIL — {str(e)[:100]}")

        # Positions
        try:
            positions = await client.get_positions()
            lines.append(f"Positions: {len(positions)} open")
        except Exception as e:
            lines.append(f"Positions: FAIL — {str(e)[:100]}")

        # Market data — test each configured series
        lines.append("")
        try:
            from .config import get_strategy_configs
            strategy_configs = get_strategy_configs()
            tested = set()
            for sc in strategy_configs:
                if not sc.get("enabled"):
                    continue
                for market in sc.get("markets", []):
                    series = market.get("series", "")
                    if not series or series in tested or series == "*":
                        continue
                    tested.add(series)
                    try:
                        markets = await client.get_markets(
                            series_ticker=series, status="open", limit=5
                        )
                        lines.append(f"  {series}: {len(markets)} open")
                    except Exception as e:
                        lines.append(f"  {series}: FAIL — {str(e)[:80]}")
        except Exception as e:
            lines.append(f"Series test: FAIL — {str(e)[:100]}")

        # Raw fetch (no series filter)
        try:
            all_markets = await client.get_markets(status="open", limit=5)
            lines.append(f"\nAll markets (no filter): {len(all_markets)} returned")
        except Exception as e:
            lines.append(f"\nAll markets: FAIL — {str(e)[:100]}")

        # Health monitor state
        health = getattr(self.bot, "_health_monitor", None)
        if health:
            zero_count = getattr(health, "_zero_markets_counter", 0)
            if zero_count > 0:
                lines.append(f"\nZero-market streak: {zero_count} cycles")

        return "\n".join(lines)

    async def _handle_command(self, text: str, classified: dict) -> str:
        """
        Handle a command by routing to the existing CommandProcessor handlers.
        """
        command_name = classified.get("command", "")
        args = classified.get("args", {})

        if not command_name:
            return "Couldn't parse that as a command. Try again?"

        # Access command processor
        processor = getattr(self.bot, 'command_processor', None)
        if not processor:
            return "Command processor not initialized."

        handler = processor._handlers.get(command_name)
        if not handler:
            return f"Unknown command: {command_name}. Available: {', '.join(processor._handlers.keys())}"

        try:
            # Ensure args is a dict
            if not isinstance(args, dict):
                args = {}

            result = await handler(args)

            # Check for explicit error in result
            if "error" in result:
                return f"Command '{command_name}' failed: {result['error']}"

            # Format successful result as readable summary
            parts = []
            for key, val in result.items():
                if key in ("status", "error"):
                    continue
                parts.append(f"{key}: {val}")
            summary = ", ".join(parts) if parts else "executed"
            return f"Done. {command_name} -> {summary}"

        except Exception as e:
            logger.error(f"Telegram Bridge: command execution failed: {e}", exc_info=True)
            return f"Command failed: {str(e)[:200]}"

    async def _send_message(self, text: str) -> None:
        """Send a message to Eddie via Telegram Bot API. Splits long messages."""
        if not self._client or not self._token:
            return

        # Telegram has a 4096 char limit — split into chunks if needed
        chunks = self._split_message(text, max_len=4000)

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        for chunk in chunks:
            try:
                resp = await self._client.post(url, json={
                    "chat_id": self._chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                if resp.status_code != 200:
                    # Retry without parse_mode in case of formatting issues
                    resp = await self._client.post(url, json={
                        "chat_id": self._chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    })
                    if resp.status_code != 200:
                        logger.warning(f"Telegram send failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Telegram send error: {e}")

    @staticmethod
    def _split_message(text: str, max_len: int = 4000) -> List[str]:
        """Split text into chunks that fit Telegram's limit, breaking at newlines."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # Find the last newline within the limit
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                # No newline found — break at last space
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1:
                # No space either — hard break
                split_at = max_len

            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")

        return chunks

    async def _send_chat_action(self, action: str = "typing") -> None:
        """Send a chat action (typing indicator) to Telegram."""
        if not self._client or not self._token:
            return

        url = f"https://api.telegram.org/bot{self._token}/sendChatAction"
        try:
            await self._client.post(url, json={
                "chat_id": self._chat_id,
                "action": action,
            })
        except Exception:
            pass  # Non-critical

    def _load_credentials(self) -> None:
        """
        Load Telegram credentials with Dae-first priority.

        Priority chain:
        1. DAE_TELEGRAM_TOKEN (Dae's own bot: @deepstack_voice_bot)
        2. TELEGRAM_BOT_TOKEN (generic fallback)
        3. ~/.hydra/config/telegram.env (HYDRA's config, last resort)
        """
        # Dae's own token takes priority
        self._token = os.getenv("DAE_TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        # Fall back to HYDRA config
        if not self._token or not self._chat_id:
            hydra_env = Path.home() / ".hydra" / "config" / "telegram.env"
            if hydra_env.exists():
                try:
                    for line in hydra_env.read_text().splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            # Strip surrounding quotes
                            value = value.strip().strip("'\"")
                            if key == "TELEGRAM_BOT_TOKEN" and not self._token:
                                self._token = value
                            elif key == "TELEGRAM_CHAT_ID" and not self._chat_id:
                                self._chat_id = value
                except Exception as e:
                    logger.warning(f"Failed to read HYDRA telegram config: {e}")

        if self._token and self._chat_id:
            logger.info(f"Telegram Bridge: credentials loaded (chat_id: {self._chat_id[:4]}...)")
        else:
            logger.warning("Telegram Bridge: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
