"""GitHub App client: JWT -> installation token, PR reads, and review posting."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
import jwt

log = logging.getLogger(__name__)

API_VERSION = "2022-11-28"
# Refresh installation tokens this long before GitHub expires them (they last 1 hour).
TOKEN_REFRESH_MARGIN_SECONDS = 300


@dataclass
class ReviewComment:
    path: str
    line: int
    body: str


class GitHubClient(Protocol):
    """The worker depends on this interface so tests can inject an in-memory fake."""

    async def list_pr_files(self, installation_id: int, repo: str, pr_number: int) -> list[dict]:
        """Changed files as returned by GitHub, including each file's `patch`."""
        ...

    async def get_file_content(
        self, installation_id: int, repo: str, path: str, ref: str
    ) -> str: ...

    async def create_review(
        self,
        installation_id: int,
        repo: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        comments: list[ReviewComment],
    ) -> int:
        """Post one COMMENT review and return its id."""
        ...


class GitHubError(Exception):
    pass


class GitHubAppClient:
    def __init__(
        self,
        app_id: str,
        private_key: str,
        base_url: str = "https://api.github.com",
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._http = http or httpx.AsyncClient(timeout=30)
        self._base_url = base_url.rstrip("/")
        # installation_id -> (token, unix expiry)
        self._tokens: dict[int, tuple[str, float]] = {}
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    def _app_jwt(self) -> str:
        now = int(time.time())
        # iat is backdated to tolerate clock drift; GitHub caps exp at 10 minutes.
        payload = {"iat": now - 60, "exp": now + 540, "iss": self._app_id}
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def _installation_token(self, installation_id: int) -> str:
        async with self._token_lock:
            cached = self._tokens.get(installation_id)
            if cached and cached[1] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
                return cached[0]
            response = await self._request(
                "POST",
                f"/app/installations/{installation_id}/access_tokens",
                auth=f"Bearer {self._app_jwt()}",
            )
            data = response.json()
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            self._tokens[installation_id] = (data["token"], expires_at.timestamp())
            return data["token"]

    @staticmethod
    def _is_retryable(response: httpx.Response) -> bool:
        if response.status_code == 429 or response.status_code >= 500:
            return True
        # Primary rate limit exhaustion is reported as 403 with remaining=0.
        return response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            if retry_after := response.headers.get("retry-after"):
                return float(retry_after)
            if reset := response.headers.get("x-ratelimit-reset"):
                return max(0.0, float(reset) - time.time()) + 1
        # Exponential backoff with jitter so parallel workers do not retry in lockstep.
        return self._backoff_base * 2**attempt + random.uniform(0, self._backoff_base)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: str,
        accept: str = "application/vnd.github+json",
        **kwargs,
    ) -> httpx.Response:
        headers = {
            "Authorization": auth,
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
        }
        for attempt in range(self._max_attempts):
            response: httpx.Response | None = None
            try:
                response = await self._http.request(
                    method, self._base_url + path, headers=headers, **kwargs
                )
            except httpx.TransportError as exc:
                if attempt == self._max_attempts - 1:
                    raise GitHubError(f"{method} {path} failed: {exc}") from exc
            else:
                if response.is_success:
                    return response
                if not self._is_retryable(response) or attempt == self._max_attempts - 1:
                    raise GitHubError(
                        f"{method} {path} returned {response.status_code}: {response.text[:500]}"
                    )
            delay = self._retry_delay(attempt, response)
            log.warning("GitHub %s %s retry %s in %.1fs", method, path, attempt + 1, delay)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _token_auth(self, installation_id: int) -> str:
        return f"Bearer {await self._installation_token(installation_id)}"

    async def list_pr_files(self, installation_id: int, repo: str, pr_number: int) -> list[dict]:
        files: list[dict] = []
        page = 1
        # GitHub returns at most 3000 files, 100 per page.
        while page <= 30:
            response = await self._request(
                "GET",
                f"/repos/{repo}/pulls/{pr_number}/files",
                auth=await self._token_auth(installation_id),
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    async def get_file_content(self, installation_id: int, repo: str, path: str, ref: str) -> str:
        response = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            auth=await self._token_auth(installation_id),
            accept="application/vnd.github.raw+json",
            params={"ref": ref},
        )
        return response.text

    async def create_review(
        self,
        installation_id: int,
        repo: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        comments: list[ReviewComment],
    ) -> int:
        payload = {
            "commit_id": commit_sha,
            "body": body,
            # Always COMMENT: the bot never approves or blocks a merge.
            "event": "COMMENT",
            "comments": [
                {"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in comments
            ],
        }
        response = await self._request(
            "POST",
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            auth=await self._token_auth(installation_id),
            json=payload,
        )
        return response.json()["id"]
