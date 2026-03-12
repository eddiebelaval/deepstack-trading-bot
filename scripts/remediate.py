#!/usr/bin/env python3
"""
Tier 2: Claude-Routed Remediation Script

Polls Dae's health status from Supabase. When persistent critical failures
are detected (2+ consecutive checks), spawns a Claude Code session to
investigate and fix the issue on a feature branch.

Run via launchd every 5 minutes:
  com.id8labs.deepstack-remediate

Safety rails:
  - 2-hour cooldown between remediation sessions for the same issue
  - Max 3 remediation sessions per day
  - Only runs on feature branches, never touches main
  - Notifies Eddie via Telegram when a fix PR is created
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Config
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BOT_REPO = Path(__file__).parent.parent
STATE_FILE = BOT_REPO / ".remediation_state.json"
COOLDOWN_HOURS = 2
MAX_SESSIONS_PER_DAY = 3
TELEGRAM_TOKEN = os.getenv("DAE_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("DAE_TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")


def load_state() -> dict:
    """Load remediation state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "last_remediation": 0,
        "sessions_today": 0,
        "today_date": "",
        "recent_issues": {},  # issue_key -> last_remediation_timestamp
    }


def save_state(state: dict) -> None:
    """Persist remediation state."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_health_status() -> dict | None:
    """Fetch latest sensory report from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
        return None

    try:
        import httpx
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/deepstack_health_status?id=eq.1&select=sensory_report,sensory_status,consecutive_critical,updated_at",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            timeout=10,
        )
        if r.status_code == 200:
            rows = r.json()
            if rows:
                return rows[0]
        else:
            print(f"Supabase fetch failed: HTTP {r.status_code}")
    except Exception as e:
        print(f"Supabase fetch error: {e}")

    return None


