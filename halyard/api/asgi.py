"""ASGI entry point: ``uvicorn halyard.api.asgi:app``."""

from .app import create_app

app = create_app()
