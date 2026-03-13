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


def write_lessons(new_lessons: list[str], max_lines: int = 50) -> None:
    """
    Append AI-learned lessons to memory/lessons.md and invalidate cache.

    Maintains a dedicated "## AI-Learned" section at the end of the file.
    Compresses oldest AI-learned entries when the file exceeds max_lines.

    Args:
        new_lessons: List of lesson strings to append.
        max_lines: Maximum total lines for the file (default 50).
    """
    if not new_lessons:
        return

    file_path = _MIND_DIR / "memory" / "lessons.md"

    try:
        current = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = "# Lessons Learned\n"

    # Split into human-written section and AI-learned section
    ai_header = "## AI-Learned"
    if ai_header in current:
        parts = current.split(ai_header, 1)
        human_section = parts[0].rstrip()
        # Parse existing AI lessons (skip the header line itself)
        ai_lines = [
            line for line in parts[1].strip().splitlines()
            if line.strip() and line.strip().startswith("- ")
        ]
    else:
        human_section = current.rstrip()
        ai_lines = []

    # Append new lessons
    for lesson in new_lessons:
        clean = lesson.strip()
        if clean and not clean.startswith("- "):
            clean = f"- {clean}"
        if clean and clean not in ai_lines:
            ai_lines.append(clean)

    # Compute budget: human section line count + header + AI lines must fit
    human_line_count = len(human_section.splitlines())
    # Reserve 2 lines for the AI header (blank line + "## AI-Learned")
    ai_budget = max_lines - human_line_count - 2
    if ai_budget < 1:
        ai_budget = 5  # Always keep at least 5 AI lesson slots

    # Trim oldest AI lessons if over budget (keep newest)
    if len(ai_lines) > ai_budget:
        ai_lines = ai_lines[-ai_budget:]

    # Reassemble
    updated = f"{human_section}\n\n{ai_header}\n\n" + "\n".join(ai_lines) + "\n"

    file_path.write_text(updated, encoding="utf-8")
    invalidate_cache("memory/lessons.md")
    logger.info(f"Consciousness: wrote {len(new_lessons)} lesson(s) to memory/lessons.md")


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


# ── Lexicon (Strategy Knowledge Layer) ────────────────────────────

# Topic key -> relative path within mind/
_LEXICON_TOPIC_MAP: Dict[str, str] = {
    "buffett": "lexicon/titans/buffett-munger.md",
    "munger": "lexicon/titans/buffett-munger.md",
    "dalio": "lexicon/titans/dalio.md",
    "icahn": "lexicon/titans/icahn.md",
    "cohen": "lexicon/titans/cohen.md",
    "gill": "lexicon/titans/gill.md",
    "burry": "lexicon/titans/burry.md",
    "musk": "lexicon/titans/musk.md",
    "jobs": "lexicon/titans/jobs.md",
    "contrarian": "lexicon/eddie/playbook.md",
    "eddie": "lexicon/eddie/playbook.md",
    "playbook": "lexicon/eddie/playbook.md",
    "trending": "lexicon/regimes/trending.md",
    "mean_reverting": "lexicon/regimes/mean-reverting.md",
    "high_vol": "lexicon/regimes/high-vol.md",
    "low_vol": "lexicon/regimes/low-vol.md",
    "event": "lexicon/regimes/event-driven.md",
    "arsenal": "lexicon/arsenal/tv-top-performers.md",
}

# MarketRegime value -> regime playbook path
_REGIME_PLAYBOOK_MAP: Dict[str, str] = {
    "trending_up": "lexicon/regimes/trending.md",
    "trending_down": "lexicon/regimes/trending.md",
    "mean_reverting": "lexicon/regimes/mean-reverting.md",
    "high_vol_choppy": "lexicon/regimes/high-vol.md",
    "low_vol_calm": "lexicon/regimes/low-vol.md",
}



def load_lexicon_index() -> str:
    """
    Load strategy lexicon master index.
    ~400 tokens, always safe to include for general strategy awareness.
    """
    return _read_file("lexicon/INDEX.md")


def load_lexicon_topic(topic: str) -> str:
    """
    Load a specific lexicon topic file by key.
    ~500-800 tokens depending on topic.

    Args:
        topic: Key from _LEXICON_TOPIC_MAP (e.g., "buffett", "dalio", "trending")
    """
    path = _LEXICON_TOPIC_MAP.get(topic.lower())
    if not path:
        logger.debug(f"Lexicon: unknown topic '{topic}'")
        return ""
    return _read_file(path)


def load_lexicon_for_regime(regime: str) -> str:
    """
    Load regime playbook + TV regime map for a given MarketRegime value.
    ~800 tokens combined.

    Args:
        regime: MarketRegime value string (e.g., "trending_up", "high_vol_choppy")
    """
    playbook_path = _REGIME_PLAYBOOK_MAP.get(regime)
    if not playbook_path:
        logger.debug(f"Lexicon: no playbook for regime '{regime}'")
        return ""
    parts = [
        _read_file(playbook_path),
        _read_file("lexicon/arsenal/tv-regime-map.md"),
    ]
    return "\n\n---\n\n".join(p for p in parts if p)
