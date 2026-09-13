"""Read-only shared-project authorization query."""

from ..application.project_access import is_project_shared

__all__ = ["is_project_shared"]
