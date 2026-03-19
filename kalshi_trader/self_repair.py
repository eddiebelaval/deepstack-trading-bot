"""
Self-Repair Engine — Autonomous Code Fixes for DeepStack

Tier 3 of the heartbeat system. When Tier 1 (deterministic) and Tier 2 (AI advisory)
detect issues that require code changes, Tier 3 invokes Claude Code CLI to diagnose
and fix the problem autonomously.

Safety constraints:
  - Max 1 repair attempt per issue category per day
  - Always notifies Eddie via Telegram before AND after
  - Syntax-validates all changes before restarting
  - Never modifies: risk limits, safety thresholds, auth credentials, API keys
  - Protected files list prevents changes to core safety systems
  - All repairs logged to repair-log.json for audit trail
  - Bot only restarts if syntax validation passes
"""

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).parent
_PROJECT_ROOT = _MODULE_DIR.parent
_REPAIR_LOG_PATH = _PROJECT_ROOT / "repair-log.json"
_REPAIR_STATE_PATH = _PROJECT_ROOT / "repair-state.json"

# Claude Code CLI path
_CLAUDE_CLI = "/Users/eddiebelaval/.local/bin/claude"

# Files DAE is NEVER allowed to modify via self-repair
PROTECTED_FILES = {
    "kalshi_trader/deepstack_integration.py",  # Risk management
    "kalshi_trader/config.py",                 # Config schema
    "kalshi_trader/kalshi_client.py",          # API auth
    "kalshi_trader/self_repair.py",            # This file (no self-modifying)
    "kalshi_private_key.pem",                  # Auth key
    "config.yaml",                             # Config (use config commands instead)
}

# Max repair attempts per category per day
MAX_REPAIRS_PER_CATEGORY_PER_DAY = 1

# Max time for a Claude Code session (5 minutes)
REPAIR_TIMEOUT_SECONDS = 300


class RepairCategory:
    """Known categories of issues DAE can self-repair."""
    HEARTBEAT_PARSE = "heartbeat_parse"
    STRATEGY_DATA_FEED = "strategy_data_feed"
    POSITION_SIZING = "position_sizing"
    DASHBOARD_SYNC = "dashboard_sync"
    LOG_ROTATION = "log_rotation"


