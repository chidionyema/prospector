"""Compiling a migration plan from a probe report, and running it.

`plan.py` decides what moves, in what order, and what is knowingly left behind. Nothing here
touches the running world; the runner is the only part that does.
"""
