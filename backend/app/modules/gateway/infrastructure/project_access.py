"""Current sharing grant used by remote authoring and diagnostic reads."""

from .models import SyncProject


def is_project_shared(project_id: str) -> bool:
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        return (
            db.query(SyncProject.project_id)
            .filter(
                SyncProject.project_id == project_id,
                SyncProject.status == "enabled",
            )
            .first()
            is not None
        )