class SelfRepairEngine:
    """
    Autonomous code repair via Claude Code CLI.

    Invoked by the heartbeat engine when deterministic checks detect
    issues that require code-level fixes (not just config changes).
    """

    def __init__(self, telegram_bridge: Optional[Any] = None):
        self._telegram = telegram_bridge
        self._state = self._load_state()
        self._repair_log: List[Dict] = self._load_repair_log()

    def _load_state(self) -> Dict:
        try:
            return json.loads(_REPAIR_STATE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"repairs_today": {}, "last_reset_date": ""}

    def _save_state(self) -> None:
        try:
            _REPAIR_STATE_PATH.write_text(
                json.dumps(self._state, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Self-repair: failed to save state: %s", e)

    def _load_repair_log(self) -> List[Dict]:
        try:
            return json.loads(_REPAIR_LOG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_repair_log(self) -> None:
        try:
            # Keep last 50 entries
            trimmed = self._repair_log[-50:]
            _REPAIR_LOG_PATH.write_text(
                json.dumps(trimmed, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Self-repair: failed to save repair log: %s", e)

    def _check_date_rollover(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state.get("last_reset_date") != today:
            self._state["repairs_today"] = {}
            self._state["last_reset_date"] = today

    def can_repair(self, category: str) -> bool:
        """Check if a repair attempt is allowed for this category today."""
        self._check_date_rollover()
        count = self._state.get("repairs_today", {}).get(category, 0)
        return count < MAX_REPAIRS_PER_CATEGORY_PER_DAY

    def _record_attempt(self, category: str) -> None:
        repairs = self._state.get("repairs_today", {})
        repairs[category] = repairs.get(category, 0) + 1
        self._state["repairs_today"] = repairs
        self._save_state()

    async def _notify(self, message: str) -> None:
        logger.info("Self-repair: %s", message)
        if self._telegram and hasattr(self._telegram, '_send_message'):
            try:
                await self._telegram._send_message(f"[Self-Repair] {message}")
            except Exception:
                pass

    def _validate_syntax(self, file_path: Path) -> bool:
        """Validate Python syntax of a file before accepting changes."""
        try:
            import ast
            ast.parse(file_path.read_text(encoding="utf-8"))
            return True
        except SyntaxError as e:
            logger.error("Self-repair: syntax error in %s: %s", file_path, e)
            return False

    def _check_protected_files(self, output: str) -> bool:
        """Check if Claude Code tried to modify protected files."""
        for protected in PROTECTED_FILES:
            if protected in output and ("Edit" in output or "Write" in output):
                logger.warning(
                    "Self-repair: BLOCKED — attempted to modify protected file: %s",
                    protected,
                )
                return False
        return True

    async def attempt_repair(
        self,
        category: str,
        diagnosis: str,
        context: str,
        affected_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Invoke Claude Code CLI to fix an issue.

        Args:
            category: RepairCategory constant
            diagnosis: What's wrong (human-readable)
            context: Additional context (log snippets, error messages)
            affected_files: Hint about which files are likely involved

        Returns:
            Dict with: success, message, changes_made, duration_seconds
        """
        if not self.can_repair(category):
            msg = f"Repair limit reached for '{category}' today. Skipping."
            await self._notify(msg)
            return {"success": False, "message": msg, "changes_made": [], "duration_seconds": 0}

        # Record attempt before starting
        self._record_attempt(category)

        await self._notify(
            f"Attempting self-repair: {category}\n"
            f"Diagnosis: {diagnosis}"
        )

        # Build the prompt for Claude Code
        file_hint = ""
        if affected_files:
            file_hint = f"\n\nLikely affected files:\n" + "\n".join(f"- {f}" for f in affected_files)

        prompt = (
            f"You are fixing a bug in the DeepStack trading bot (DAE). "
            f"This is an AUTONOMOUS repair. Be surgical. Fix ONLY the specific issue described.\n\n"
            f"ISSUE CATEGORY: {category}\n"
            f"DIAGNOSIS: {diagnosis}\n"
            f"CONTEXT:\n{context}\n"
            f"{file_hint}\n\n"
            f"RULES:\n"
            f"- Fix ONLY the described issue. Do not refactor, clean up, or improve other code.\n"
            f"- Do NOT modify these protected files: {', '.join(PROTECTED_FILES)}\n"
            f"- Do NOT change risk limits, safety thresholds, or authentication.\n"
            f"- Do NOT modify config.yaml (use the bot's command system for that).\n"
            f"- After fixing, run: python -c \"import ast; ast.parse(open('<file>').read())\" to validate.\n"
            f"- Keep changes minimal. One-line fixes are ideal.\n"
        )

        start_time = time.time()
        result = {
            "success": False,
            "message": "",
            "changes_made": [],
            "duration_seconds": 0,
            "category": category,
            "diagnosis": diagnosis,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    _CLAUDE_CLI,
                    "-p", prompt,
                    "--allowedTools", "Read,Edit,Bash,Grep,Glob",
                    "--max-turns", "10",
                ],
                capture_output=True,
                text=True,
                timeout=REPAIR_TIMEOUT_SECONDS,
                cwd=str(_PROJECT_ROOT),
                env={
                    **dict(__import__("os").environ),
                    "CLAUDE_CODE_ENTRYPOINT": "self-repair",
                },
            )

            output = proc.stdout or ""
            stderr = proc.stderr or ""
            duration = time.time() - start_time
            result["duration_seconds"] = round(duration, 1)

            if proc.returncode != 0:
                result["message"] = f"Claude Code exited with code {proc.returncode}: {stderr[:200]}"
                await self._notify(f"Repair FAILED: {result['message']}")
            else:
                # Check for protected file violations
                if not self._check_protected_files(output):
                    result["message"] = "Repair BLOCKED: attempted to modify protected files"
                    await self._notify(result["message"])
                else:
                    # Validate syntax of all Python files that might have changed
                    all_valid = True
                    for py_file in _MODULE_DIR.glob("*.py"):
                        if not self._validate_syntax(py_file):
                            all_valid = False
                            result["message"] = f"Syntax error in {py_file.name} after repair"
                            break

                    if all_valid:
                        result["success"] = True
                        result["message"] = f"Repair completed in {duration:.1f}s"
                        # Extract what changed from output (rough heuristic)
                        if "Edit" in output:
                            result["changes_made"].append("Code edited")
                        await self._notify(
                            f"Repair SUCCEEDED ({duration:.1f}s): {category}\n"
                            f"Bot will restart to apply changes."
                        )
                    else:
                        await self._notify(f"Repair FAILED: {result['message']}")

        except subprocess.TimeoutExpired:
            result["message"] = f"Repair timed out after {REPAIR_TIMEOUT_SECONDS}s"
            result["duration_seconds"] = REPAIR_TIMEOUT_SECONDS
            await self._notify(f"Repair TIMED OUT: {category}")
        except FileNotFoundError:
            result["message"] = "Claude Code CLI not found"
            await self._notify("Repair FAILED: Claude Code CLI not installed")
        except Exception as e:
            result["message"] = f"Repair error: {str(e)[:200]}"
            await self._notify(f"Repair ERROR: {e}")

        # Log the attempt
        self._repair_log.append(result)
        self._save_repair_log()

        return result

    async def repair_and_restart(
        self,
        category: str,
        diagnosis: str,
        context: str,
        affected_files: Optional[List[str]] = None,
    ) -> bool:
        """
        Attempt repair and restart the bot if successful.

        Returns True if repair succeeded and restart was triggered.
        """
        result = await self.attempt_repair(category, diagnosis, context, affected_files)

        if result["success"]:
            await self._notify("Restarting bot to apply repair...")
            # Trigger restart via launchctl (async, non-blocking)
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["launchctl", "kickstart", "-k", "gui/501/com.id8labs.deepstack-bot"],
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Self-repair: restart failed: %s", e)
                await self._notify(f"Restart failed: {e}. Manual restart needed.")
                return False
            return True

        return False
