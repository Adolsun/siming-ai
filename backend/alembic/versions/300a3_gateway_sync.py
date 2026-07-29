"""Add the user-owned Gateway pairing and synchronization schema.

Revision ID: 300a3_gateway_sync
Revises: 300a2_content_sync
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "300a3_gateway_sync"
down_revision = "300a2_content_sync"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _table_names()

    if "gateway_identities" not in tables:
        op.create_table(
            "gateway_identities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("instance_id", sa.String(length=36), nullable=False),
            sa.Column("display_name", sa.String(length=200), nullable=False),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("private_key_encrypted", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("fingerprint"),
            sa.UniqueConstraint("instance_id"),
        )

    if "gateway_devices" not in tables:
        op.create_table(
            "gateway_devices",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("platform", sa.String(length=40), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("public_key", sa.Text(), nullable=True),
            sa.Column("public_key_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("capabilities_json", sa.JSON(), nullable=True),
            sa.Column("protocol_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_gateway_devices_status", "gateway_devices", ["status"])
        op.create_index(
            "ix_gateway_devices_last_seen", "gateway_devices", ["last_seen_at"]
        )

    if "gateway_pairing_sessions" not in tables:
        op.create_table(
            "gateway_pairing_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("secret_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("requested_device_id", sa.String(length=36), nullable=True),
            sa.Column("created_by_device_id", sa.String(length=36), nullable=True),
            sa.Column("created_from", sa.String(length=80), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["created_by_device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["requested_device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("secret_hash"),
        )
        op.create_index(
            "ix_gateway_pairing_status_expiry",
            "gateway_pairing_sessions",
            ["status", "expires_at"],
        )

    if "gateway_access_tokens" not in tables:
        op.create_table(
            "gateway_access_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("device_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["device_id"], ["gateway_devices.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_gateway_access_device_expiry",
            "gateway_access_tokens",
            ["device_id", "expires_at"],
        )

    if "gateway_refresh_tokens" not in tables:
        op.create_table(
            "gateway_refresh_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("device_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("rotated_to_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["device_id"], ["gateway_devices.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["rotated_to_id"], ["gateway_refresh_tokens.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_gateway_refresh_device_expiry",
            "gateway_refresh_tokens",
            ["device_id", "expires_at"],
        )

    if "sync_projects" not in tables:
        op.create_table(
            "sync_projects",
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("manifest_json", sa.JSON(), nullable=True),
            sa.Column("initial_revision", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("enabled_at", sa.DateTime(), nullable=True),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("project_id"),
        )
        op.create_index("ix_sync_projects_status", "sync_projects", ["status"])

    if "sync_capture_jobs" not in tables:
        op.create_table(
            "sync_capture_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("operation", sa.String(length=20), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_sync_capture_status_created",
            "sync_capture_jobs",
            ["status", "created_at"],
        )
        op.create_index(
            "ix_sync_capture_project_created",
            "sync_capture_jobs",
            ["project_id", "created_at"],
        )

    if "sync_entity_states" not in tables:
        op.create_table(
            "sync_entity_states",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("modified_by_device_id", sa.String(length=36), nullable=True),
            sa.Column("server_modified_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["modified_by_device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id", "entity_type", "entity_id", name="uq_sync_entity_identity"
            ),
        )
        op.create_index(
            "ix_sync_entity_project_revision",
            "sync_entity_states",
            ["project_id", "revision"],
        )
        op.create_index(
            "ix_sync_entity_project_type",
            "sync_entity_states",
            ["project_id", "entity_type"],
        )

    if "sync_changes" not in tables:
        op.create_table(
            "sync_changes",
            sa.Column("revision", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("mutation_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("operation", sa.String(length=20), nullable=False),
            sa.Column("base_revision", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("device_id", sa.String(length=36), nullable=True),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("revision"),
            sa.UniqueConstraint("mutation_id"),
        )
        op.create_index(
            "ix_sync_changes_project_revision",
            "sync_changes",
            ["project_id", "revision"],
        )
        op.create_index(
            "ix_sync_changes_device_revision",
            "sync_changes",
            ["device_id", "revision"],
        )

    if "sync_conflicts" not in tables:
        op.create_table(
            "sync_conflicts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("mutation_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("device_id", sa.String(length=36), nullable=True),
            sa.Column("client_base_revision", sa.Integer(), nullable=False),
            sa.Column("server_revision", sa.Integer(), nullable=False),
            sa.Column(
                "client_operation",
                sa.String(length=20),
                nullable=False,
                server_default="upsert",
            ),
            sa.Column(
                "server_operation",
                sa.String(length=20),
                nullable=False,
                server_default="upsert",
            ),
            sa.Column("client_payload_json", sa.JSON(), nullable=True),
            sa.Column("server_payload_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("resolution_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("mutation_id"),
        )
        op.create_index(
            "ix_sync_conflicts_project_status",
            "sync_conflicts",
            ["project_id", "status"],
        )
        op.create_index(
            "ix_sync_conflicts_entity",
            "sync_conflicts",
            ["project_id", "entity_type", "entity_id"],
        )
    else:
        conflict_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("sync_conflicts")
        }
        if "client_operation" not in conflict_columns:
            op.add_column(
                "sync_conflicts",
                sa.Column(
                    "client_operation",
                    sa.String(length=20),
                    nullable=False,
                    server_default="upsert",
                ),
            )
        if "server_operation" not in conflict_columns:
            op.add_column(
                "sync_conflicts",
                sa.Column(
                    "server_operation",
                    sa.String(length=20),
                    nullable=False,
                    server_default="upsert",
                ),
            )

    if "sync_tombstones" not in tables:
        op.create_table(
            "sync_tombstones",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("deleted_by_device_id", sa.String(length=36), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["deleted_by_device_id"], ["gateway_devices.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "entity_type",
                "entity_id",
                name="uq_sync_tombstone_identity",
            ),
        )
        op.create_index(
            "ix_sync_tombstones_expiry", "sync_tombstones", ["expires_at"]
        )


def downgrade() -> None:
    for table_name in (
        "sync_tombstones",
        "sync_conflicts",
        "sync_changes",
        "sync_entity_states",
        "sync_capture_jobs",
        "sync_projects",
        "gateway_refresh_tokens",
        "gateway_access_tokens",
        "gateway_pairing_sessions",
        "gateway_devices",
        "gateway_identities",
    ):
        if table_name in _table_names():
            op.drop_table(table_name)
