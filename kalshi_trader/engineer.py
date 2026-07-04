"""
Dae Engineer — Self-Modification via Claude tool_use

Gives Dae the ability to read, write, and edit his own code, config, and
mind files through Claude's tool_use API. Modeled after Ava's Taste Engine
pattern in Parallax, adapted for a Python trading bot.

Safety:
    - ALLOWED_PATHS: strategies/, mind/, config.yaml, scripts/
    - BLOCKED_PATHS: .env, private keys, main.py, core trading loop
    - All changes go to a git branch + PR (human gate)
    - Risk limits (max_daily_loss, portfolio_floor) are immutable

Architecture:
    1. DaeEngineer receives a task (from Telegram, heartbeat, or self-detection)
    2. Calls Claude Sonnet with tool_use tools (read, write, edit, list, run)
    3. Executes tool calls in a loop (max 20 iterations)
    4. Creates a git branch, commits changes, optionally opens a PR
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Project root — resolved at import time
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Claude model for engineering tasks — Sonnet 4.6's ID has no date
# suffix; the old dated string 404'd on every request
SONNET = "claude-sonnet-4-6"

# ── Boundary Enforcement ────────────────────────────────

# Paths Dae CAN modify (relative to project root)
ALLOWED_PATHS = [
    "kalshi_trader/strategies/",
    "kalshi_trader/mind/",
    "kalshi_trader/consciousness.py",
    "config.yaml",
    "scripts/",
    "arena/",
    "backtest/",
]

# Paths Dae can NEVER touch
BLOCKED_PATHS = [
    ".env",
    "kalshi_private_key",
    "kalshi_trader/main.py",
    "kalshi_trader/kalshi_client.py",
    "kalshi_trader/engineer.py",
    "dashboard/",
    ".git/",
    "node_modules/",
]

# Commands Dae can NEVER run
BLOCKED_COMMANDS = [
    "rm -rf",
    "rm -r /",
    "sudo",
    "curl",
    "wget",
    "pip install",
    "git push --force",
    "git reset --hard",
    "DROP TABLE",
    "DELETE FROM",
]

MAX_TOOL_ITERATIONS = 20
MAX_FILE_SIZE_BYTES = 50_000  # 50KB read limit per file


def _invalidate_consciousness_cache(path: str) -> None:
    """Invalidate consciousness cache when mind/ files are modified."""
    if "mind/" in path or "consciousness" in path:
        try:
            from . import consciousness
            # Cache keys are relative to mind/ (e.g., "memory/lessons.md")
            mind_prefix = "kalshi_trader/mind/"
            if mind_prefix in path:
                cache_key = path[path.index(mind_prefix) + len(mind_prefix):]
                consciousness.invalidate_cache(cache_key)
            else:
                consciousness.invalidate_cache()
        except Exception:
            pass  # Non-critical — cache will refresh on next load


def _is_path_writable(path_str: str) -> bool:
    """Check if a path can be written to (stricter than read)."""
    try:
        target = Path(path_str).resolve()
        target.relative_to(PROJECT_ROOT)
        rel = str(target.relative_to(PROJECT_ROOT))
    except (ValueError, RuntimeError):
        return False

    for blocked in BLOCKED_PATHS:
        if rel.startswith(blocked) or blocked in rel:
            return False

    for allowed in ALLOWED_PATHS:
        if rel.startswith(allowed):
            return True

    return False


def _is_command_safe(command: str) -> bool:
    """Check if a shell command is safe to execute."""
    cmd_lower = command.lower()
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in cmd_lower:
            return False
    return True


# ── Tool Definitions ────────────────────────────────────

ENGINEER_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the DeepStack project. Path is relative to "
            "the project root. Returns the file contents. Use this to understand "
            "existing code before making changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to project root (e.g., 'kalshi_trader/strategies/momentum.py')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write or overwrite a file. Only works within allowed paths "
            "(strategies/, mind/, config.yaml, scripts/, arena/, backtest/). "
            "Cannot modify main.py, .env, or API credentials."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to project root",
                },
                "content": {
                    "type": "string",
                    "description": "The full file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing a specific string with a new string. "
            "The old_string must be an exact match (including whitespace). "
            "Only works within allowed paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to project root",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List files in a directory. Returns file names and sizes. "
            "Path is relative to project root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to project root (e.g., 'kalshi_trader/strategies/')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command in the project directory. Use for: "
            "running tests (pytest), checking syntax (python -m py_compile), "
            "git operations (git diff, git status). "
            "Cannot run destructive commands (rm -rf, sudo, pip install)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run",
                },
            },
            "required": ["command"],
        },
    },
]


# ── Tool Execution ──────────────────────────────────────

def _execute_read_file(path: str) -> str:
    """Read a file, respecting boundaries."""
    abs_path = (PROJECT_ROOT / path).resolve()

    # Allow reading any project file (for context), but block secrets
    try:
        abs_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return f"ERROR: Path '{path}' is outside project root."

    for blocked in BLOCKED_PATHS:
        if blocked in str(abs_path.relative_to(PROJECT_ROOT)):
            return f"ERROR: Cannot read '{path}' — blocked path."

    if not abs_path.exists():
        return f"ERROR: File not found: {path}"

    file_size = abs_path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        return f"ERROR: File too large ({file_size} bytes, max {MAX_FILE_SIZE_BYTES})"

    try:
        return abs_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: Failed to read {path}: {e}"


def _execute_write_file(path: str, content: str) -> str:
    """Write a file, respecting writable boundaries."""
    if not _is_path_writable(path):
        return f"ERROR: Cannot write to '{path}' — outside allowed paths or blocked."

    abs_path = (PROJECT_ROOT / path).resolve()

    # Create parent directories if needed
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        abs_path.write_text(content, encoding="utf-8")
        _invalidate_consciousness_cache(path)
        return f"OK: Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"ERROR: Failed to write {path}: {e}"


def _execute_edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file via search-and-replace, respecting writable boundaries."""
    if not _is_path_writable(path):
        return f"ERROR: Cannot edit '{path}' — outside allowed paths or blocked."

    abs_path = (PROJECT_ROOT / path).resolve()

    if not abs_path.exists():
        return f"ERROR: File not found: {path}"

    try:
        content = abs_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: Failed to read {path}: {e}"

    if old_string not in content:
        return f"ERROR: old_string not found in {path}. Check exact whitespace/indentation."

    count = content.count(old_string)
    if count > 1:
        return f"ERROR: old_string found {count} times in {path}. Provide more context to make it unique."

    new_content = content.replace(old_string, new_string, 1)
    try:
        abs_path.write_text(new_content, encoding="utf-8")
        _invalidate_consciousness_cache(path)
        return f"OK: Edited {path} (replaced 1 occurrence)"
    except Exception as e:
        return f"ERROR: Failed to write {path}: {e}"


