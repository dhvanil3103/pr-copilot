# Deploying to Amazon EKS

This guide creates the AWS infrastructure with Terraform, installs the ingress controller,
and deploys PR Copilot with Helm from GitHub Actions. It also covers tearing it all down,
because a running cluster costs about $5 per day (see [Cost](#cost)).

**Prerequisites:** AWS CLI v2 with a configured profile, Terraform ≥ 1.10, kubectl, Helm ≥ 3,
and the GitHub App from [GITHUB_APP.md](GITHUB_APP.md).

## 1. Create the infrastructure

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set budget_email, region, github_repo
terraform init
terraform plan        # review: VPC, EKS, node group, add-ons, IAM, budget
terraform apply       # about 15 minutes
```

This creates:

- A VPC with two public subnets in two AZs (no NAT gateway; see DESIGN.md).
- EKS 1.37 (standard support until December 2027) with upgrade policy `STANDARD`.
- One managed node group: 2 × `t4g.medium` (Graviton), 20 GiB gp3 root volumes. The node AMI
  follows `node_instance_type`, so an x86 type works too. On an AWS free plan account, which
  only allows free tier eligible types, set `node_instance_type = "m7i-flex.large"` and
  `node_count = 1` (2 vCPU and 8 GiB is enough for the whole app). The EKS control plane and
  the load balancer are not free tier and are paid from your credits.
- Add-ons: VPC CNI, CoreDNS, kube-proxy, EKS Pod Identity Agent, and the EBS CSI driver
  (its IAM role is attached through Pod Identity).
- The `pr-copilot-worker-bedrock` role, linked to the worker's service account
  (`pr-copilot-worker`) through EKS Pod Identity. It may only invoke the models in
  `bedrock_model_ids` (default: Claude Opus 4.5 through the `us.` inference profile), so the
  cluster holds no AWS keys. See [Claude through Bedrock](#claude-through-bedrock).
- A GitHub OIDC provider and the `pr-copilot-github-deploy` role (main branch only), with
  an EKS access entry limited to the `pr-copilot` namespace.
- An AWS Budgets alert emailing you at $25, $50 and $90 of actual spend. Confirm the
  subscription email AWS sends you.

Every resource is tagged `project = pr-copilot`.

**Restricting the API endpoint.** `cluster_endpoint_public_access_cidrs` defaults to
`0.0.0.0/0` so GitHub-hosted runners can deploy. To lock it down, set it to your IP plus
[GitHub's Actions IP ranges](https://api.github.com/meta) (a long list that changes over
time), or keep it at your IP and deploy from your laptop.

## 2. Connect kubectl

```bash
$(terraform output -raw update_kubeconfig_command)
kubectl get nodes        # node_count nodes, Ready
```

## 3. Install cluster-wide pieces (once, as admin)

The CI deploy role can only act inside the app namespace, so you install these yourself.

```bash
# gp3 StorageClass for the Postgres and Kafka volumes (EBS CSI driver).
kubectl apply -f ../k8s/gp3-storageclass.yaml

# ingress-nginx behind a single internet-facing NLB.
helm upgrade --install ingress-nginx ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx --version 4.15.1 \
  --namespace ingress-nginx --create-namespace \
  -f ../k8s/ingress-nginx-values.yaml --wait

kubectl -n ingress-nginx get svc ingress-nginx-controller   # EXTERNAL-IP = NLB DNS name
```

> ingress-nginx was retired in March 2026; 4.15.1 is its final release and was not tested
> against Kubernetes 1.37. It works for this project, but plan to move to another controller
> or Gateway API for anything long-lived (see DESIGN.md).

The NLB is created by the AWS cloud provider built into EKS, from the
`service.beta.kubernetes.io/aws-load-balancer-type: nlb` annotation. It is internet-facing
because the `aws-load-balancer-internal` annotation is absent, and it lands in the subnets
tagged `kubernetes.io/role/elb`.

## 4. Create the namespace and Secret

```bash
kubectl create namespace pr-copilot

kubectl -n pr-copilot create secret generic pr-copilot-secrets \
  --from-literal=github-webhook-secret='<webhook secret>' \
  --from-literal=github-app-id='<app id>' \
  --from-file=github-private-key=path/to/app.private-key.pem \
  --from-literal=postgres-password="$(openssl rand -hex 24)"
```

`values-eks.yaml` uses Bedrock, so no model key is needed. To use the Claude API instead, add
`--from-literal=anthropic-api-key='<sk-ant-...>'` and deploy with
`--set config.llmProvider=anthropic --set config.defaultModel=claude-haiku-4-5`.

### Claude through Bedrock

`values-eks.yaml` sets `config.llmProvider: bedrock`, `config.awsRegion`, the model, and
`config.llmRequestsPerMinute: "5"` (a new account's Bedrock quota). Before the first review:

- **Model access:** the model must be usable from the account. Check with
  `aws bedrock-runtime converse --region us-east-1 --model-id <model>
  --messages '[{"role":"user","content":[{"text":"hi"}]}]'`.
- **Same model in both places:** `config.defaultModel` in `values-eks.yaml` must be listed in
  the Terraform variable `bedrock_model_ids`, or the worker gets `AccessDeniedException`.
- **Messages API models:** the role allows Converse only (`bedrock:InvokeModel*`). Unversioned
  Claude IDs such as `claude-sonnet-5` go through bedrock-mantle and also need
  `bedrock-mantle:CreateInference` added to the policy in `bedrock.tf`.
- **Quota:** when AWS raises the requests-per-minute quota, delete `llmRequestsPerMinute` from
  `values-eks.yaml` and redeploy.

To confirm the worker got the role, run
`kubectl -n pr-copilot exec deploy/prc-pr-copilot-worker -- env | grep AWS_CONTAINER`. Pod
Identity sets `AWS_CONTAINER_CREDENTIALS_FULL_URI` in pods created after the association, so
restart the worker if it started before `terraform apply` finished.

Use a hex (URL-safe) Postgres password: it is embedded in the database URL.

## 5. Configure GitHub and deploy

In the repository, go to **Settings → Secrets and variables → Actions → Variables** and add:

| Variable | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `terraform output -raw github_deploy_role_arn` |
| `AWS_REGION` | e.g. `us-east-1` |
| `EKS_CLUSTER_NAME` | `terraform output -raw cluster_name` |

Images come from GHCR, pushed by the **Release** workflow on every push to `main` (tags are
the commit SHA and `latest`). New GHCR packages are private, so either make
`pr-copilot-api`, `pr-copilot-worker` and `pr-copilot-frontend` public (**Package settings →
Change visibility**), or create a pull secret and list it under `imagePullSecrets` in
`values-eks.yaml`.

Deploy: **Actions → Deploy → Run workflow** on `main`. It assumes the deploy role through
OIDC (no AWS keys in GitHub), runs `aws eks update-kubeconfig`, and runs
`helm upgrade --install prc charts/pr-copilot -f values-eks.yaml --set image.tag=<sha>`.

To deploy from your laptop instead (admin credentials):

```bash
helm upgrade --install prc charts/pr-copilot -n pr-copilot \
  -f charts/pr-copilot/values-eks.yaml --set image.tag=<commit sha> --wait
```

On first install the migration Job runs after the release's resources are created. On every
upgrade it runs before the new pods roll out.

## 6. Point the GitHub App at the cluster

```bash
NLB=$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "Dashboard: http://$NLB/"
echo "Webhook:   http://$NLB/webhooks/github"
```

Set the webhook URL in the GitHub App settings and open a PR to test (see GITHUB_APP.md,
step 7). The DNS name can take a few minutes to resolve after the NLB is created.

**HTTP without a domain** is acceptable for the webhook because every request is
HMAC-signed, so it cannot be forged or altered. It is not encrypted, though: the dashboard
and PR metadata travel in clear text. See DESIGN.md for the tradeoff.

### Optional: TLS with a domain

1. Install cert-manager and create a `ClusterIssuer` named `letsencrypt` (HTTP-01 through the
   `nginx` ingress class).
2. Create a DNS CNAME from your host to the NLB DNS name.
3. Deploy with `--set ingress.host=prcopilot.example.com --set ingress.tls.enabled=true`.
   The chart adds the `cert-manager.io/cluster-issuer` annotation and a TLS section.
4. Change the webhook URL to `https://prcopilot.example.com/webhooks/github`.

## Cost

Approximate us-east-1 on-demand prices, November 2026. Check the
[AWS pricing pages](https://aws.amazon.com/pricing/) for your region.

| Item | Rate | Per hour | Per day |
|---|---|---|---|
| EKS control plane (standard support) | $0.10/h | $0.100 | $2.40 |
| 2 × t4g.medium nodes | $0.0336/h each | $0.067 | $1.61 |
| Network Load Balancer | $0.0225/h + LCUs | $0.023 | $0.55 |
| Public IPv4 (2 nodes + 2 NLB) | $0.005/h each | $0.020 | $0.48 |
| EBS gp3 (2 × 20 GiB roots + 2 × 2 GiB PVCs) | $0.08/GB-month | $0.005 | $0.12 |
| **Total** | | **≈ $0.21** | **≈ $5.15** |

Not included: data transfer (small at this scale) and model usage (Bedrock or the Claude
API, tracked per review on the dashboard; on Opus 4.5 a large PR costs about $1).

At about $5 a day, $117 of credits lasts about 22 days if the cluster runs non-stop. **Tear it
down when you're not using it**, and recreate it with `terraform apply` (about 15 minutes) when
you need it. Running it only for a few hours a week costs a few dollars a month.

Things that would add cost, all off by default: a NAT gateway (~$1.08/day plus data), control
plane logging and Container Insights (CloudWatch ingestion), extended support (+$0.50/h for the
control plane), and extra load balancers (each Service of type LoadBalancer creates one).
Spot nodes (`use_spot = true`) cut the node cost by roughly 60-70%, but nodes can be reclaimed
with two minutes' notice, which restarts Kafka and Postgres.

## Tear down

```bash
scripts/teardown.sh            # asks for confirmation before terraform destroy
```

The order matters. Kubernetes, not Terraform, created the NLB (for ingress-nginx's
LoadBalancer Service) and the EBS volumes (for the PVCs). They are not in Terraform state.
If `terraform destroy` ran first, the cluster would be gone before Kubernetes could delete
them. They would keep billing, and they would also block deleting the VPC. The script:

1. Uninstalls the app. The StatefulSets' PVC retention policy deletes the PVCs, and the EBS
   CSI driver deletes the volumes.
2. Uninstalls ingress-nginx, which deletes the LoadBalancer Service and the NLB.
3. Waits until AWS reports no NLB tagged for the cluster and no CSI-created volumes.
4. Runs `terraform destroy`.
5. Lists load balancers, EBS volumes, Elastic IPs and any resource still tagged
   `project=pr-copilot`.

### Confirm nothing is left billing

The script's last step should print empty lists. To check by hand:

```bash
REGION=us-east-1
aws elbv2 describe-load-balancers --region $REGION --query 'LoadBalancers[].LoadBalancerName'
aws ec2 describe-volumes --region $REGION --filters Name=tag:project,Values=pr-copilot \
  --query 'Volumes[].VolumeId'
aws ec2 describe-volumes --region $REGION --filters Name=status,Values=available \
  --query 'Volumes[].VolumeId'                 # any unattached volume still bills
aws ec2 describe-addresses --region $REGION --query 'Addresses[].PublicIp'
aws eks list-clusters --region $REGION
aws resourcegroupstaggingapi get-resources --region $REGION \
  --tag-filters Key=project,Values=pr-copilot --query 'ResourceTagMappingList[].ResourceARN'
```

The tagging API can keep listing deleted resources for a while. In the console, the Billing →
Cost Explorer view grouped by the `project` tag (activate it under Cost allocation tags) shows
whether anything is still accruing.

## Remote state (optional)

State is local (`infra/terraform/terraform.tfstate`, git-ignored) by default. To share it or
keep it safe, store it in S3:

1. Create a versioned, encrypted S3 bucket.
2. Uncomment the `backend "s3"` block in `versions.tf` and set `bucket`, `key` and `region`.
   `use_lockfile = true` uses S3's native locking; no DynamoDB table is needed.
3. Run `terraform init -migrate-state` and confirm copying the existing state.
