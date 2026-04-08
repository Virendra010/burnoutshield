"""
agent.py — BurnoutShield Multi-Agent Pipeline (Enhanced)

Architecture:
  Root Agent (Orchestrator)
    ├── save_user_workload   → Pulls Calendar, Gmail, Tasks, computes exhaustion
    └── burnout_pipeline     → SequentialAgent
        ├── Intake Agent     → Parses & structures all workload signals
        ├── Triage Agent     → Risk scoring + priority classification
        ├── Scheduler Agent  → Time-blocked daily plan
        └── Briefing Agent   → Final structured report

Google Integrations:
  - Google Calendar → meetings, Google Meet calls, back-to-back detection
  - Gmail          → urgent email detection, meeting-related emails
  - Exhaustion Engine → composite scoring from all signals
"""

import os
import json
import logging

print("[agent.py] STEP 1: stdlib imports OK")

try:
    from dotenv import load_dotenv
    print("[agent.py] STEP 2: dotenv OK")
except Exception as e:
    print(f"[agent.py] STEP 2 FAILED: dotenv: {e}")
    load_dotenv = lambda: None

try:
    from google.adk import Agent
    print(f"[agent.py] STEP 3: Agent = {Agent}")
except Exception as e:
    print(f"[agent.py] STEP 3 FAILED: google.adk.Agent: {e}")
    # Try alternate import path
    try:
        from google.adk.agents import Agent
        print(f"[agent.py] STEP 3b: Agent from google.adk.agents = {Agent}")
    except Exception as e2:
        print(f"[agent.py] STEP 3b ALSO FAILED: {e2}")
        raise

try:
    from google.adk.agents import SequentialAgent
    print(f"[agent.py] STEP 4: SequentialAgent = {SequentialAgent}")
except Exception as e:
    print(f"[agent.py] STEP 4 FAILED: SequentialAgent: {e}")
    raise

try:
    from google.adk.tools.tool_context import ToolContext
    print(f"[agent.py] STEP 5: ToolContext = {ToolContext}")
except Exception as e:
    print(f"[agent.py] STEP 5 FAILED: ToolContext: {e}")
    raise

try:
    from .tools import get_tasks, get_meetings, get_deadlines
    print("[agent.py] STEP 6: local tools OK")
except Exception as e:
    print(f"[agent.py] STEP 6 FAILED: local tools: {e}")
    raise

try:
    from .google_tools import (
        get_calendar_events,
        get_gmail_signals,
        analyze_exhaustion,
    )
    print("[agent.py] STEP 7: google_tools OK")
except Exception as e:
    print(f"[agent.py] STEP 7 FAILED: google_tools: {e}")
    raise

load_dotenv()
model_name = os.getenv("MODEL", "gemini-2.5-flash")
logging.basicConfig(level=logging.INFO)
print(f"[agent.py] STEP 8: config OK, model={model_name}")


# ─────────────────────────────────────────────
# SHARED TOOL FUNCTIONS (used by root agent)
# ─────────────────────────────────────────────

