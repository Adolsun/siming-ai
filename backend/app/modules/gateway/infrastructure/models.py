"""Persistence models for pairing, devices, and revisioned synchronization."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.database.models_support import generate_uuid
from app.database.session import Base


class GatewayIdentity(Base):
    """Stable, user-owned identity used to fingerprint one Gateway install."""

    __tablename__ = "gateway_identities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    instance_id = Column(String(36), nullable=False, unique=True)
    display_name = Column(String(200), nullable=False, default="司命 Gateway")
    public_key = Column(Text, nullable=False)
    private_key_encrypted = Column(Text, nullable=False)
    fingerprint = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class GatewayDevice(Base):
    """A paired phone, desktop, or compute node."""

    __tablename__ = "gateway_devices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(120), nullable=False)
    platform = Column(String(40), nullable=False)
    role = Column(String(30), nullable=False, default="member")
    status = Column(String(30), nullable=False, default="pending")
    public_key = Column(Text, nullable=True)
    public_key_fingerprint = Column(String(64), nullable=True)
    capabilities_json = Column(JSON, nullable=True)
    protocol_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_gateway_devices_status", "status"),
        Index("ix_gateway_devices_last_seen", "last_seen_at"),
    )


class GatewayPairingSession(Base):
    """Short-lived one-time pairing proof; the raw secret is never stored."""

    __tablename__ = "gateway_pairing_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    secret_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(30), nullable=False, default="created")
    requested_device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_from = Column(String(80), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_gateway_pairing_status_expiry", "status", "expires_at"),)


class GatewayAccessToken(Base):
    """Short-lived opaque access token stored only as a digest."""

    __tablename__ = "gateway_access_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_gateway_access_device_expiry", "device_id", "expires_at"),)


class GatewayRefreshToken(Base):
    """Rotating refresh token; rotation revokes the predecessor atomically."""

    __tablename__ = "gateway_refresh_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    rotated_to_id = Column(
        String(36),
        ForeignKey("gateway_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_gateway_refresh_device_expiry", "device_id", "expires_at"),)


class SyncProject(Base):
    """Explicit per-project opt-in and migration verification state."""

    __tablename__ = "sync_projects"

    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(String(30), nullable=False, default="migrating")
    manifest_json = Column(JSON, nullable=True)
    initial_revision = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    enabled_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (Index("ix_sync_projects_status", "status"),)


class SyncCaptureJob(Base):
    """Transactional outbox from canonical Gateway writes to the change log."""

    __tablename__ = "sync_capture_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False)
    operation = Column(String(20), nullable=False)
    payload_json = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_sync_capture_status_created", "status", "created_at"),
        Index("ix_sync_capture_project_created", "project_id", "created_at"),
    )


class SyncEntityState(Base):
    """Gateway-authoritative latest snapshot for one synchronized entity."""

    __tablename__ = "sync_entity_states"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    payload_json = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    modified_by_device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    server_modified_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "entity_type",
            "entity_id",
            name="uq_sync_entity_identity",
        ),
        Index("ix_sync_entity_project_revision", "project_id", "revision"),
        Index("ix_sync_entity_project_type", "project_id", "entity_type"),
    )


class SyncChange(Base):
    """Append-only ordered change log used as every device pull cursor."""

    __tablename__ = "sync_changes"

    revision = Column(Integer, primary_key=True, autoincrement=True)
    mutation_id = Column(String(64), nullable=False, unique=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False)
    operation = Column(String(20), nullable=False)
    base_revision = Column(Integer, nullable=False)
    payload_json = Column(JSON, nullable=True)
    content_hash = Column(String(64), nullable=False)
    device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_sync_changes_project_revision", "project_id", "revision"),
        Index("ix_sync_changes_device_revision", "device_id", "revision"),
    )


class SyncConflict(Base):
    """Permanent preservation of both snapshots when base revisions diverge."""

    __tablename__ = "sync_conflicts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    mutation_id = Column(String(64), nullable=False, unique=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False)
    device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_base_revision = Column(Integer, nullable=False)
    server_revision = Column(Integer, nullable=False)
    client_operation = Column(String(20), nullable=False, default="upsert")
    server_operation = Column(String(20), nullable=False, default="upsert")
    client_payload_json = Column(JSON, nullable=True)
    server_payload_json = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False, default="open")
    resolution_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_sync_conflicts_project_status", "project_id", "status"),
        Index("ix_sync_conflicts_entity", "project_id", "entity_type", "entity_id"),
    )


class SyncTombstone(Base):
    """Deletion marker retained long enough for long-offline replicas."""

    __tablename__ = "sync_tombstones"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    deleted_by_device_id = Column(
        String(36),
        ForeignKey("gateway_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    deleted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "entity_type",
            "entity_id",
            name="uq_sync_tombstone_identity",
        ),
        Index("ix_sync_tombstones_expiry", "expires_at"),
    )


__all__ = [
    "GatewayAccessToken",
    "GatewayDevice",
    "GatewayIdentity",
    "GatewayPairingSession",
    "GatewayRefreshToken",
    "SyncChange",
    "SyncCaptureJob",
    "SyncConflict",
    "SyncEntityState",
    "SyncProject",
    "SyncTombstone",
]
