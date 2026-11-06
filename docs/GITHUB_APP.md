# Creating the GitHub App

PR Copilot acts as a GitHub App: it receives `pull_request` webhooks and posts reviews as
the app's bot user. These steps take about five minutes.

## 1. Decide the webhook URL

The app must be able to reach `POST /webhooks/github` on the API.

| Where it runs | Webhook URL |
|---|---|
| EKS without a domain | `http://<NLB DNS name>/webhooks/github` (see [DEPLOY_EKS.md](DEPLOY_EKS.md#6-point-the-github-app-at-the-cluster)) |
| EKS with a domain and TLS | `https://<your host>/webhooks/github` |
| Local docker compose | A tunnel to `http://localhost:8000/webhooks/github`, e.g. `cloudflared tunnel --url http://localhost:8000` or [smee.io](https://smee.io) |

You can create the app first with a placeholder URL and edit it later.

## 2. Generate a webhook secret

```bash
openssl rand -hex 32
```

Keep this value: it goes into the app settings and into `GITHUB_WEBHOOK_SECRET`.

## 3. Create the app

Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**. For an
organization, use the organization's settings page instead.

| Field | Value |
|---|---|
| GitHub App name | Any unique name, e.g. `pr-copilot-<you>` |
| Homepage URL | Your repository URL |
| Webhook → Active | Checked |
| Webhook URL | From step 1 |
| Webhook secret | From step 2 |
| SSL verification | Enabled (it only applies to `https://` URLs) |

**Repository permissions:** the minimum the app needs.

| Permission | Access | Why |
|---|---|---|
| Pull requests | Read and write | Read PR files and diffs, post the review |
| Contents | Read-only | Read full file contents at the PR head commit |
| Metadata | Read-only | Mandatory for every app |

Leave everything else at **No access**.

**Subscribe to events:** check **Pull request** only. The API handles the `opened`,
`synchronize` and `reopened` actions and returns 200 for everything else.

**Where can this GitHub App be installed?** Choose **Only on this account**.

Click **Create GitHub App**.

## 4. Collect the credentials

On the app's settings page:

1. Note the **App ID** near the top → `GITHUB_APP_ID`.
2. Under **Private keys**, click **Generate a private key**. A `.pem` file downloads →
   `GITHUB_PRIVATE_KEY`. Store it like a password; anyone holding it can act as the app.

The worker signs a short-lived JWT with this key, exchanges it for an installation access
token (valid for one hour, cached until five minutes before expiry), and uses that token for
all API calls. The installation ID arrives in every webhook payload, so you don't need to
configure it.

## 5. Install the app

On the app page, click **Install App**, pick your account, and choose **Only select
repositories**. Then select the repositories PR Copilot should review.

## 6. Configure PR Copilot

**Docker compose:** add the values to `.env`. Keep the PEM's newlines inside double quotes:

```bash
GITHUB_WEBHOOK_SECRET=<from step 2>
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----"
```

**Kubernetes:** the values go into the `pr-copilot-secrets` Secret, see
[DEPLOY_EKS.md](DEPLOY_EKS.md#4-create-the-namespace-and-secret).

## 7. Test it

Open a pull request in an installed repository, then check:

- **App settings → Advanced → Recent Deliveries:** the delivery should show a 200 response
  with `{"status":"queued", ...}`. A 401 means the webhook secret does not match.
- **The dashboard:** the review moves from `queued` to `running` to `done`.
- **The PR:** a review from `<app name>[bot]` appears, with inline comments and a summary.

To resend a delivery while debugging, use **Redeliver** in Recent Deliveries. A delivery
for a commit that was already reviewed returns `{"status":"duplicate"}` by design. Push a new
commit to trigger a fresh review. Without GitHub in the loop, `scripts/send_test_webhook.py`
sends a correctly signed webhook.
