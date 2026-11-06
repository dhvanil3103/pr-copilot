import json

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from worker.github import GitHubAppClient, GitHubError, ReviewComment

API = "https://api.github.test"


@pytest.fixture(scope="module")
def private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def client(private_key):
    return GitHubAppClient("123", private_key, base_url=API, max_attempts=3, backoff_base=0)


def token_route(mock: respx.MockRouter, expires_at="2099-01-01T00:00:00Z"):
    return mock.post(f"{API}/app/installations/7/access_tokens").respond(
        201, json={"token": "inst-token", "expires_at": expires_at}
    )


@respx.mock
async def test_installation_token_is_cached(client):
    tokens = token_route(respx)
    files = respx.get(f"{API}/repos/o/r/pulls/1/files").respond(200, json=[{"filename": "a.py"}])

    await client.list_pr_files(7, "o/r", 1)
    await client.list_pr_files(7, "o/r", 1)

    assert tokens.call_count == 1
    assert tokens.calls[0].request.headers["authorization"].startswith("Bearer ey")
    assert files.calls[0].request.headers["authorization"] == "Bearer inst-token"


@respx.mock
async def test_token_refreshed_when_close_to_expiry(client):
    tokens = token_route(respx, expires_at="2000-01-01T00:00:00Z")
    respx.get(f"{API}/repos/o/r/pulls/1/files").respond(200, json=[])
    await client.list_pr_files(7, "o/r", 1)
    await client.list_pr_files(7, "o/r", 1)
    assert tokens.call_count == 2


@respx.mock
async def test_paginates_pr_files(client):
    token_route(respx)
    page1 = [{"filename": f"f{i}.py"} for i in range(100)]
    route = respx.get(f"{API}/repos/o/r/pulls/1/files")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=[{"filename": "x"}]),
    ]
    files = await client.list_pr_files(7, "o/r", 1)
    assert len(files) == 101


@respx.mock
async def test_retries_transient_errors_and_rate_limits(client):
    token_route(respx)
    route = respx.get(f"{API}/repos/o/r/contents/a.py")
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
        httpx.Response(200, text="print('hi')"),
    ]
    assert await client.get_file_content(7, "o/r", "a.py", "abc") == "print('hi')"
    assert route.calls[-1].request.url.params["ref"] == "abc"


@respx.mock
async def test_gives_up_after_max_attempts(client):
    token_route(respx)
    respx.get(f"{API}/repos/o/r/contents/a.py").respond(503)
    with pytest.raises(GitHubError, match="503"):
        await client.get_file_content(7, "o/r", "a.py", "abc")


@respx.mock
async def test_does_not_retry_client_errors(client):
    token_route(respx)
    route = respx.get(f"{API}/repos/o/r/contents/a.py").respond(404)
    with pytest.raises(GitHubError):
        await client.get_file_content(7, "o/r", "a.py", "abc")
    assert route.call_count == 1


@respx.mock
async def test_create_review_posts_comment_event(client):
    token_route(respx)
    route = respx.post(f"{API}/repos/o/r/pulls/1/reviews").respond(200, json={"id": 99})
    review_id = await client.create_review(
        7, "o/r", 1, "sha1", "summary", [ReviewComment("a.py", 3, "bug")]
    )
    assert review_id == 99
    payload = json.loads(route.calls[0].request.content)
    assert payload == {
        "commit_id": "sha1",
        "body": "summary",
        "event": "COMMENT",
        "comments": [{"path": "a.py", "line": 3, "side": "RIGHT", "body": "bug"}],
    }
