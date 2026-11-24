"""pytest configuration for the backend test suite.

Adds the backend/ directory to sys.path so that ``from app.services...``
imports resolve correctly when pytest is run from either the workspace root
(``pytest backend/``) or from within the backend/ directory itself.
"""
import sys
import os

# Ensure backend/ is on sys.path so ``from app.services...`` works.
_backend_dir = os.path.dirname(__file__)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
