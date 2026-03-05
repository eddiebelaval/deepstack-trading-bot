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
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from . import consciousness
from .self_knowledge import gather_self_knowledge

logger = logging.getLogger(__name__)

# Rate limit: minimum seconds between Claude API calls from Telegram
_MIN_RESPONSE_INTERVAL = 10.0

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

        logger.info("Telegram Bridge connected")

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
            # Classify intent
            classified = await self._classify_message(text)
            intent = classified.get("type", "chat")
            args = classified.get("args", [])

            logger.info(f"Telegram Bridge: classified as '{intent}' (confidence: {classified.get('confidence', '?')})")

            if intent == "command":
                response = await self._handle_command(text, classified)
            elif intent == "query":
                response = await self._handle_query(text)
            else:
                # chat, query-like intents, and anything else
                response = await self._handle_query(text)

            if response:
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

- query: Questions about bot state, performance, strategy, reasoning, or markets. Examples:
  - "what's the scoop?" / "how are we doing?" / "status" / "give me a rundown"
  - "why is momentum disabled?" / "what happened today?"
  - "how's our kelly looking?" / "what's the win rate on mean reversion?"
  - "any trades today?" / "what's the balance?"

- chat: Casual conversation, reactions, thoughts, strategy discussion. Examples:
  - "nice" / "keep it up" / "that's rough"
  - "I was thinking about adding a new strategy"
  - "markets are wild today huh"

Respond with ONLY valid JSON. No explanation.
{"type": "command|query|chat", "confidence": "high|medium|low", ...}
For commands, include "command" and "args" fields.
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

    async def _handle_query(self, text: str) -> str:
        """
        Handle a query by gathering self-knowledge + consciousness
        and asking Claude Sonnet for an intelligent response.
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

        system_prompt = f"""{identity}

---

# Current State (Live Data)

{self_knowledge}

---

# Response Guidelines

You are Dae, responding to Eddie via Telegram.
- Be yourself: laconic, data-driven, dry wit when earned.
- Answer with specifics from your current state above. Use real numbers.
- Keep responses under 300 words. Most should be 50-150.
- Never fabricate data. If you don't know, say so.
- Think Hemingway at a trading terminal, not a chatbot.
- No emojis. No exclamation marks unless something truly exceptional happened.
- If Eddie asks about strategy reasoning, explain the logic behind governance decisions.
- If he asks about performance, lead with P&L and win rates.
- If he just says "what's the scoop" or "how are we doing", give a concise portfolio summary."""

        try:
            resp = await self._claude_client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": SONNET,
                    "max_tokens": 500,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": text}],
                },
            )
            resp.raise_for_status()

            data = resp.json()
            return data.get("content", [{}])[0].get("text", "").strip() or "No response generated."

        except Exception as e:
            logger.error(f"Telegram Bridge: query response failed: {e}")
            return f"Failed to generate response: {str(e)[:100]}"

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
            status = result.get("status", "unknown")
            detail = result.get("detail", "")

            if status == "ok":
                return f"Done. {detail}" if detail else f"Command '{command_name}' executed."
            else:
                return f"Command '{command_name}' failed: {detail or status}"

        except Exception as e:
            logger.error(f"Telegram Bridge: command execution failed: {e}", exc_info=True)
            return f"Command failed: {str(e)[:200]}"

    async def _send_message(self, text: str) -> None:
        """Send a message to Eddie via Telegram Bot API."""
        if not self._client or not self._token:
            return

        # Telegram has a 4096 char limit per message
        if len(text) > 4000:
            text = text[:3997] + "..."

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            resp = await self._client.post(url, json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            if resp.status_code != 200:
                # Retry without parse_mode in case of formatting issues
                resp = await self._client.post(url, json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                })
                if resp.status_code != 200:
                    logger.warning(f"Telegram send failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")

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
