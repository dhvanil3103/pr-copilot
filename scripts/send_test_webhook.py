"""Send a correctly signed pull_request webhook to a running API.

Usage: uv run python scripts/send_test_webhook.py [--url URL] [--secret S] [--sha SHA]
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid

import httpx


def build_payload(repo: str, pr_number: int, sha: str, action: str) -> dict:
    return {
        "action": action,
        "pull_request": {"number": pr_number, "head": {"sha": sha}},
        "repository": {"full_name": repo},
        "installation": {"id": 1},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/webhooks/github")
    parser.add_argument("--secret", default=os.environ.get("GITHUB_WEBHOOK_SECRET", ""))
    parser.add_argument("--repo", default="acme/demo")
    parser.add_argument("--pr", type=int, default=1)
    parser.add_argument("--sha", default=uuid.uuid4().hex)
    parser.add_argument("--action", default="opened")
    args = parser.parse_args()

    if not args.secret:
        print("Set GITHUB_WEBHOOK_SECRET or pass --secret", file=sys.stderr)
        return 2

    body = json.dumps(build_payload(args.repo, args.pr, args.sha, args.action)).encode()
    signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
    response = httpx.post(
        args.url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": signature,
        },
        timeout=10,
    )
    print(response.status_code, response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
