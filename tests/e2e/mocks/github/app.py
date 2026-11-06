"""Mock GitHub REST API for e2e tests. Never used in production.

Serves one canned pull request for any repo/number, records posted reviews, and
rejects inline comments on lines outside the diff exactly like GitHub (422).
"""

import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Mock GitHub")

FILES: dict[str, str] = {
    "app/payments.py": (
        "import requests\n\n"
        "API_KEY = 'acme-pay-live-0123456789abcdef'\n\n\n"
        "def charge(amount, token):\n"
        "    return requests.post('https://payments.acme.example', data={'a': amount})\n"
    ),
    "web/src/greet.js": "export function greet(name) {\n  return `Hello ${name}`;\n}\n",
}
PR_FILES = [
    {
        "filename": "app/payments.py",
        "status": "added",
        "additions": 7,
        "deletions": 0,
        "changes": 7,
        "patch": "@@ -0,0 +1,7 @@\n"
        + "\n".join("+" + line for line in FILES["app/payments.py"].rstrip("\n").split("\n")),
    },
    {
        "filename": "web/src/greet.js",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "patch": "@@ -1,3 +1,3 @@\n export function greet(name) {\n-  return 'Hello ' + name;\n"
        "+  return `Hello ${name}`;\n }",
    },
    {
        "filename": "package-lock.json",
        "status": "modified",
        "additions": 1,
        "patch": "@@ -1 +1 @@\n+{}",
    },
    {"filename": "logo.png", "status": "added", "additions": 0},
]
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

_lock = threading.Lock()
_reviews: list[dict[str, Any]] = []


def _commentable_lines(patch: str) -> set[int]:
    lines, current = set(), 0
    for raw in patch.splitlines():
        if m := _HUNK.match(raw):
            current = int(m.group(1))
        elif raw.startswith("-"):
            continue
        else:
            lines.add(current)  # GitHub accepts added and context lines on the RIGHT side
            current += 1
    return lines


def _require_auth(request: Request, prefix: str) -> None:
    if not request.headers.get("authorization", "").startswith(prefix):
        raise HTTPException(status_code=401, detail="Bad credentials")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/app/installations/{installation_id}/access_tokens", status_code=201)
async def access_token(installation_id: int, request: Request) -> dict[str, str]:
    _require_auth(request, "Bearer ey")  # an RS256 app JWT always starts with "ey"
    expires = datetime.now(UTC) + timedelta(hours=1)
    return {
        "token": f"ghs_mock_{installation_id}",
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.get("/repos/{owner}/{repo}/pulls/{number}/files")
async def pr_files(owner: str, repo: str, number: int, request: Request, page: int = 1):
    _require_auth(request, "Bearer ghs_mock_")
    return PR_FILES if page == 1 else []


@app.get("/repos/{owner}/{repo}/contents/{path:path}")
async def contents(owner: str, repo: str, path: str, request: Request):
    _require_auth(request, "Bearer ghs_mock_")
    if path not in FILES:
        raise HTTPException(status_code=404, detail="Not Found")
    return PlainTextResponse(FILES[path])


@app.post("/repos/{owner}/{repo}/pulls/{number}/reviews")
async def create_review(owner: str, repo: str, number: int, request: Request):
    _require_auth(request, "Bearer ghs_mock_")
    body = await request.json()
    if body.get("event") != "COMMENT":
        raise HTTPException(status_code=422, detail="PR Copilot must only COMMENT")
    patches = {f["filename"]: f.get("patch", "") for f in PR_FILES}
    for comment in body.get("comments", []):
        if comment["line"] not in _commentable_lines(patches.get(comment["path"], "")):
            raise HTTPException(status_code=422, detail=f"Line could not be resolved: {comment}")
    with _lock:
        review = {"id": len(_reviews) + 1, "repo": f"{owner}/{repo}", "pr": number, **body}
        _reviews.append(review)
    return {"id": review["id"], "state": "COMMENTED"}


@app.get("/_mock/reviews")
async def recorded_reviews() -> list[dict[str, Any]]:
    """Test-only endpoint: the smoke test checks that a review was posted."""
    with _lock:
        return list(_reviews)
