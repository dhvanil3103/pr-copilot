#!/usr/bin/env bash
# Build all images, deploy them to a kind cluster against the mock APIs, and run
# the smoke test. Used by .github/workflows/e2e.yml and runnable locally.
# Needs: docker, kind, kubectl, helm, uv, openssl.
set -euo pipefail

CLUSTER="${CLUSTER:-pr-copilot}"
NAMESPACE="${NAMESPACE:-pr-copilot}"
RELEASE="${RELEASE:-prc}"
cd "$(dirname "$0")/.."

echo "==> Building images"
docker build -q -t pr-copilot-api:e2e -f api/Dockerfile .
docker build -q -t pr-copilot-worker:e2e -f worker/Dockerfile .
docker build -q -t pr-copilot-frontend:e2e frontend
docker build -q -t pr-copilot-mock-github:e2e -f tests/e2e/mocks/github/Dockerfile tests/e2e/mocks
docker build -q -t pr-copilot-mock-anthropic:e2e -f tests/e2e/mocks/anthropic/Dockerfile tests/e2e/mocks

echo "==> Creating kind cluster '$CLUSTER'"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --wait 120s
for image in api worker frontend mock-github mock-anthropic; do
  kind load docker-image --name "$CLUSTER" "pr-copilot-$image:e2e"
done

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NAMESPACE" apply -f tests/e2e/k8s/mocks.yaml
kubectl -n "$NAMESPACE" rollout status deploy/mock-github deploy/mock-anthropic --timeout=120s

echo "==> Creating throwaway secrets"
if kubectl -n "$NAMESPACE" get secret pr-copilot-secrets >/dev/null 2>&1; then
  # Reuse on reruns: running pods keep the value they started with.
  WEBHOOK_SECRET="$(kubectl -n "$NAMESPACE" get secret pr-copilot-secrets \
    -o jsonpath='{.data.github-webhook-secret}' | base64 --decode)"
else
  WEBHOOK_SECRET="$(openssl rand -hex 16)"
  KEY_FILE="$(mktemp)"
  openssl genrsa -out "$KEY_FILE" 2048 2>/dev/null
  kubectl -n "$NAMESPACE" create secret generic pr-copilot-secrets \
    --from-literal=github-webhook-secret="$WEBHOOK_SECRET" \
    --from-literal=github-app-id=1 \
    --from-file=github-private-key="$KEY_FILE" \
    --from-literal=anthropic-api-key=mock \
    --from-literal=postgres-password="$(openssl rand -hex 16)"
  rm -f "$KEY_FILE"
fi

echo "==> Installing the chart"
helm upgrade --install "$RELEASE" charts/pr-copilot -n "$NAMESPACE" \
  -f charts/pr-copilot/values-kind.yaml --wait --timeout 10m

echo "==> Running the smoke test"
NAMESPACE="$NAMESPACE" RELEASE="$RELEASE" WEBHOOK_SECRET="$WEBHOOK_SECRET" scripts/smoke_test.sh
