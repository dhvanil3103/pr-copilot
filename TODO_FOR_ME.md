# TODO for me

## Merged (merged locally into `main` by Claude at your request, then pushed)
- `feat/foundation` (from `main`)
- `feat/review-pipeline` (from `main`)
- `feat/api-and-dashboard` (from `main`)
- `test/integration-and-evals` (from `main`)
- `feat/deployment` (from `main`)

## Blocked on me
- Create the GitHub App and put `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`
  in `.env` (steps in docs/GITHUB_APP.md).
- Provide `ANTHROPIC_API_KEY` in `.env` for real reviews and evals, then run
  `uv run python -m evals.run` once (10 cases x 2 agents on Haiku; expect cents, not
  dollars). Evals were only verified against the mock Anthropic server, so no real scores yet.
- GitHub repo settings for the workflows:
  - Secret `ANTHROPIC_API_KEY` (evals workflow).
  - Variables `AWS_DEPLOY_ROLE_ARN` (terraform output `github_deploy_role_arn`), `AWS_REGION`,
    `EKS_CLUSTER_NAME` (deploy workflow).
  - After the first release run, make the three GHCR packages public (or add an
    `imagePullSecrets` entry in values-eks.yaml); new GHCR packages start private.
- AWS: configure a CLI profile, then `terraform apply` per docs/DEPLOY_EKS.md. Set
  `budget_email` in `terraform.tfvars`. Nothing in AWS has been created.
- `git config user.name` is not set; commits show the system default name "Dhvanil".

## Decisions to review
- **Migration hook is `post-install,pre-upgrade`, not `pre-install,pre-upgrade`.** Postgres is
  part of the same release, so on a first install it does not exist when pre-install hooks
  run and the Job would hang. Upgrades still migrate before new pods roll out.
- **gp3 StorageClass lives in `infra/k8s/`, not the chart.** It is cluster-scoped and the CI
  deploy role only has edit rights in the app namespace, so an admin applies it once.
- **NLB uses the built-in AWS cloud provider** (`service.beta.kubernetes.io/aws-load-balancer-type: nlb`),
  not the AWS Load Balancer Controller that AWS now recommends. The controller would add a
  component and an IAM role that are not in the spec; the in-tree one still gets critical fixes.
- **ingress-nginx was retired in March 2026** (no more releases or security fixes). It is kept
  because the spec requires it; the chart's Ingress is controller-agnostic (`ingress.className`),
  so moving to another controller or Gateway API later is a values change plus an install step.
- **Budget tracks gross spend** (`include_credit = false`), otherwise credits net spend to $0 and
  the alerts never fire. It is one annual budget starting at `budget_start` so it accumulates
  across months like the credit pool does.
- Added a `summary` column to `reviews` (migration 0002); the dashboard detail view needs it.
- Duplicate deliveries are rejected by the unique (repo, pr, head_sha) constraint, not a
  separate delivery-id table; the delivery id is carried in the event and logged.
- Default model for both agents is `claude-haiku-4-5` ($1/$5 per 1M tokens). Override with
  `DEFAULT_MODEL`, `REVIEW_AGENT_MODEL`, `TEST_AGENT_MODEL`.
- Frontend pins jsdom 29 (not 31) because jsdom 30+ needs Node >= 22.22 and local Node is
  22.14; TypeScript is pinned to 6.0.3 because typescript-eslint does not support TS 7 yet.
- Known gap: if the worker crashes after GitHub accepts a review but before the DB commit,
  a retry would post a second review. The window is small; documented in DESIGN.md.
