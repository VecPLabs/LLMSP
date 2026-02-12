"""Tests for LLMSP cryptographic primitives."""

from llmsp.crypto import (
    Ed25519Signer,
    Ed25519Verifier,
    KeyType,
    RSASigner,
    RSAVerifier,
    make_signer,
    make_verifier,
)


def test_ed25519_sign_verify():
    signer = Ed25519Signer()
    data = b"hello swarm protocol"
    sig = signer.sign(data)

    verifier = Ed25519Verifier(signer.public_key_bytes)
    assert verifier.verify(data, sig) is True


def test_ed25519_reject_tampered():
    signer = Ed25519Signer()
    data = b"original data"
    sig = signer.sign(data)

    verifier = Ed25519Verifier(signer.public_key_bytes)
    assert verifier.verify(b"tampered data", sig) is False


def test_ed25519_reject_wrong_key():
    signer1 = Ed25519Signer()
    signer2 = Ed25519Signer()
    data = b"test"
    sig = signer1.sign(data)

    verifier = Ed25519Verifier(signer2.public_key_bytes)
    assert verifier.verify(data, sig) is False


def test_rsa_sign_verify():
    signer = RSASigner(key_size=2048)
    data = b"hello rsa"
    sig = signer.sign(data)

    verifier = RSAVerifier(signer.public_key_bytes)
    assert verifier.verify(data, sig) is True


def test_rsa_reject_tampered():
    signer = RSASigner(key_size=2048)
    data = b"original"
    sig = signer.sign(data)

    verifier = RSAVerifier(signer.public_key_bytes)
    assert verifier.verify(b"tampered", sig) is False


def test_make_signer_ed25519():
    signer = make_signer(KeyType.ED25519)
    assert signer.key_type == KeyType.ED25519
    assert len(signer.public_key_bytes) == 32  # Ed25519 public key is 32 bytes


def test_make_signer_rsa():
    signer = make_signer(KeyType.RSA)
    assert signer.key_type == KeyType.RSA
    assert len(signer.public_key_bytes) > 0


def test_make_verifier_roundtrip():
    for kt in (KeyType.ED25519, KeyType.RSA):
        signer = make_signer(kt)
        data = b"roundtrip test"
        sig = signer.sign(data)

        verifier = make_verifier(kt, signer.public_key_bytes)
        assert verifier.verify(data, sig) is True
