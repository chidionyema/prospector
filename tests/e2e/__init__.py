"""End-to-end tests: the whole wire, not one link of it.

Every test outside this directory grades one component against a stub of its neighbour. That is
worth having and it is not enough -- four green unit files sat over a runner that handed its
adapters an empty environment, because no test ever ran a compiled plan through an adapter that
read what the runner set. A defect at a JOIN is invisible from either side of it.

The rule for anything added here: no cloud account, no credentials, no network. Substrates are
directories and adapters are the real shell scripts. A test that needs a secret is a test that
gets skipped, and a skipped test proves nothing at 3am.
"""
