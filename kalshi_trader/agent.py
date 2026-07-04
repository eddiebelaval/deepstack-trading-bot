"""
Dae Agent — Scoped Autonomous Agent with Cognitive Tools

Extends DaeEngineer's tool_use pattern with research and reporting tools.
The engineer modifies code; the agent THINKS — queries data, researches
markets, writes reports, and reasons through multi-step problems.

Safety Boundary (Approach B):
    CAN:  read files, query journal, query Supabase, web search,
          write reports/lessons, read/update long-term memory
    CANNOT: modify strategy code, change risk params, alter config.yaml,
            execute git operations, touch .env or credentials

Architecture:
    1. Receives a task (from Telegram, heartbeat, or scheduled)
    2. Calls Claude Sonnet with AGENT_TOOLS (cognitive tools only)
    3. Executes tool calls in a loop (max 15 iterations)
    4. Returns structured result (no git branch — reports, not code)
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Claude model — Sonnet 4.6's ID has no date suffix; the old dated
# string 404'd on every request, silently killing the DaeAgent layer
SONNET = "claude-sonnet-4-6"

MAX_TOOL_ITERATIONS = 15


# ── Tool Definitions ────────────────────────────────────

AGENT_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the DeepStack project. Path relative to project root. "
            "Use for reading mind/ files, config, strategy code, reports, lessons."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to project root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List files in a directory. Returns names and sizes. "
            "Path relative to project root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to project root",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "query_journal",
        "description": (
            "Query the SQLite trade journal (trade_journal.db). Run a SELECT query "
            "to analyze trades, performance, P&L, win rates, etc. "
            "Tables: trades (market_ticker, side, action, contracts, price_cents, "
            "fill_price_cents, pnl_cents, strategy, exit_reason, created_at, "
            "paper_trade, order_id). "
            "Only SELECT queries allowed — no INSERT/UPDATE/DELETE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query against trade_journal.db",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_supabase",
        "description": (
            "Query the Supabase database (DeepStack cloud tables). "
            "Available tables: deepstack_positions, deepstack_orders, deepstack_fills, "
            "deepstack_captains_log, deepstack_strategy_status, deepstack_health_status, "
            "deepstack_governance_log, deepstack_settlements, deepstack_long_term_memory, "
            "deepstack_backtest_results. Only SELECT queries allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Table name (e.g., 'deepstack_long_term_memory')",
                },
                "select": {
                    "type": "string",
                    "description": "Columns to select (PostgREST format, e.g., 'key,value,category')",
                },
                "filter": {
                    "type": "string",
                    "description": "PostgREST filter (e.g., 'category=eq.identity'). Optional.",
                },
                "order": {
                    "type": "string",
                    "description": "Order by (e.g., 'created_at.desc'). Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 50).",
                },
            },
            "required": ["table", "select"],
        },
    },
    {
        "name": "read_long_term_memory",
        "description": (
            "Read all entries from Dae's long-term memory (Supabase). "
            "Returns key-value pairs organized by category. "
            "Use this to recall persistent facts about mission, phase, strategy, risk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "update_long_term_memory",
        "description": (
            "Update or create an entry in Dae's long-term memory. "
            "Upserts on key — if the key exists, updates the value. "
            "Categories: identity, capital, strategy, risk, planning, reporting, observation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Memory key (e.g., 'phase', 'lesson_regime_shift')",
                },
                "value": {
                    "type": "string",
                    "description": "The fact or observation to store",
                },
                "category": {
                    "type": "string",
                    "description": "Category: identity, capital, strategy, risk, planning, reporting, observation",
                },
            },
            "required": ["key", "value", "category"],
        },
    },
    {
        "name": "write_report",
        "description": (
            "Write a report file to kalshi_trader/mind/reports/. "
            "Used for Oak Tree Reports, analysis summaries, investigation findings. "
            "Files are markdown. Use descriptive filenames like '2026-03-16-oak-tree-week-1.md'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Report filename (e.g., '2026-03-16-oak-tree-week-1.md')",
                },
                "content": {
                    "type": "string",
                    "description": "Report content in markdown",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "update_lessons",
        "description": (
            "Append or update a lesson in kalshi_trader/mind/memory/lessons.md. "
            "Reads the current file, appends the new lesson, and compresses if "
            "the file exceeds 50 lines (per standing order)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson": {
                    "type": "string",
                    "description": "The lesson to record (1-2 lines, actionable)",
                },
            },
            "required": ["lesson"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for market news, economic data, or trading context. "
            "Returns summarized search results. Use for: checking market conditions, "
            "researching events that might affect positions, understanding regime shifts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'Fed rate decision March 2026')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_bot_state",
        "description": (
            "Get Dae's current operational state: balance, positions, daily P&L, "
            "regime, strategy health, risk state, health status. "
            "Returns the same self-knowledge context used for Telegram responses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── Tool Execution ──────────────────────────────────────

MAX_FILE_SIZE_BYTES = 50_000

# Paths the agent can NEVER read (secrets)
BLOCKED_READ_PATHS = [".env", "kalshi_private_key"]


def _execute_read_file(path: str) -> str:
    """Read a file, blocking only secrets."""
    abs_path = (PROJECT_ROOT / path).resolve()

    try:
        abs_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return f"ERROR: Path '{path}' is outside project root."

    for blocked in BLOCKED_READ_PATHS:
        if blocked in str(abs_path.relative_to(PROJECT_ROOT)):
            return f"ERROR: Cannot read '{path}' — blocked."

    if not abs_path.exists():
        return f"ERROR: File not found: {path}"

    if abs_path.stat().st_size > MAX_FILE_SIZE_BYTES:
        return f"ERROR: File too large (max {MAX_FILE_SIZE_BYTES} bytes)"

    try:
        return abs_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


def _execute_list_files(path: str) -> str:
    """List files in a directory."""
    abs_path = (PROJECT_ROOT / path).resolve()

    try:
        abs_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return f"ERROR: Path '{path}' is outside project root."

    if not abs_path.is_dir():
        return f"ERROR: Not a directory: {path}"

    entries = []
    for item in sorted(abs_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append(f"  {item.name}/")
        else:
            entries.append(f"  {item.name}  ({item.stat().st_size} bytes)")

    return "\n".join(entries) if entries else "(empty)"


def _execute_query_journal(query: str) -> str:
    """Execute a SELECT query against the trade journal."""
    # Safety: only SELECT allowed
    normalized = query.strip().upper()
    if not normalized.startswith("SELECT"):
        return "ERROR: Only SELECT queries allowed on trade journal."

    for forbidden in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]:
        if forbidden in normalized:
            return f"ERROR: {forbidden} not allowed on trade journal."

    db_path = PROJECT_ROOT / "trade_journal.db"
    if not db_path.exists():
        return "ERROR: trade_journal.db not found."

    try:
        # Open read-only via URI mode — defense-in-depth against writes
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query)
            rows = cursor.fetchmany(100)  # Cap at 100 rows

            if not rows:
                return "(no results)"

            # Format as table
            columns = [desc[0] for desc in cursor.description]
            result_lines = [" | ".join(columns)]
            result_lines.append("-" * len(result_lines[0]))
            for row in rows:
                result_lines.append(" | ".join(str(row[col]) for col in columns))

            output = "\n".join(result_lines)
            if len(output) > 8000:
                output = output[:8000] + "\n... (truncated)"
            return output
        finally:
            conn.close()

    except Exception as e:
        return f"ERROR: Query failed: {e}"


async def _execute_query_supabase(
    table: str,
    select: str,
    filter_str: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Query Supabase via REST API."""
    supabase_url = os.getenv("SUPABASE_URL", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not service_key:
        return "ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set."

    # Whitelist tables
    allowed_tables = [
        "deepstack_positions", "deepstack_orders", "deepstack_fills",
        "deepstack_captains_log", "deepstack_strategy_status",
        "deepstack_health_status", "deepstack_governance_log",
        "deepstack_settlements", "deepstack_long_term_memory",
        "deepstack_backtest_results", "deepstack_daily_summary",
        "deepstack_remediation_queue",
    ]
    if table not in allowed_tables:
        return f"ERROR: Table '{table}' not in allowed list: {', '.join(allowed_tables)}"

    # Validate PostgREST params to prevent injection
    _safe_postgrest = re.compile(r'^[a-zA-Z0-9_,.*()!]+$')
    if not _safe_postgrest.match(select):
        return "ERROR: Invalid characters in select parameter."
    if filter_str and not re.match(r'^[a-zA-Z0-9_.,=<>!& ]+$', filter_str):
        return "ERROR: Invalid characters in filter parameter."
    if order and not re.match(r'^[a-zA-Z0-9_.,]+$', order):
        return "ERROR: Invalid characters in order parameter."

    url = f"{supabase_url}/rest/v1/{table}?select={select}"
    if filter_str:
        url += f"&{filter_str}"
    if order:
        url += f"&order={order}"
    url += f"&limit={limit}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return "(no results)"

            return json.dumps(data, indent=2, default=str)[:8000]

    except Exception as e:
        return f"ERROR: Supabase query failed: {e}"


async def _execute_read_ltm() -> str:
    """Read all long-term memory entries."""
    return await _execute_query_supabase(
        table="deepstack_long_term_memory",
        select="key,value,category",
        order="category,key",
        limit=100,
    )


async def _execute_update_ltm(key: str, value: str, category: str) -> str:
    """Upsert a long-term memory entry."""
    supabase_url = os.getenv("SUPABASE_URL", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not service_key:
        return "ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set."

    url = f"{supabase_url}/rest/v1/deepstack_long_term_memory?on_conflict=key"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                json={
                    "key": key,
                    "value": value,
                    "category": category,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            resp.raise_for_status()
            return f"OK: Stored '{key}' in long-term memory (category: {category})"

    except Exception as e:
        return f"ERROR: Failed to update long-term memory: {e}"


def _execute_write_report(filename: str, content: str) -> str:
    """Write a report to mind/reports/."""
    # Sanitize filename
    if ".." in filename or "/" in filename:
        return "ERROR: Filename cannot contain '..' or '/'"

    reports_dir = PROJECT_ROOT / "kalshi_trader" / "mind" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / filename

    try:
        report_path.write_text(content, encoding="utf-8")
        return f"OK: Report written to mind/reports/{filename} ({len(content)} bytes)"
    except Exception as e:
        return f"ERROR: Failed to write report: {e}"


def _execute_update_lessons(lesson: str) -> str:
    """Append a lesson to lessons.md, compressing if over 50 lines."""
    lessons_path = PROJECT_ROOT / "kalshi_trader" / "mind" / "memory" / "lessons.md"

    try:
        content = lessons_path.read_text(encoding="utf-8") if lessons_path.exists() else ""
        lines = content.strip().split("\n")

        # Append the new lesson
        lines.append(f"- {lesson}")

        # Compress if over 50 lines (per standing order)
        if len(lines) > 50:
            # Keep header (first 5 lines) + last 44 lines + new lesson
            header = lines[:5]
            recent = lines[-44:]
            lines = header + ["", "*(older lessons compressed)*", ""] + recent

        new_content = "\n".join(lines) + "\n"
        lessons_path.write_text(new_content, encoding="utf-8")

        # Invalidate consciousness cache
        try:
            from . import consciousness
            consciousness.invalidate_cache("memory/lessons.md")
        except Exception:
            pass

        return f"OK: Lesson recorded ({len(lines)} total lines)"

    except Exception as e:
        return f"ERROR: Failed to update lessons: {e}"


async def _execute_web_search(query: str) -> str:
    """Search the web via DuckDuckGo HTML (no API key needed)."""
    try:
        search_url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                search_url,
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            )
            resp.raise_for_status()

            # Extract text snippets from results (basic HTML parsing)
            text = resp.text
            results = []
            # Find result snippets between <a class="result__snippet"> tags
            snippets = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</a>',
                text,
                re.DOTALL,
            )
            titles = re.findall(
                r'class="result__a"[^>]*>(.*?)</a>',
                text,
                re.DOTALL,
            )

            for i, (title, snippet) in enumerate(zip(titles[:8], snippets[:8])):
                # Strip HTML tags
                clean_title = re.sub(r"<[^>]+>", "", title).strip()
                clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                results.append(f"{i+1}. {clean_title}\n   {clean_snippet}")

            if results:
                return "\n\n".join(results)
            else:
                return f"No results found for: {query}"

    except Exception as e:
        return f"ERROR: Web search failed: {e}"


async def _execute_get_bot_state(bot) -> str:
    """Get current bot state via self_knowledge."""
    try:
        from .self_knowledge import gather_self_knowledge
        return await gather_self_knowledge(bot)
    except Exception as e:
        return f"ERROR: Failed to gather bot state: {e}"


async def execute_tool(tool_name: str, tool_input: Dict[str, Any], bot=None) -> str:
    """Dispatch a tool call to the appropriate handler."""
    if tool_name == "read_file":
        return _execute_read_file(tool_input["path"])
    elif tool_name == "list_files":
        return _execute_list_files(tool_input["path"])
    elif tool_name == "query_journal":
        return _execute_query_journal(tool_input["query"])
    elif tool_name == "query_supabase":
        return await _execute_query_supabase(
            table=tool_input["table"],
            select=tool_input["select"],
            filter_str=tool_input.get("filter"),
            order=tool_input.get("order"),
            limit=tool_input.get("limit", 50),
        )
    elif tool_name == "read_long_term_memory":
        return await _execute_read_ltm()
    elif tool_name == "update_long_term_memory":
        return await _execute_update_ltm(
            key=tool_input["key"],
            value=tool_input["value"],
            category=tool_input["category"],
        )
    elif tool_name == "write_report":
        return _execute_write_report(tool_input["filename"], tool_input["content"])
    elif tool_name == "update_lessons":
        return _execute_update_lessons(tool_input["lesson"])
    elif tool_name == "web_search":
        return await _execute_web_search(tool_input["query"])
    elif tool_name == "get_bot_state":
        return await _execute_get_bot_state(bot)
    else:
        return f"ERROR: Unknown tool: {tool_name}"


# ── Agent Core ──────────────────────────────────────────

@dataclass
class AgentResult:
    """Result of a Dae agent session."""
    task: str
    success: bool
    summary: str
    tools_used: List[str] = field(default_factory=list)
    reports_written: List[str] = field(default_factory=list)
    memories_updated: List[str] = field(default_factory=list)
    iterations: int = 0
    error: Optional[str] = None


class DaeAgent:
    """
    Dae's cognitive agent — thinks, researches, reports.

    Unlike DaeEngineer (code modification), DaeAgent is for reasoning:
    - Investigate why trades failed
    - Write Oak Tree Reports
    - Research market conditions
    - Update long-term memory with observations
    - Analyze performance trends

    No git operations. No code modification. Read + reason + report.
    """

    def __init__(self, api_key: Optional[str] = None, bot=None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for DaeAgent")

        self.bot = bot
        self._client: Optional[httpx.AsyncClient] = None
        self._tools_used: List[str] = []
        self._reports_written: List[str] = []
        self._memories_updated: List[str] = []

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
        """Build system prompt for agent tasks."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        return f"""You are Dae — an autonomous prediction market trading bot on Kalshi.
You are now in agent mode. You can research, analyze, and report — but NOT modify code.

Current time: {now}

YOUR CAPABILITIES:
- Read any project file (mind/, strategies/, config, reports)
- Query the SQLite trade journal (trade history, P&L, win rates)
- Query Supabase cloud tables (positions, governance, captain's log, long-term memory)
- Search the web for market news and context
- Write reports (Oak Tree Reports, analysis summaries)
- Update lessons learned (mind/memory/lessons.md)
- Read and update long-term memory (persistent facts in Supabase)
- Get your own current operational state (balance, positions, regime)

YOUR CONSTRAINTS:
- You CANNOT modify code, config.yaml, or strategy files
- You CANNOT change risk parameters or trading behavior
- You CANNOT execute git operations or shell commands
- You are a THINKER, not an ENGINEER. For code changes, use DaeEngineer.

YOUR IDENTITY:
- Voice: Sarcastic, sharp, teaches by showing the work. Hard edges but never cruel.
- Philosophy: Oak Tree Principles (capital preservation, 70% reserve, think in centuries)
- Mission: Turn $159.64 into generational wealth through compounding small edges
- Phase: SEED ($0-$500). Proven edges only.

TASK: {task}

Work through this systematically. Use tools to gather data before drawing conclusions.
When writing reports, use markdown. When updating memory, be concise and factual.
End with a clear summary of what you found and what you did."""

    async def run(self, task: str) -> AgentResult:
        """
        Run an agent task with Claude tool_use.

        Args:
            task: Natural language description of what to investigate/report.

        Returns:
            AgentResult with summary, tools used, and outputs.
        """
        logger.info("DaeAgent starting task: %s", task)
        self._tools_used = []
        self._reports_written = []
        self._memories_updated = []

        client = await self._ensure_client()

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
                        "tools": AGENT_TOOLS,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                stop_reason = data.get("stop_reason", "")
                content_blocks = data.get("content", [])

                text_parts = []
                tool_uses = []
                for block in content_blocks:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)

                if text_parts:
                    final_text = "\n".join(text_parts)

                if stop_reason != "tool_use" or not tool_uses:
                    break

                messages.append({"role": "assistant", "content": content_blocks})

                tool_results = []
                for tool_use in tool_uses:
                    tool_name = tool_use["name"]
                    tool_input = tool_use["input"]

                    logger.info(
                        "DaeAgent tool [%d]: %s(%s)",
                        iterations,
                        tool_name,
                        json.dumps(tool_input)[:200],
                    )

                    result = await execute_tool(tool_name, tool_input, bot=self.bot)

                    # Track usage
                    if tool_name not in self._tools_used:
                        self._tools_used.append(tool_name)
                    if tool_name == "write_report" and result.startswith("OK"):
                        self._reports_written.append(tool_input.get("filename", ""))
                    if tool_name == "update_long_term_memory" and result.startswith("OK"):
                        self._memories_updated.append(tool_input.get("key", ""))

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": result,
                    })

                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            logger.error("DaeAgent failed: %s", e, exc_info=True)
            return AgentResult(
                task=task,
                success=False,
                summary=f"Agent task failed: {e}",
                tools_used=self._tools_used,
                iterations=iterations,
                error=str(e),
            )

        return AgentResult(
            task=task,
            success=True,
            summary=final_text,
            tools_used=self._tools_used,
            reports_written=self._reports_written,
            memories_updated=self._memories_updated,
            iterations=iterations,
        )


async def run_agent_task(task: str, bot=None) -> AgentResult:
    """Convenience function to run a one-shot agent task."""
    agent = DaeAgent(bot=bot)
    try:
        return await agent.run(task)
    finally:
        await agent.close()
