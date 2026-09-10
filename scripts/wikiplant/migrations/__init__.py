"""Versioned detached, deterministic data migrations. Never provider calls."""

from .v1_to_v2 import MigrationResult, migrate_instance

__all__ = ["MigrationResult", "migrate_instance"]
