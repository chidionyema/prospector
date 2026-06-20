"""popdd_agent — backward-compat re-export. PopddAgent moved to popdd.agent.

Usage (old style):
    from popdd_agent import PopddAgent

Recommended (new style):
    from popdd.agent import PopddAgent
"""

from popdd.agent import PopddAgent  # noqa

__all__ = ["PopddAgent"]
