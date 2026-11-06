import hashlib
import hmac

from api.signature import verify_signature

SECRET = "s3cret"
BODY = b'{"action":"opened"}'


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_accepted():
    assert verify_signature(SECRET, BODY, sign(BODY))


def test_wrong_secret_rejected():
    assert not verify_signature(SECRET, BODY, sign(BODY, "other"))


def test_tampered_body_rejected():
    assert not verify_signature(SECRET, BODY + b" ", sign(BODY))


def test_missing_or_malformed_header_rejected():
    assert not verify_signature(SECRET, BODY, None)
    assert not verify_signature(SECRET, BODY, "")
    assert not verify_signature(SECRET, BODY, hashlib.sha256(BODY).hexdigest())


def test_empty_secret_never_validates():
    # An unconfigured secret must not let anyone in by signing with "".
    assert not verify_signature("", BODY, sign(BODY, ""))
