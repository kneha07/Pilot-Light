"""Pilot Light Auto-Fix Pipeline.

Reads incident postmortem and transcript from Box, extracts actionable tasks,
runs Claude Code to implement fixes, and creates GitHub PRs.

Usage:
    python -m pilotlight.auto_fix [INCIDENT_ID]

If no INCIDENT_ID is given, uses the latest incident.
"""
