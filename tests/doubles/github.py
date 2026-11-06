from dataclasses import dataclass, field

from worker.github import ReviewComment


@dataclass
class PostedReview:
    repo: str
    pr_number: int
    commit_sha: str
    body: str
    comments: list[ReviewComment]


@dataclass
class FakeGitHubClient:
    """In-memory GitHub: serves canned PR files and records posted reviews."""

    files: list[dict] = field(default_factory=list)
    contents: dict[str, str] = field(default_factory=dict)
    posted: list[PostedReview] = field(default_factory=list)
    fail_posts: int = 0  # number of create_review calls that raise before succeeding

    async def list_pr_files(self, installation_id: int, repo: str, pr_number: int) -> list[dict]:
        return self.files

    async def get_file_content(self, installation_id: int, repo: str, path: str, ref: str) -> str:
        return self.contents[path]

    async def create_review(self, installation_id, repo, pr_number, commit_sha, body, comments):
        if self.fail_posts:
            self.fail_posts -= 1
            raise RuntimeError("GitHub unavailable")
        self.posted.append(PostedReview(repo, pr_number, commit_sha, body, list(comments)))
        return len(self.posted)