def fetch_remediation_queue() -> list:
    """Fetch pending remediation requests from queue table."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []

    try:
        import httpx
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/deepstack_remediation_queue?status=eq.pending&order=created_at.desc&limit=1",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def update_remediation_status(record_id: str, status: str, result: str = "") -> None:
    """Update remediation queue record status."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return

    try:
        import httpx
        httpx.patch(
            f"{SUPABASE_URL}/rest/v1/deepstack_remediation_queue?id=eq.{record_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "status": status,
                "result": result,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
    except Exception as e:
        print(f"Failed to update remediation status: {e}")


def send_telegram(message: str) -> None:
    """Send notification to Eddie via Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram not configured. Message: {message}")
        return

    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
    except Exception as e:
        print(f"Telegram send failed: {e}")


def spawn_claude_session(prompt: str, issue_key: str) -> bool:
    """Spawn a Claude Code session to fix the issue."""
    # Create feature branch
    branch_name = f"fix/dae-remediation-{int(time.time())}"
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(BOT_REPO),
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Branch creation failed: {e.stderr.decode()}")
        return False

    # Spawn Claude Code with the remediation prompt
    claude_prompt = (
        f"{prompt}\n\n"
        f"You are running as an automated remediation agent.\n"
        f"Branch: {branch_name}\n"
        f"After fixing, commit your changes with message: "
        f"'fix(dae): auto-remediate {issue_key}'\n"
        f"Do NOT push or create a PR — just commit locally."
    )

    try:
        result = subprocess.run(
            ["claude", "-p", claude_prompt, "--yes"],
            cwd=str(BOT_REPO),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute max
        )

        if result.returncode == 0:
            # Check if there are commits on this branch
            diff = subprocess.run(
                ["git", "log", "main..HEAD", "--oneline"],
                cwd=str(BOT_REPO),
                capture_output=True,
                text=True,
            )

            if diff.stdout.strip():
                # Push and create PR
                subprocess.run(
                    ["git", "push", "-u", "origin", branch_name],
                    cwd=str(BOT_REPO),
                    capture_output=True,
                    check=True,
                )

                pr_result = subprocess.run(
                    [
                        "gh", "pr", "create",
                        "--title", f"fix(dae): auto-remediate {issue_key}",
                        "--body", (
                            "## Auto-Remediation\n\n"
                            f"Triggered by persistent sensory check failures.\n\n"
                            f"**Issue:** {issue_key}\n\n"
                            f"**Claude output:**\n```\n{result.stdout[-500:]}\n```\n\n"
                            "Generated by Dae Tier 2 remediation system."
                        ),
                    ],
                    cwd=str(BOT_REPO),
                    capture_output=True,
                    text=True,
                )

                pr_url = pr_result.stdout.strip()
                send_telegram(
                    f"[Dae Remediation] Fix PR created\n"
                    f"Issue: {issue_key}\n"
                    f"PR: {pr_url}\n"
                    f"Review and merge when ready."
                )
                return True
            else:
                print("Claude session completed but no commits were made")
                # Clean up empty branch
                subprocess.run(
                    ["git", "checkout", "main"],
                    cwd=str(BOT_REPO),
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    cwd=str(BOT_REPO),
                    capture_output=True,
                )
                return False
        else:
            print(f"Claude session failed: {result.stderr[-300:]}")
            return False

    except subprocess.TimeoutExpired:
        print("Claude session timed out after 5 minutes")
        return False
    except FileNotFoundError:
        print("claude CLI not found — install Claude Code first")
        return False
    finally:
        # Always return to main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(BOT_REPO),
            capture_output=True,
        )


def main():
    """Main remediation loop — runs once per invocation (called by launchd)."""
    state = load_state()
    now = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    # Reset daily counter
    if state.get("today_date") != today:
        state["sessions_today"] = 0
        state["today_date"] = today

    # Check daily limit
    if state["sessions_today"] >= MAX_SESSIONS_PER_DAY:
        print(f"Daily limit reached ({MAX_SESSIONS_PER_DAY} sessions)")
        return

    # Check global cooldown
    if now - state.get("last_remediation", 0) < COOLDOWN_HOURS * 3600:
        remaining = COOLDOWN_HOURS * 3600 - (now - state["last_remediation"])
        print(f"Cooldown active ({remaining/60:.0f} min remaining)")
        return

    # Strategy 1: Check remediation queue (written by sensory_check.py)
    queue = fetch_remediation_queue()
    if queue:
        record = queue[0]
        prompt = record.get("prompt", "")
        failures = record.get("failures", [])
        issue_key = "|".join(f"{f['sense']}:{f['name']}" for f in failures)

        # Check issue-specific cooldown
        last_issue_time = state.get("recent_issues", {}).get(issue_key, 0)
        if now - last_issue_time < COOLDOWN_HOURS * 3600:
            print(f"Issue cooldown active for: {issue_key}")
            return

        print(f"Remediation request found: {issue_key}")
        update_remediation_status(record.get("id", ""), "in_progress")

        success = spawn_claude_session(prompt, issue_key)

        update_remediation_status(
            record.get("id", ""),
            "completed" if success else "failed",
            "PR created" if success else "No fix generated",
        )

        state["last_remediation"] = now
        state["sessions_today"] += 1
        state.setdefault("recent_issues", {})[issue_key] = now
        save_state(state)
        return

    # Strategy 2: Check health status directly (fallback if queue table doesn't exist)
    health = fetch_health_status()
    if not health:
        print("No health data available")
        return

    consecutive = health.get("consecutive_critical", 0)
    if consecutive < 2:
        print(f"No persistent criticals (consecutive={consecutive})")
        return

    # Parse the sensory report
    report_json = health.get("sensory_report", "{}")
    try:
        report = json.loads(report_json) if isinstance(report_json, str) else report_json
    except (json.JSONDecodeError, TypeError):
        print("Could not parse sensory report")
        return

    # Find Claude-routable issues
    routable = report.get("claude_routable", [])
    if not routable:
        # Fall back to critical failures
        routable = report.get("critical_failures", [])

    if not routable:
        print("No routable issues found despite critical status")
        return

    issue_key = "|".join(f"{f['sense']}:{f['name']}" for f in routable)

    # Check issue-specific cooldown
    last_issue_time = state.get("recent_issues", {}).get(issue_key, 0)
    if now - last_issue_time < COOLDOWN_HOURS * 3600:
        print(f"Issue cooldown active for: {issue_key}")
        return

    # Build prompt from health data
    prompt = (
        "Dae trading bot sensory check detected persistent failures.\n"
        "Investigate and fix the following issues:\n\n"
        + "\n".join(f"- [{f['sense']}] {f['name']}: {f.get('detail', '')}" for f in routable)
        + f"\n\nConsecutive critical checks: {consecutive}"
        + f"\n\nBot repo: {BOT_REPO}"
        + "\nSensory check: kalshi_trader/sensory_check.py"
    )

    print(f"Spawning Claude remediation for: {issue_key}")
    success = spawn_claude_session(prompt, issue_key)

    state["last_remediation"] = now
    state["sessions_today"] += 1
    state.setdefault("recent_issues", {})[issue_key] = now
    save_state(state)

    if not success:
        send_telegram(
            f"[Dae Remediation] Claude could not auto-fix:\n"
            f"{issue_key}\n"
            f"Manual investigation needed."
        )


if __name__ == "__main__":
    main()
