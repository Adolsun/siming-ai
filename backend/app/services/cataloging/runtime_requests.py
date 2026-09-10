"""Transaction-owned requests consumed by the registered cataloging worker lifecycle."""
from sqlalchemy.orm import Session

def request_cataloging_runtime_stop(db: Session, job_id: str, *, terminal: bool) -> None:
    """Stop a provider only after the author's control change commits."""
    db.info.setdefault("cataloging_runtime_stops", {})[job_id] = terminal