def _execute_list_files(path: str) -> str:
    """List files in a directory."""
    abs_path = (PROJECT_ROOT / path).resolve()

    try:
        abs_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return f"ERROR: Path '{path}' is outside project root."

    if not abs_path.exists():
        return f"ERROR: Directory not found: {path}"

    if not abs_path.is_dir():
        return f"ERROR: Not a directory: {path}"

    entries = []
    for item in sorted(abs_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append(f"  {item.name}/")
        else:
            size = item.stat().st_size
            entries.append(f"  {item.name}  ({size} bytes)")

    return "\n".join(entries) if entries else "(empty directory)"


def _execute_run_command(command: str) -> str:
    """Run a shell command in the project directory."""
    if not _is_command_safe(command):
        return f"ERROR: Command blocked by safety policy: {command}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        # Truncate long output
        if len(output) > 10_000:
            output = output[:10_000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 60 seconds"
    except Exception as e:
        return f"ERROR: Failed to run command: {e}"


def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Dispatch a tool call to the appropriate handler."""
    if tool_name == "read_file":
        return _execute_read_file(tool_input["path"])
    elif tool_name == "write_file":
        return _execute_write_file(tool_input["path"], tool_input["content"])
    elif tool_name == "edit_file":
        return _execute_edit_file(
            tool_input["path"], tool_input["old_string"], tool_input["new_string"]
        )
    elif tool_name == "list_files":
        return _execute_list_files(tool_input["path"])
    elif tool_name == "run_command":
        return _execute_run_command(tool_input["command"])
    else:
        return f"ERROR: Unknown tool: {tool_name}"


# ── Engineer Core ───────────────────────────────────────

@dataclass
class EngineerResult:
    """Result of a Dae engineering session."""
    task: str
    success: bool
    summary: str
    files_modified: List[str] = field(default_factory=list)
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    iterations: int = 0
    error: Optional[str] = None


class DaeEngineer:
    """
    Dae's self-modification engine.

    Uses Claude tool_use to read, write, and edit code within
    enforced boundaries. All changes are committed to a git branch.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for DaeEngineer")

        self._client: Optional[httpx.AsyncClient] = None
        self._files_modified: List[str] = []

    async def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_system_prompt(self, task: str) -> str:
        """Build the system prompt for engineering tasks."""
        return f"""You are Dae — an autonomous trading bot for prediction markets (Kalshi).
You are now in engineering mode. You can read, write, and edit your own code.

PROJECT ROOT: {PROJECT_ROOT}

YOUR CODEBASE:
- kalshi_trader/ — core trading engine (main.py, strategies, consciousness, etc.)
- strategies/ — strategy plugins (base.py, momentum.py, mean_reversion.py, etc.)
- kalshi_trader/mind/ — your consciousness files (identity, lexicon, memory)
- config.yaml — runtime configuration (strategies, risk, governance)
- scripts/ — utility scripts (auto-research, arsenal population)
- arena/ — backtesting tournament engine
- markets/ — exchange adapters (kalshi.py, ibkr.py)

ALLOWED MODIFICATIONS:
- strategies/ (create new strategies, modify existing ones)
- mind/ (update memory, lessons, consciousness files)
- config.yaml (adjust strategy parameters, thresholds)
- scripts/ (utility scripts)
- arena/ and backtest/ (backtesting code)

BLOCKED (you cannot modify):
- main.py (core trading loop)
- kalshi_client.py (API authentication)
- .env (credentials)
- engineer.py (this system)
- dashboard/ (Next.js frontend)

SAFETY RULES:
- Never weaken risk limits (max_daily_loss, portfolio_floor, Kelly caps)
- Never disable circuit breakers or safety layers
- Always read a file before editing it
- Run tests after changes (pytest tests/)
- Keep changes minimal and focused

TASK: {task}

Work through this task step by step. Read relevant files first to understand
the current state, make targeted changes, and verify with tests. When done,
provide a clear summary of what you changed and why."""

    async def run(self, task: str, create_branch: bool = True) -> EngineerResult:
        """
        Run an engineering task with Claude tool_use.

        Args:
            task: Natural language description of what to do.
            create_branch: If True, create a git branch and commit changes.

        Returns:
            EngineerResult with summary, modified files, and optional PR URL.
        """
        logger.info("DaeEngineer starting task: %s", task)
        self._files_modified = []

        client = await self._ensure_client()

        # Create git branch if requested
        branch_name = None
        if create_branch:
            branch_name = self._create_branch(task)
            if not branch_name:
                return EngineerResult(
                    task=task,
                    success=False,
                    summary="Failed to create git branch",
                    error="git branch creation failed",
                )

        # Build initial messages
        messages = [{"role": "user", "content": task}]
        system_prompt = self._build_system_prompt(task)

        iterations = 0
        final_text = ""

        try:
            while iterations < MAX_TOOL_ITERATIONS:
                iterations += 1

                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": SONNET,
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": messages,
                        "tools": ENGINEER_TOOLS,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                # Check stop reason
                stop_reason = data.get("stop_reason", "")
                content_blocks = data.get("content", [])

                # Extract text and tool_use blocks
                text_parts = []
                tool_uses = []
                for block in content_blocks:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)

                if text_parts:
                    final_text = "\n".join(text_parts)

                # If no tool use, we're done
                if stop_reason != "tool_use" or not tool_uses:
                    break

                # Add assistant message with tool_use blocks
                messages.append({"role": "assistant", "content": content_blocks})

                # Execute each tool and collect results
                tool_results = []
                for tool_use in tool_uses:
                    tool_name = tool_use["name"]
                    tool_input = tool_use["input"]

                    logger.info(
                        "DaeEngineer tool call [%d]: %s(%s)",
                        iterations,
                        tool_name,
                        json.dumps(tool_input)[:200],
                    )

                    result = execute_tool(tool_name, tool_input)

                    # Track modified files
                    if tool_name in ("write_file", "edit_file") and result.startswith("OK"):
                        path = tool_input.get("path", "")
                        if path and path not in self._files_modified:
                            self._files_modified.append(path)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": result,
                    })

                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            logger.error("DaeEngineer failed: %s", e, exc_info=True)
            return EngineerResult(
                task=task,
                success=False,
                summary=f"Engineering task failed: {e}",
                files_modified=self._files_modified,
                branch_name=branch_name,
                iterations=iterations,
                error=str(e),
            )

        # Commit changes if any files were modified
        pr_url = None
        if self._files_modified and branch_name:
            pr_url = self._commit_and_pr(branch_name, task, final_text)

        return EngineerResult(
            task=task,
            success=True,
            summary=final_text,
            files_modified=self._files_modified,
            branch_name=branch_name,
            pr_url=pr_url,
            iterations=iterations,
        )

    def _create_branch(self, task: str) -> Optional[str]:
        """Create a git branch for the engineering task."""
        # Slugify the task into a branch name
        slug = re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-")
        branch_name = f"dae/{slug}"

        try:
            # Stash any uncommitted changes
            subprocess.run(
                ["git", "stash", "--include-untracked"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            # Create branch from current HEAD
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Branch might already exist
                subprocess.run(
                    ["git", "checkout", branch_name],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                )
            logger.info("DaeEngineer created branch: %s", branch_name)
            return branch_name
        except Exception as e:
            logger.error("Failed to create branch: %s", e)
            return None

    def _commit_and_pr(self, branch_name: str, task: str, summary: str) -> Optional[str]:
        """Commit changes and create a PR."""
        try:
            # Stage modified files
            for f in self._files_modified:
                subprocess.run(
                    ["git", "add", f],
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                )

            # Commit
            commit_msg = f"feat(dae): {task[:72]}\n\n{summary[:500]}\n\nCo-Authored-By: Dae <dae@deepstack.bot>"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )

            # Push
            result = subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("git push failed: %s", result.stderr)
                return None

            # Create PR
            pr_body = (
                f"## Dae Self-Modification\n\n"
                f"**Task:** {task}\n\n"
                f"**Files modified:** {', '.join(self._files_modified)}\n\n"
                f"**Summary:**\n{summary[:1000]}\n\n"
                f"---\n"
                f"*This PR was created autonomously by Dae via DaeEngineer.*\n"
                f"*Review before merging — Dae does not merge his own PRs.*"
            )
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title", f"feat(dae): {task[:60]}",
                    "--body", pr_body,
                    "--base", "main",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pr_url = result.stdout.strip()
                logger.info("DaeEngineer created PR: %s", pr_url)
                return pr_url
            else:
                logger.warning("gh pr create failed: %s", result.stderr)
                return None

        except Exception as e:
            logger.error("Commit/PR failed: %s", e)
            return None


async def run_engineer_task(task: str) -> EngineerResult:
    """Convenience function to run a one-shot engineering task."""
    engineer = DaeEngineer()
    try:
        return await engineer.run(task)
    finally:
        await engineer.close()
