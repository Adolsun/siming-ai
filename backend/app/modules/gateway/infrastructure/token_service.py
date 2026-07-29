"""Opaque access and rotating refresh-token behavior for Gateway services."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.architecture.uow import commit_session
from app.core.exceptions import UnauthorizedError
from app.modules.gateway.application.contracts import SYNC_PROTOCOL_VERSION, TokenPair

from .models import GatewayAccessToken, GatewayDevice, GatewayRefreshToken
from .support import GatewayAuthContext, token_digest, utcnow


class GatewayTokenMixin:
    """Mixin whose concrete service supplies the request-owned session and TTLs."""

    db: Session
    access_ttl_minutes: int
    refresh_ttl_days: int

    def _issue_token_pair(self, device: GatewayDevice) -> TokenPair:
        now = utcnow()
        access_raw, access_expiry = self._issue_access_token(device)
        refresh_raw = "smr_" + secrets.token_urlsafe(48)
        refresh_expiry = now + timedelta(days=self.refresh_ttl_days)
        self.db.add(
            GatewayRefreshToken(
                device_id=device.id,
                token_hash=token_digest(refresh_raw),
                expires_at=refresh_expiry,
            )
        )
        self.db.flush()
        return TokenPair(
            access_token=access_raw,
            access_expires_at=access_expiry,
            refresh_token=refresh_raw,
            refresh_expires_at=refresh_expiry,
        )

    def _issue_access_token(
        self,
        device: GatewayDevice,
        *,
        ttl_minutes: int | None = None,
    ) -> tuple[str, datetime]:
        raw = "sma_" + secrets.token_urlsafe(32)
        expiry = utcnow() + timedelta(minutes=ttl_minutes or self.access_ttl_minutes)
        self.db.add(
            GatewayAccessToken(
                device_id=device.id,
                token_hash=token_digest(raw),
                expires_at=expiry,
            )
        )
        self.db.flush()
        return raw, expiry

    def issue_web_admin_session(self, *, ttl_minutes: int = 12 * 60) -> tuple[str, datetime]:
        """Issue an HTTP-only browser session after bootstrap-key verification."""

        device = (
            self.db.query(GatewayDevice)
            .filter(
                GatewayDevice.platform == "web",
                GatewayDevice.role == "owner",
                GatewayDevice.status == "approved",
            )
            .first()
        )
        if device is None:
            now = utcnow()
            device = GatewayDevice(
                name="Gateway 管理网页",
                platform="web",
                role="owner",
                status="approved",
                capabilities_json={
                    "protocol_version": SYNC_PROTOCOL_VERSION,
                    "admin_console": True,
                },
                protocol_version=SYNC_PROTOCOL_VERSION,
                approved_at=now,
            )
            self.db.add(device)
            self.db.flush()
        raw, expiry = self._issue_access_token(device, ttl_minutes=ttl_minutes)
        commit_session(self.db)
        return raw, expiry

    def refresh_tokens(self, raw_refresh_token: str) -> TokenPair:
        digest = token_digest(raw_refresh_token)
        stored = (
            self.db.query(GatewayRefreshToken)
            .filter(GatewayRefreshToken.token_hash == digest)
            .first()
        )
        if stored is None:
            raise UnauthorizedError("刷新凭据无效")
        device = self.db.get(GatewayDevice, stored.device_id)
        now = utcnow()
        if device is None or device.status != "approved" or stored.expires_at <= now:
            raise UnauthorizedError("设备授权已失效，请重新配对")
        if stored.revoked_at is not None:
            self._revoke_reused_refresh_token(device.id, now)
            raise UnauthorizedError("检测到已轮换凭据被重复使用，请重新配对")

        stored.revoked_at = now
        stored.last_used_at = now
        tokens = self._issue_token_pair(device)
        replacement = (
            self.db.query(GatewayRefreshToken)
            .filter(GatewayRefreshToken.token_hash == token_digest(tokens.refresh_token))
            .one()
        )
        stored.rotated_to_id = replacement.id
        commit_session(self.db)
        return tokens

    def _revoke_reused_refresh_token(self, device_id: str, now: datetime) -> None:
        self.db.query(GatewayAccessToken).filter(
            GatewayAccessToken.device_id == device_id,
            GatewayAccessToken.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session=False)
        self.db.query(GatewayRefreshToken).filter(
            GatewayRefreshToken.device_id == device_id,
            GatewayRefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session=False)
        commit_session(self.db)

    def authenticate(self, raw_access_token: str, *, touch: bool = True) -> GatewayAuthContext:
        stored = (
            self.db.query(GatewayAccessToken)
            .filter(GatewayAccessToken.token_hash == token_digest(raw_access_token))
            .first()
        )
        now = utcnow()
        if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
            raise UnauthorizedError("访问凭据无效或已过期")
        device = self.db.get(GatewayDevice, stored.device_id)
        if device is None or device.status != "approved" or device.revoked_at is not None:
            raise UnauthorizedError("设备授权已撤销")
        if touch:
            stored.last_used_at = now
            device.last_seen_at = now
            commit_session(self.db)
        return GatewayAuthContext(
            device_id=device.id,
            role=device.role,
            platform=device.platform,
        )

    def revoke_access_token(self, raw_access_token: str) -> None:
        stored = (
            self.db.query(GatewayAccessToken)
            .filter(GatewayAccessToken.token_hash == token_digest(raw_access_token))
            .first()
        )
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = utcnow()
            commit_session(self.db)


__all__ = ["GatewayTokenMixin"]
