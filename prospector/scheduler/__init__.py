"""Always-on, unattended generation daemon and its automated safety backstop.

The daemon runs with no human in the loop (founder decision, 2026-06-20). The two automated
rails in `guard.py` — a hard daily spend ceiling and a filesystem PAUSE kill switch — are what
bound it in place of human supervision. See specs/launch-hardening-execution.md WS2.
"""
