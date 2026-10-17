"""Pilot Light auto-fix pipeline (original by Harika).

After a postmortem, reads the postmortem and transcript from Box, extracts code tasks
(Box AI analysis plus Bedrock Nova 2 Lite), uploads auto_fix_plan.md to the incident folder,
and assigns it for review. Opt-in PR mode implements tasks with Claude Code in isolated
git worktrees and opens GitHub PRs.

Usage:
    python -m pilotlight.auto_fix [INCIDENT_ID] [--pr]
"""
