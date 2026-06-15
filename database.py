"""Compatibility wrapper for the data layer."""

from db.connection import get_db, init_db, transaction

__all__ = ["get_db", "init_db", "transaction"]
