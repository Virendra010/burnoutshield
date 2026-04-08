"""
tools.py — BurnoutShield Tool Layer (Enhanced)

Provides get_tasks, get_meetings, get_deadlines.

Priority order:
  1. MCP Toolbox (BigQuery) — if TOOLBOX_URL is set in .env
  2. Local mock data  — fallback for development

To activate MCP Toolbox:
  - Start the MCP Toolbox server: ./toolbox --tools-file tools.yaml
  - Set TOOLBOX_URL=http://127.0.0.1:5000 in burnout_agent/.env

BigQuery schema expected:
  burnoutshield_db.tasks       (id, user_id, task, priority, due, category, created_at)
  burnoutshield_db.meetings    (id, user_id, time, title, duration_min, mandatory, date)
  burnoutshield_db.deadlines   (id, user_id, task, due, severity, created_at)
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
TOOLBOX_URL = os.getenv("TOOLBOX_URL", "")

# ── Try to load real MCP Toolbox client ──────────────────────────────────────
_toolbox_client = None

if TOOLBOX_URL:
    try:
        from toolbox_core import ToolboxSyncClient
        _toolbox_client = ToolboxSyncClient(TOOLBOX_URL)
        _mcp_tools = _toolbox_client.load_toolset("burnout_toolset")
        logging.info(f"[MCP Toolbox] Connected to {TOOLBOX_URL}")
    except Exception as e:
        logging.warning(f"[MCP Toolbox] Could not connect ({e}) — falling back to local data")
        _toolbox_client = None


# ── Local mock data (used when MCP is unavailable) ───────────────────────────
# These are realistic examples that simulate a high-pressure day

_LOCAL_TASKS = [
    {"id": "t1",  "task": "Finish Q2 project report",             "priority": "high",   "due": "today",     "category": "work",     "estimate_min": 90},
    {"id": "t2",  "task": "Prepare client demo presentation",     "priority": "high",   "due": "today",     "category": "work",     "estimate_min": 60},
    {"id": "t3",  "task": "Code review for PR #42 (auth module)", "priority": "high",   "due": "today",     "category": "work",     "estimate_min": 45},
    {"id": "t4",  "task": "Reply to pending stakeholder emails",  "priority": "medium", "due": "today",     "category": "admin",    "estimate_min": 30},
    {"id": "t5",  "task": "Update API documentation",             "priority": "medium", "due": "this week", "category": "work",     "estimate_min": 60},
    {"id": "t6",  "task": "Team 1:1 prep notes",                  "priority": "medium", "due": "today",     "category": "meetings", "estimate_min": 15},
    {"id": "t7",  "task": "Expense report submission",            "priority": "low",    "due": "this week", "category": "admin",    "estimate_min": 20},
    {"id": "t8",  "task": "Research new testing framework",       "priority": "low",    "due": "next week", "category": "work",     "estimate_min": 45},
    {"id": "t9",  "task": "Onboarding doc for new hire",          "priority": "medium", "due": "tomorrow",  "category": "work",     "estimate_min": 40},
    {"id": "t10", "task": "Fix CI/CD pipeline flaky test",        "priority": "high",   "due": "today",     "category": "work",     "estimate_min": 30},
]

_LOCAL_MEETINGS = [
    {"id": "m1", "time": "09:30 AM", "title": "Daily standup",            "duration_min": 15,  "mandatory": True,  "type": "recurring", "has_video": True},
    {"id": "m2", "time": "10:00 AM", "title": "Sprint planning",          "duration_min": 90,  "mandatory": True,  "type": "recurring", "has_video": True},
    {"id": "m3", "time": "11:30 AM", "title": "1:1 with Manager",         "duration_min": 30,  "mandatory": True,  "type": "recurring", "has_video": True},
    {"id": "m4", "time": "02:00 PM", "title": "Client demo call",         "duration_min": 60,  "mandatory": True,  "type": "one-time",  "has_video": True},
    {"id": "m5", "time": "03:15 PM", "title": "Design review",            "duration_min": 45,  "mandatory": False, "type": "optional",  "has_video": False},
    {"id": "m6", "time": "04:30 PM", "title": "Engineering sync",         "duration_min": 60,  "mandatory": False, "type": "recurring", "has_video": True},
]

_LOCAL_DEADLINES = [
    {"id": "d1", "task": "Q2 project report",                "due": "today",     "severity": "critical", "stakeholder": "VP Engineering"},
    {"id": "d2", "task": "Client demo presentation",         "due": "today",     "severity": "critical", "stakeholder": "Client (Acme Corp)"},
    {"id": "d3", "task": "PR #42 review",                    "due": "today",     "severity": "high",     "stakeholder": "Release team"},
    {"id": "d4", "task": "Quarterly OKR update",             "due": "tomorrow",  "severity": "high",     "stakeholder": "HR / Manager"},
    {"id": "d5", "task": "API documentation update",         "due": "this week", "severity": "medium",   "stakeholder": "DevRel team"},
]


# ── Public API ────────────────────────────────────────────────────────────────

def get_tasks() -> list[dict]:
    """
    Returns the user's task list.
    Uses MCP Toolbox (BigQuery) if available, otherwise returns local mock data.
    """
    if _toolbox_client:
        try:
            result = _toolbox_client.run_tool("get_tasks", {})
            logging.info(f"[MCP] get_tasks → {len(result)} rows")
            return result
        except Exception as e:
            logging.warning(f"[MCP] get_tasks failed: {e}")

    logging.info(f"[Local] get_tasks → {len(_LOCAL_TASKS)} tasks")
    return _LOCAL_TASKS


def get_meetings() -> list[dict]:
    """
    Returns the user's scheduled meetings.
    Uses MCP Toolbox (BigQuery) if available, otherwise returns local mock data.
    """
    if _toolbox_client:
        try:
            result = _toolbox_client.run_tool("get_meetings", {})
            logging.info(f"[MCP] get_meetings → {len(result)} rows")
            return result
        except Exception as e:
            logging.warning(f"[MCP] get_meetings failed: {e}")

    logging.info(f"[Local] get_meetings → {len(_LOCAL_MEETINGS)} meetings")
    return _LOCAL_MEETINGS


def get_deadlines() -> list[dict]:
    """
    Returns the user's upcoming deadlines.
    Uses MCP Toolbox (BigQuery) if available, otherwise returns local mock data.
    """
    if _toolbox_client:
        try:
            result = _toolbox_client.run_tool("get_deadlines", {})
            logging.info(f"[MCP] get_deadlines → {len(result)} rows")
            return result
        except Exception as e:
            logging.warning(f"[MCP] get_deadlines failed: {e}")

    logging.info(f"[Local] get_deadlines → {len(_LOCAL_DEADLINES)} deadlines")
    return _LOCAL_DEADLINES