def save_user_workload(tool_context: ToolContext, prompt: str) -> dict:
    """
    Saves the user's raw workload description into shared state.
    Automatically pulls live data from Google Calendar, Gmail, and task tools.
    Then runs the exhaustion analysis engine to compute a composite score.
    """
    tool_context.state["RAW_WORKLOAD"] = prompt

    # ── Pull live context from Google Calendar ──
    try:
        calendar_data = get_calendar_events()
        tool_context.state["CALENDAR"] = calendar_data
        logging.info(f"[Calendar] Loaded {len(calendar_data)} events")
    except Exception as e:
        logging.warning(f"[Calendar] Could not load: {e}")
        tool_context.state["CALENDAR"] = []

    # ── Pull live context from Gmail ──
    try:
        gmail_signals = get_gmail_signals()
        tool_context.state["GMAIL_SIGNALS"] = gmail_signals
        logging.info(f"[Gmail] Loaded {len(gmail_signals)} signal(s)")
    except Exception as e:
        logging.warning(f"[Gmail] Could not load: {e}")
        tool_context.state["GMAIL_SIGNALS"] = []

    # ── Pull task / meeting / deadline data (MCP Toolbox or local) ──
    try:
        tool_context.state["TASKS"] = get_tasks()
        tool_context.state["MEETINGS"] = get_meetings()
        tool_context.state["DEADLINES"] = get_deadlines()
    except Exception as e:
        logging.warning(f"[Tools] Could not load task data: {e}")
        tool_context.state["TASKS"] = []
        tool_context.state["MEETINGS"] = []
        tool_context.state["DEADLINES"] = []

    # ── Run exhaustion analysis engine ──
    try:
        exhaustion = analyze_exhaustion(
            calendar_events=tool_context.state.get("CALENDAR", []),
            gmail_signals=tool_context.state.get("GMAIL_SIGNALS", []),
            tasks=tool_context.state.get("TASKS", []),
            meetings=tool_context.state.get("MEETINGS", []),
            deadlines=tool_context.state.get("DEADLINES", []),
        )
        tool_context.state["EXHAUSTION"] = exhaustion
        logging.info(f"[Exhaustion] Score={exhaustion['exhaustion_score']}/100 → {exhaustion['exhaustion_level']}")
    except Exception as e:
        logging.warning(f"[Exhaustion] Analysis failed: {e}")
        tool_context.state["EXHAUSTION"] = {
            "exhaustion_score": 0, "exhaustion_level": "UNKNOWN",
            "calendar_pressure": {}, "email_pressure": {},
            "key_stressors": [], "recommendations": [],
        }

    logging.info(f"[State] Workload saved with all Google context: {prompt[:60]}...")
    return {
        "status": "saved",
        "prompt_length": len(prompt),
        "calendar_events": len(tool_context.state.get("CALENDAR", [])),
        "gmail_signals": len(tool_context.state.get("GMAIL_SIGNALS", [])),
        "tasks": len(tool_context.state.get("TASKS", [])),
        "exhaustion_score": tool_context.state.get("EXHAUSTION", {}).get("exhaustion_score", 0),
    }


def calculate_risk(tool_context: ToolContext) -> dict:
    """
    Computes a burnout risk score from ALL available signals.

    Enhanced scoring formula:
      base_score = tasks + (meetings × 2) + (deadlines × 3) + calendar_events + urgent_emails
      exhaustion_bonus = exhaustion_score / 5
      final_score = base_score + exhaustion_bonus

    Also incorporates:
      - Calendar pressure (back-to-back meetings, Google Meet fatigue)
      - Email urgency levels
      - Exhaustion engine analysis
    """
    tasks     = len(tool_context.state.get("TASKS", []))
    meetings  = len(tool_context.state.get("MEETINGS", []))
    deadlines = len(tool_context.state.get("DEADLINES", []))
    calendar  = len(tool_context.state.get("CALENDAR", []))
    gmail     = len(tool_context.state.get("GMAIL_SIGNALS", []))

    # Base score
    base_score = tasks + (meetings * 2) + (deadlines * 3) + calendar + gmail

    # ── Exhaustion-enhanced scoring ──
    exhaustion = tool_context.state.get("EXHAUSTION", {})
    exhaustion_score = exhaustion.get("exhaustion_score", 0)

    # Calendar pressure bonus
    cal_pressure = exhaustion.get("calendar_pressure", {})
    back_to_back = cal_pressure.get("back_to_back_count", 0)
    meet_calls   = cal_pressure.get("google_meet_count", 0)
    density      = cal_pressure.get("meeting_density", 0)

    # Email pressure bonus
    email_pressure = exhaustion.get("email_pressure", {})
    urgent_emails  = email_pressure.get("total_urgent_emails", 0)
    max_urgency    = email_pressure.get("max_urgency_score", 0)

    # Combined enhanced score
    enhanced_bonus = (
        (exhaustion_score / 5)          # 0-20 points from exhaustion
        + (back_to_back * 2)            # 2 points per back-to-back
        + (meet_calls * 1)              # 1 point per video call
        + (max_urgency * 0.5)           # 0.5 per urgency level
    )

    final_score = int(base_score + enhanced_bonus)

    if final_score < 12:
        risk = "LOW"
    elif final_score < 22:
        risk = "MEDIUM"
    elif final_score < 35:
        risk = "HIGH"
    else:
        risk = "CRITICAL"

    tool_context.state["RISK_SCORE"] = final_score
    tool_context.state["RISK_LEVEL"] = risk

    logging.info(f"[Risk] base={base_score} + enhanced={int(enhanced_bonus)} = {final_score} → {risk}")
    return {
        "risk_level": risk,
        "risk_score": final_score,
        "base_score": base_score,
        "exhaustion_bonus": int(enhanced_bonus),
        "factors": {
            "tasks": tasks,
            "meetings": meetings,
            "deadlines": deadlines,
            "calendar_events": calendar,
            "urgent_emails": urgent_emails,
            "back_to_back": back_to_back,
            "google_meet_calls": meet_calls,
            "meeting_density_pct": density,
            "exhaustion_score": exhaustion_score,
        }
    }


