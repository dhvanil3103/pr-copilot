# PR Copilot: notes for Claude Code

GitHub App that reviews PRs with two LangChain/Claude agents. Read docs/DESIGN.md for the why.

## Commands

```bash
uv sync                                   # Python deps (Python 3.12, uv)
uv run ruff check . && uv run ruff format --check .
uv run pytest -m "not integration"        # fast unit tests
uv run pytest -m integration              # needs Docker (Testcontainers Postgres + Kafka)
cd frontend && npm run lint && npm test && npm run build
docker compose up --build                 # local stack: API :8000, dashboard :8080
scripts/e2e_kind.sh                       # kind + Helm + mock APIs + smoke test
uv run python -m evals.run                # real model, costs money, needs ANTHROPIC_API_KEY
helm lint charts/pr-copilot -f charts/pr-copilot/values-eks.yaml
cd infra/terraform && terraform fmt -check && terraform init -backend=false && terraform validate
```

## Layout and conventions

- One Python project, two entrypoints: `api/` (`api.asgi:app`) and `worker/` (`worker.main`),
  sharing `shared/`. Settings are `shared/config.py` (env vars, pydantic-settings).
- Agent prompts live in `worker/prompts/*_v<N>.md`. To change a prompt, add a new version
  and update `PROMPT_FILES` in `worker/agents/langchain_runner.py`, so diffs and eval
  reports show the change.
- No fake or test modes in production code. Tests inject doubles from `tests/doubles/`
  (`FakeGitHubClient`, `FakeAgentRunner`) through `WorkerDeps`; e2e mock servers live in
  `tests/e2e/mocks/`. Integration tests carry `pytestmark = pytest.mark.integration`.
- Agent tools must stay read-only. Only deterministic code posts to GitHub, after
  `worker/grounding.py`.
- Processing must stay idempotent (at-least-once delivery): see `claim_review` in
  `worker/processor.py` and the unique (repo, PR, head SHA) constraint.
- Schema changes: add an Alembic migration in `migrations/versions/` (enums are VARCHAR).
- Comments explain why, not what. Line length 100, ruff rules E, F, I, UP, B, ASYNC.
- Fake credentials in fixtures must not match real provider formats (`sk_live_`, `ghp_`,
  `AKIA`): GitHub push protection blocks them.
- Commits: Conventional Commits, imperative subject under 72 chars, one or two line body,
  no assistant attribution. Work on a branch, never commit directly to `main`.
- Never run `terraform apply` or anything that creates cloud resources or costs money.
