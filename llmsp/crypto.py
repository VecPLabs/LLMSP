"""Cryptographic primitives for LLMSP.

Provides key generation, signing, and verification using Ed25519
(preferred for speed) with RSA-PSS as a fallback.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa, utils


class KeyType(str, Enum):
    ED25519 = "ed25519"
    RSA = "rsa"


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class Signer(Protocol):
    """Signs payloads and exposes the public key for verification."""

    @property
    def key_type(self) -> KeyType: ...

    @property
    def public_key_bytes(self) -> bytes:
        """DER-encoded public key."""
        ...

    def sign(self, data: bytes) -> bytes: ...


class Verifier(Protocol):
    """Verifies signatures given a public key."""

    def verify(self, data: bytes, signature: bytes) -> bool: ...


# ---------------------------------------------------------------------------
# Ed25519 implementation (preferred)
# ---------------------------------------------------------------------------


class Ed25519Signer:
    """Ed25519 signing key."""

    key_type = KeyType.ED25519

    def __init__(self) -> None:
        self._private_key = ed25519.Ed25519PrivateKey.generate()

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

    def sign(self, data: bytes) -> bytes:
        return self._private_key.sign(data)


class Ed25519Verifier:
    """Ed25519 verification from raw public key bytes."""

    def __init__(self, public_key_bytes: bytes) -> None:
        self._public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, data)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# RSA-PSS implementation (fallback / interop)
# ---------------------------------------------------------------------------

_RSA_PADDING = padding.PSS(
    mgf=padding.MGF1(hashes.SHA256()),
    salt_length=padding.PSS.MAX_LENGTH,
)
_RSA_HASH = hashes.SHA256()


class RSASigner:
    """RSA-2048 PSS signing key."""

    key_type = KeyType.RSA

    def __init__(self, key_size: int = 2048) -> None:
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def sign(self, data: bytes) -> bytes:
        return self._private_key.sign(data, _RSA_PADDING, _RSA_HASH)


class RSAVerifier:
    """RSA-PSS verification from DER-encoded public key bytes."""

    def __init__(self, public_key_bytes: bytes) -> None:
        self._public_key = serialization.load_der_public_key(public_key_bytes)

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, data, _RSA_PADDING, _RSA_HASH)  # type: ignore[arg-type]
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_signer(key_type: KeyType = KeyType.ED25519, **kwargs) -> Signer:  # type: ignore[return]
    if key_type == KeyType.ED25519:
        return Ed25519Signer()
    elif key_type == KeyType.RSA:
        return RSASigner(**kwargs)
    raise ValueError(f"Unsupported key type: {key_type}")


def make_verifier(key_type: KeyType, public_key_bytes: bytes) -> Verifier:  # type: ignore[return]
    if key_type == KeyType.ED25519:
        return Ed25519Verifier(public_key_bytes)
    elif key_type == KeyType.RSA:
        return RSAVerifier(public_key_bytes)
    raise ValueError(f"Unsupported key type: {key_type}")