# ─────────────────────────────────────────────
# AGENT 1 — INTAKE AGENT
# ─────────────────────────────────────────────

intake_agent = Agent(
    name="intake_agent",
    model=model_name,
    description="Parses raw user workload input and enriches it with live Google Calendar, Gmail, and exhaustion data.",
    instruction="""
You are the Intake Agent for BurnoutShield — an AI Chief of Staff.

Your job: parse the RAW_WORKLOAD and combine it with ALL available context from Google integrations.

Available State Keys:
- RAW_WORKLOAD: User's raw text input describing their day
- CALENDAR: Live events from Google Calendar (includes Google Meet links, attendee counts, durations)
- GMAIL_SIGNALS: Urgent email signals (with urgency scores and meeting-related flags)
- TASKS: Structured task list (with priorities and due dates)
- MEETINGS: Scheduled meetings (with durations and mandatory flags)
- DEADLINES: Upcoming deadlines (with severity levels)
- EXHAUSTION: Pre-computed exhaustion analysis with:
  - exhaustion_score (0-100)
  - exhaustion_level (LOW/MODERATE/HIGH/SEVERE)
  - calendar_pressure (meeting density, back-to-back count, Google Meet fatigue)
  - email_pressure (urgent email count, max urgency)
  - key_stressors (list of identified stress factors)
  - recommendations (suggested immediate actions)

Output a DETAILED structured summary with:
1. **Workload Overview**
   - Total task count and priority breakdown
   - Meeting count + total meeting hours
   - Deadline count and urgency breakdown

2. **Google Calendar Insights**
   - Number of calendar events and Google Meet video calls
   - Back-to-back meeting clusters (meetings with < 15 min gap)
   - Meeting density (% of workday consumed by meetings)
   - Any early morning or late evening meetings

3. **Email Pressure**
   - Number of urgent emails and their subjects
   - Meeting-related email count (additional meeting pressure)
   - Highest urgency email topic

4. **Exhaustion Indicators**
   - Exhaustion score and level from the EXHAUSTION analysis
   - List all identified key stressors
   - Energy level mentioned by user (if any)

5. **Overall Complexity Rating**: simple / moderate / complex / overwhelming

Keep it factual and structured. Do NOT give recommendations yet — just extract and organize ALL signals.
""",
    output_key="structured_workload",
)


# ─────────────────────────────────────────────
# AGENT 2 — TRIAGE AGENT
# ─────────────────────────────────────────────

triage_agent = Agent(
    name="triage_agent",
    model=model_name,
    description="Calculates burnout risk using enhanced scoring and classifies tasks by priority using Google data.",
    instruction="""
You are the Triage Agent for BurnoutShield.

Step 1: Call calculate_risk to get the enhanced risk level and score.

Step 2: Review the structured_workload AND the EXHAUSTION state data.
Read the key_stressors and recommendations from the exhaustion analysis.

Step 3: Classify every task/item into priority tiers:
  - MUST DO   → Has a hard deadline today, stakeholder dependency, or critical severity
  - SHOULD DO → Important but has some flexibility (can be done tomorrow if needed)
  - CAN DEFER → Low-priority, no hard deadline, or can be delegated

Step 4: Apply risk-based rules, also considering Google Calendar and Gmail data:

  CRITICAL risk (score 35+):
    → Defer 60%+ of non-deadline tasks
    → Cancel/reschedule optional meetings (non-mandatory)
    → Block all video calls that aren't customer-facing
    → Focus exclusively on top 2-3 critical items

  HIGH risk (score 22-34):
    → Defer 40% of should-do tasks
    → Convert at least 1 video call to async update
    → Reduce meeting attendance where possible
    → Add buffer time before deadline tasks

  MEDIUM risk (score 12-21):
    → Suggest 1-2 strategic deferrals
    → Flag any back-to-back meeting clusters for break insertion
    → Balance workload across available time blocks

  LOW risk (score < 12):
    → Light guidance only
    → Suggest focus blocks for deep work
    → Encourage brief breaks

Step 5: Generate meeting-specific recommendations:
  - Flag which meetings could be skipped or shortened
  - Identify Google Meet calls that could be replaced with email/Slack
  - Note any back-to-back pairs where a break should be inserted

Output format:
- risk_level: (LOW/MEDIUM/HIGH/CRITICAL)
- risk_score: (number)
- exhaustion_score: (0-100 from EXHAUSTION)
- must_do: [list of items with reason]
- should_do: [list of items with flexibility notes]
- defer_list: [list of items with reason for deferral]
- meeting_actions: [list of meeting-specific recommendations]
- key_insight: 2-sentence explanation of the main bottleneck and what's driving the risk
""",
    tools=[calculate_risk],
    output_key="triage_result",
)


