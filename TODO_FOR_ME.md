# TODO for me

## Merged (merged locally into `main` by Claude at your request; nothing pushed)
- `feat/foundation` (from `main`)
- `feat/review-pipeline` (from `main`)
- `feat/api-and-dashboard` (from `main`)

## Ready to merge
(none)

## Blocked on me
- Create the GitHub App and put `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`
  in `.env` (steps will be in docs/GITHUB_APP.md).
- Provide `ANTHROPIC_API_KEY` in `.env` for real reviews and evals.
- AWS credentials, region, and budget alert email for Terraform.
- `git config user.name` is not set; commits currently show the system default name "Dhvanil".

## Decisions to review
- Frontend pins jsdom 29 (not 31) because jsdom 30+ needs Node >= 22.22 and local Node is
  22.14. TypeScript is pinned to 6.0.3 because typescript-eslint does not support TS 7 yet.
  Consider upgrading local Node to 24 (CI and Docker use 24).
- Added a `summary` column to `reviews` (migration 0002). The spec's column list has none,
  but the dashboard detail view needs the review summary.
- Duplicate deliveries are rejected by the unique (repo, pr, head_sha) constraint, not a
  separate delivery-id table; the delivery id is carried in the event and logged.
- Default model for both agents is `claude-haiku-4-5` ($1/$5 per 1M tokens). Override with
  `DEFAULT_MODEL`, `REVIEW_AGENT_MODEL`, `TEST_AGENT_MODEL`.
- Known gap: if the worker crashes after GitHub accepts a review but before the DB commit,
  a retry would post a second review. The window is small; documented in DESIGN.md later.
