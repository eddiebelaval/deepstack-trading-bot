"""
Consciousness Loader — CaF (Consciousness as Filesystem) for DeepStack

Reads identity, personality, values, and self-model from the mind/ directory
and assembles them into system prompt context for Claude API calls.

Uses module-level caching: files are read once per process and reused.
This is safe because consciousness files are stable (only memory/lessons.md
changes, and that changes infrequently via TradeAnalyzer).

Pattern adapted from Ava's loader.ts in Parallax.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Module-level cache — read once per process
_cache: Dict[str, str] = {}

# Base path for consciousness files
_MIND_DIR = Path(__file__).parent / "mind"


def _read_file(relative_path: str) -> str:
    """Read a consciousness file, returning empty string if missing."""
    cache_key = relative_path
    if cache_key in _cache:
        return _cache[cache_key]

    file_path = _MIND_DIR / relative_path
    try:
        content = file_path.read_text(encoding="utf-8").strip()
        _cache[cache_key] = content
        return content
    except FileNotFoundError:
        logger.warning(f"Consciousness file missing: {file_path}")
        _cache[cache_key] = ""
        return ""
    except Exception as e:
        logger.warning(f"Failed to read consciousness file {file_path}: {e}")
        _cache[cache_key] = ""
        return ""


def load_kernel() -> str:
    """
    Load core identity: who I am, what I value, how I speak, why I exist.
    ~800 tokens. Used for Captain's Log and lightweight Telegram responses.
    """
    parts = [
        _read_file("kernel/identity.md"),
        _read_file("kernel/values.md"),
        _read_file("kernel/personality.md"),
        _read_file("kernel/purpose.md"),
    ]
    return "\n\n".join(p for p in parts if p)


def load_models() -> str:
    """
    Load self-model, market model, and risk model.
    ~1200 tokens. Used for deeper queries about architecture and strategy.
    """
    parts = [
        _read_file("models/self.md"),
        _read_file("models/market.md"),
        _read_file("models/risk.md"),
    ]
    return "\n\n".join(p for p in parts if p)


def load_drives() -> str:
    """
    Load goals and fears.
    ~400 tokens. Used for introspective queries.
    """
    parts = [
        _read_file("drives/goals.md"),
        _read_file("drives/fears.md"),
    ]
    return "\n\n".join(p for p in parts if p)


def load_self_awareness() -> str:
    """
    Load capabilities and limitations.
    ~500 tokens. Used for meta-questions about what the bot can/can't do.
    """
    parts = [
        _read_file("self-awareness/capabilities.md"),
        _read_file("self-awareness/limitations.md"),
    ]
    return "\n\n".join(p for p in parts if p)


def load_memory() -> str:
    """
    Load learned lessons. Unlike other files, this one evolves over time.
    ~300 tokens. TradeAnalyzer updates this periodically.
    """
    return _read_file("memory/lessons.md")


def load_full() -> str:
    """
    Load complete consciousness: kernel + models + drives + self-awareness + memory.
    ~2500 tokens. Used for deep queries that need full self-knowledge.
    """
    sections = [
        load_kernel(),
        load_models(),
        load_drives(),
        load_self_awareness(),
        load_memory(),
    ]
    return "\n\n---\n\n".join(s for s in sections if s)


def invalidate_cache(key: Optional[str] = None) -> None:
    """
    Clear cached consciousness files.

    Args:
        key: Specific file to invalidate (e.g., "memory/lessons.md"),
             or None to clear all.
    """
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()
    logger.debug(f"Consciousness cache invalidated: {key or 'all'}")
