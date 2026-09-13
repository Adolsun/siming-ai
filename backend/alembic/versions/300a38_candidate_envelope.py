"""Remove redundant legacy transport fields from retained candidate payloads."""
import json

from alembic import op
import sqlalchemy as sa

revision = "300a38_candidate_envelope"
down_revision = "300a37_cataloging_plan"
branch_labels = None
depends_on = None


def _migrate_payload(text, *, item_type, operation, target_id):
    if not text:
        return text
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(payload, dict):
        return text
    original = dict(payload)
    # These were copied from the row's typed envelope by the old writer.
    # Conflicting values and all business fields stay visible for validation;
    # no model identity, missing field or enum is guessed by this migration.
    for key, value in (("type", item_type), ("item_type", item_type),
                       ("action", operation), ("operation", operation)):
        if value is not None and payload.get(key) == value:
            payload.pop(key, None)
    if target_id and payload.get("target_id") == target_id and payload.get("id") == target_id:
        payload.pop("target_id")
    return json.dumps(payload, ensure_ascii=False) if payload != original else text


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "cataloging_candidates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cataloging_candidates")}
    required = {"id", "item_type", "operation", "target_id", "raw_payload", "edited_payload"}
    if not required <= columns:
        return
    rows = connection.execute(sa.text(
        "SELECT id,item_type,operation,target_id,raw_payload,edited_payload FROM cataloging_candidates"
    )).mappings()
    for row in rows:
        updated = {
            field: _migrate_payload(row[field], item_type=row["item_type"],
                                    operation=row["operation"], target_id=row["target_id"])
            for field in ("raw_payload", "edited_payload")
        }
        if any(updated[field] != row[field] for field in updated):
            connection.execute(sa.text(
                "UPDATE cataloging_candidates SET raw_payload=:raw_payload,edited_payload=:edited_payload WHERE id=:id"
            ), {"id": row["id"], **updated})


def downgrade():
    # Redundant envelopes have no business meaning to restore.
    pass
