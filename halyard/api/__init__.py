"""HTTP surface. Thin: validation, dependency wiring and error mapping only."""

from .app import create_app

__all__ = ["create_app"]
