"""The migration kit. Product-agnostic by rule, not by intention.

Nothing under `kit/` may name a product. `tests/unit/test_kit_names_no_product.py`
fails if one appears. Everything a run needs to know about a particular business
arrives through a project declaration — see `kit/projects/schema.py`.
"""
