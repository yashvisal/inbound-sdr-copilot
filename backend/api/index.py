"""Vercel serverless entrypoint. Vercel's Python runtime serves this ASGI app."""

from app.main import app

__all__ = ["app"]
