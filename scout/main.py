"""ASGI entrypoint.

Uvicorn is pointed at "scout.main:app". This module stays intentionally
thin - it only builds the app via the factory in scout.api.app.
"""

from scout.api.app import create_app

app = create_app()
