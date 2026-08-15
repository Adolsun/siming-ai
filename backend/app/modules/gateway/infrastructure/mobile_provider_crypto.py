"""Application-layer encryption keys for ephemeral mobile model credentials."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.crypto import decrypt

from .models import GatewayIdentity

_IDENTITY_DERIVATION_INFO = b"siming-gateway-mobile-provider-identity-v1"


def gateway_encryption_private_key(identity: GatewayIdentity) -> X25519PrivateKey:
    """Derive an encryption-only X25519 identity from the signed Gateway seed.

    Domain-separated derivation avoids adding another long-lived database
    secret while keeping the encryption key stable for existing installations.
    """

    signing_seed = base64.urlsafe_b64decode(decrypt(identity.private_key_encrypted))
    encryption_seed = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_IDENTITY_DERIVATION_INFO,
    ).derive(signing_seed)
    return X25519PrivateKey.from_private_bytes(encryption_seed)


def gateway_encryption_public_key(identity: GatewayIdentity) -> str:
    raw = gateway_encryption_private_key(identity).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(raw).decode("ascii")


__all__ = ["gateway_encryption_private_key", "gateway_encryption_public_key"]
