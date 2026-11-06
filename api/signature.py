import hashlib
import hmac


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check GitHub's X-Hub-Signature-256 header against the raw request body."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # compare_digest avoids leaking how many leading characters matched.
    return hmac.compare_digest(expected, header)
