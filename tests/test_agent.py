"""
Tests for DaeAgent — scoped cognitive agent with tool boundaries.

Covers tool execution, safety boundaries, and result structure.
"""

import json
import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from kalshi_trader.agent import (
    AgentResult,
    DaeAgent,
    _execute_read_file,
    _execute_list_files,
    _execute_query_journal,
    _execute_write_report,
    _execute_update_lessons,
    execute_tool,
    PROJECT_ROOT,
)


class TestReadFile:
    def test_reads_existing_file(self):
        result = _execute_read_file("kalshi_trader/mind/kernel/purpose.md")
        assert "Find edge" in result or "Purpose" in result

    def test_blocks_env_file(self):
        result = _execute_read_file(".env")
        assert "ERROR" in result
        assert "blocked" in result.lower()

    def test_blocks_private_key(self):
        result = _execute_read_file("kalshi_private_key.pem")
        assert "ERROR" in result

    def test_rejects_path_traversal(self):
        result = _execute_read_file("../../etc/passwd")
        assert "ERROR" in result

    def test_handles_missing_file(self):
        result = _execute_read_file("nonexistent_file.txt")
        assert "ERROR" in result
        assert "not found" in result.lower()


class TestListFiles:
    def test_lists_mind_directory(self):
        result = _execute_list_files("kalshi_trader/mind/")
        assert "kernel/" in result or "drives/" in result

    def test_rejects_outside_project(self):
        result = _execute_list_files("../../")
        assert "ERROR" in result

    def test_handles_nonexistent_dir(self):
        result = _execute_list_files("fake_directory/")
        assert "ERROR" in result


class TestQueryJournal:
    def test_allows_select(self):
        result = _execute_query_journal(
            "SELECT COUNT(*) as cnt FROM trades"
        )
        # Should either return data or "no results" — not an error about permissions
        assert "ERROR" not in result or "no such table" in result.lower()

    def test_blocks_insert(self):
        result = _execute_query_journal(
            "INSERT INTO trades (market_ticker) VALUES ('HACK')"
        )
        assert "ERROR" in result
        assert "SELECT" in result

    def test_blocks_delete(self):
        result = _execute_query_journal("DELETE FROM trades")
        assert "ERROR" in result

    def test_blocks_drop(self):
        result = _execute_query_journal("DROP TABLE trades")
        assert "ERROR" in result

    def test_blocks_update(self):
        result = _execute_query_journal(
            "UPDATE trades SET pnl_cents = 9999"
        )
        assert "ERROR" in result


class TestWriteReport:
    def test_writes_report(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kalshi_trader.agent.PROJECT_ROOT", tmp_path
        )
        reports_dir = tmp_path / "kalshi_trader" / "mind" / "reports"

        result = _execute_write_report("test-report.md", "# Test Report\nContent here.")
        assert "OK" in result
        assert (reports_dir / "test-report.md").exists()

    def test_blocks_path_traversal(self):
        result = _execute_write_report("../../../hack.md", "evil content")
        assert "ERROR" in result

    def test_blocks_directory_in_filename(self):
        result = _execute_write_report("subdir/report.md", "content")
        assert "ERROR" in result


class TestUpdateLessons:
    def test_appends_lesson(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kalshi_trader.agent.PROJECT_ROOT", tmp_path
        )
        lessons_dir = tmp_path / "kalshi_trader" / "mind" / "memory"
        lessons_dir.mkdir(parents=True)
        lessons_file = lessons_dir / "lessons.md"
        lessons_file.write_text("# Lessons\n\n- Old lesson\n")

        result = _execute_update_lessons("New lesson about regime shifts")
        assert "OK" in result

        content = lessons_file.read_text()
        assert "New lesson about regime shifts" in content
        assert "Old lesson" in content


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_dispatches_read_file(self):
        result = await execute_tool(
            "read_file",
            {"path": "kalshi_trader/mind/kernel/purpose.md"},
        )
        assert "ERROR" not in result or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_dispatches_unknown_tool(self):
        result = await execute_tool("hack_tool", {})
        assert "ERROR" in result
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_dispatches_query_journal(self):
        result = await execute_tool(
            "query_journal",
            {"query": "SELECT 1 as test"},
        )
        # Should succeed with a simple query
        assert "ERROR" not in result


class TestAgentResult:
    def test_default_fields(self):
        result = AgentResult(task="test", success=True, summary="done")
        assert result.tools_used == []
        assert result.reports_written == []
        assert result.memories_updated == []
        assert result.iterations == 0
        assert result.error is None

    def test_with_outputs(self):
        result = AgentResult(
            task="oak tree report",
            success=True,
            summary="Report written",
            tools_used=["query_journal", "write_report"],
            reports_written=["2026-03-16-oak-tree.md"],
            memories_updated=["weekly_status"],
            iterations=5,
        )
        assert len(result.tools_used) == 2
        assert result.reports_written[0] == "2026-03-16-oak-tree.md"


class TestDaeAgent:
    def test_requires_api_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                DaeAgent(api_key="")

    def test_accepts_explicit_key(self):
        agent = DaeAgent(api_key="test-key-123")
        assert agent.api_key == "test-key-123"

    def test_stores_bot_reference(self):
        bot = MagicMock()
        agent = DaeAgent(api_key="test-key", bot=bot)
        assert agent.bot is bot

    def test_system_prompt_contains_identity(self):
        agent = DaeAgent(api_key="test-key")
        prompt = agent._build_system_prompt("test task")
        assert "Dae" in prompt
        assert "SEED" in prompt
        assert "Oak Tree" in prompt
        assert "CANNOT modify code" in prompt
        assert "test task" in prompt