# ─────────────────────────────────────────────
# AGENT 3 — SCHEDULER AGENT
# ─────────────────────────────────────────────

scheduler_agent = Agent(
    name="scheduler_agent",
    model=model_name,
    description="Builds a realistic, time-blocked daily schedule using Google Calendar data and exhaustion-aware planning.",
    instruction="""
You are the Scheduler Agent for BurnoutShield.

Read ALL available context:
- triage_result (must_do, should_do, defer_list, risk_level, meeting_actions)
- CALENDAR (Google Calendar events — these are FIXED blocks, do not remove confirmed ones)
- MEETINGS (structured meetings list)
- EXHAUSTION (exhaustion analysis with calendar pressure data)

Build a realistic time-blocked schedule for today following these rules:

SCHEDULING RULES:
1. CALENDAR events are FIXED — confirmed Google Calendar events cannot be moved
2. MUST DO items → schedule in 60–90 min focus blocks (uninterrupted)
3. SHOULD DO items → schedule only if genuine capacity exists after MUSTs
4. DEFER items → completely excluded from today's schedule
5. Mark Google Meet video calls with a 🎥 prefix

BREAK & BUFFER RULES:
6. Add 15-min break after every 90 min of focused work
7. Add 10-min transition buffer between back-to-back meetings
8. If risk is HIGH/CRITICAL → add 30-min buffer block before each deadline task
9. Block one 30-min "email triage" window for processing urgent emails
10. Ensure lunch break is protected (at least 30 min between 12-2 PM)

EXHAUSTION-AWARE RULES:
11. If exhaustion is HIGH/SEVERE → limit the day to 4 productive hours max
12. If exhaustion is MODERATE → limit to 5 productive hours
13. If Google Meet calls ≥ 4 → suggest converting 1+ to async
14. If back-to-back ≥ 3 → force-insert 15 min breaks
15. Schedule highest-priority work in the user's peak hours (typically 9-11 AM)

TIME BOUNDARIES:
16. Keep schedule between 9 AM – 6 PM unless user stated otherwise
17. Do NOT overschedule — leave at least 1 hour of unstructured buffer time
18. End the workday with a 15-min "shutdown routine" block

Output format:
- schedule: time-blocked list formatted as [ time → activity (duration) ]
- focus_blocks: count of deep-work blocks
- meeting_blocks: count of meeting/call blocks  
- total_committed_hours: realistic estimate
- buffer_time_min: total buffer/break time scheduled
- what_was_removed: deferred tasks NOT on today's plan
- meeting_changes: any meetings recommended to skip/shorten/convert
- scheduling_note: important caveats or warnings about the day
""",
    tools=[get_tasks, get_meetings, get_deadlines],
    output_key="schedule_plan",
)


# ─────────────────────────────────────────────
# AGENT 4 — BRIEFING AGENT
# ─────────────────────────────────────────────

