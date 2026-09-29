"""Serverless entrypoint for hosting platforms (Vercel's Python runtime imports ``app``).

The ASGI app is exactly the one uvicorn serves locally (``app.main:app``).
"""

from app.main import app

__all__ = ["app"]