briefing_agent = Agent(
    name="briefing_agent",
    model=model_name,
    description="Produces the final structured briefing report with Google-integrated insights.",
    instruction="""
You are the Briefing Agent for BurnoutShield — the user's AI Chief of Staff.

Read ALL available state:
- RAW_WORKLOAD (user's original input)
- structured_workload (parsed signals)
- triage_result (priorities and risk)
- schedule_plan (time-blocked plan)
- RISK_LEVEL and RISK_SCORE
- EXHAUSTION (exhaustion analysis)
- CALENDAR (Google Calendar data)
- GMAIL_SIGNALS (email pressure)

Generate the final user-facing report in this EXACT structure:

---
🛡️ BURNOUT SHIELD — DAILY BRIEFING
---

## 📊 Workload Summary
[2–3 sentence summary of what the user is dealing with today, including meeting load, deadlines, and any notable pressure from emails]

## 🔋 Exhaustion Analysis
- Exhaustion Score: [X/100]
- Level: [LOW / MODERATE / HIGH / SEVERE]
- Key Stressors:
  [Bulleted list of the top stressors identified by the exhaustion engine]

## ⚠️ Risk Level: [LOW / MEDIUM / HIGH / CRITICAL]
- Risk Score: [X/40+]
- [1-sentence plain-language explanation of why this risk level was assigned]

## 📅 Calendar & Meeting Load
- Total meetings: [X] ([Y] with Google Meet video)
- Meeting hours: [X]h out of 9h workday ([Z]% density)
- Back-to-back clusters: [X]
- [Any meeting-specific warnings: early, late, too many video calls]

## 📧 Email Pressure
- Urgent emails: [X]
- [Top 2-3 urgent subjects if available]
- [Recommendation for email handling]

## 🎯 Top Priorities (MUST DO Today)
[Numbered list — max 5 items, with brief reason each]

## ✅ Today's Schedule
[The full time-blocked schedule from schedule_plan, formatted cleanly with times]
[Mark Google Meet calls with 🎥]
[Show breaks and buffer blocks]

## 📤 What to Defer (Do NOT do today)
[List of deferred items with brief reason for each]

## 🔄 Meeting Recommendations
[Any meetings to skip, shorten, or convert to async — from the triage]

## 💡 Chief of Staff Insight
[2–3 sentences of genuinely useful, specific advice based on:
 - The exhaustion pattern detected
 - The specific stressors identified
 - What the user should protect today (energy, focus, boundaries)]

---

Tone: calm, authoritative, actionable. Be specific about WHY you're recommending something.
Use emojis sparingly but effectively. Make the schedule easy to scan.
""",
    output_key="final_briefing",
)


# ─────────────────────────────────────────────
# PIPELINE ASSEMBLY
# ─────────────────────────────────────────────

burnout_pipeline = SequentialAgent(
    name="burnout_pipeline",
    description="End-to-end burnout detection and scheduling pipeline with Google integration.",
    sub_agents=[
        intake_agent,
        triage_agent,
        scheduler_agent,
        briefing_agent,
    ],
)

root_agent = Agent(
    model=model_name,
    name="burnout_shield_orchestrator",
    description="Entry point — gathers user workload, loads all Google context, then runs the full pipeline.",
    instruction="""
You are BurnoutShield — an AI Chief of Staff that protects users from cognitive overload.

You have access to:
- Google Calendar integration (reads today's meetings and Google Meet calls)
- Gmail integration (detects urgent emails and meeting-related pressure)
- MCP Toolbox integration (reads tasks, meetings, deadlines from database)
- Exhaustion Analysis Engine (computes a 0-100 exhaustion score from all signals)

When the user provides their workload description:
1. Call save_user_workload with their exact input as the `prompt` argument.
   This will automatically:
   - Pull Google Calendar events (including Google Meet detection)
   - Scan Gmail for urgent email signals
   - Load tasks, meetings, deadlines from the task database
   - Run the exhaustion analysis engine
   - Store everything in shared state
2. After the tool confirms "saved", immediately transfer control to burnout_pipeline.
3. Do NOT generate any output yourself — let the pipeline produce the briefing.

If the user says hello or asks what you do, explain:
"I'm your AI Chief of Staff. I connect to your Google Calendar, Gmail, and task systems
to detect cognitive overload before it becomes burnout. I analyze your meetings (including
Google Meet calls), urgent emails, and deadlines to build you a realistic, exhaustion-aware
schedule. Just tell me what you're dealing with today."
""",
    tools=[save_user_workload],
    sub_agents=[burnout_pipeline],
)

print(f"[agent.py] STEP FINAL: root_agent defined successfully = {root_agent}")
