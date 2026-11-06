#!/usr/bin/env bash
# Send a signed webhook to a deployed release, wait for the review to finish, and
# check that the mock GitHub received the posted review.
# Env: NAMESPACE, RELEASE, WEBHOOK_SECRET (required); TIMEOUT_SECONDS (default 180).
set -euo pipefail

NAMESPACE="${NAMESPACE:?}"
RELEASE="${RELEASE:?}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:?}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-180}"
API_PORT=18000
GITHUB_PORT=18081

kubectl -n "$NAMESPACE" port-forward "svc/${RELEASE}-pr-copilot-api" "$API_PORT:8000" >/dev/null &
PF_API=$!
kubectl -n "$NAMESPACE" port-forward svc/mock-github "$GITHUB_PORT:8080" >/dev/null &
PF_GITHUB=$!
trap 'kill $PF_API $PF_GITHUB 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS "http://localhost:$API_PORT/readyz" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "http://localhost:$API_PORT/readyz" && echo

response=$(uv run python scripts/send_test_webhook.py \
  --url "http://localhost:$API_PORT/webhooks/github" --secret "$WEBHOOK_SECRET" \
  --repo acme/smoke --pr 7)
echo "webhook: $response"
review_id=$(echo "$response" | sed -n 's/.*"review_id":\([0-9]*\).*/\1/p')
[ -n "$review_id" ] || { echo "webhook was not queued"; exit 1; }

deadline=$((SECONDS + TIMEOUT_SECONDS))
while true; do
  review=$(curl -fsS "http://localhost:$API_PORT/api/reviews/$review_id")
  status=$(echo "$review" | uv run python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  echo "review $review_id: $status"
  case "$status" in
    done) break ;;
    failed|skipped) echo "$review"; exit 1 ;;
  esac
  [ "$SECONDS" -lt "$deadline" ] || { echo "timed out"; exit 1; }
  sleep 3
done

echo "$review" | uv run python -c "
import json, sys
review = json.load(sys.stdin)
assert review['comments'], 'review has no comments'
print(f\"{len(review['comments'])} comments stored, {review['input_tokens']} input tokens\")
"
curl -fsS "http://localhost:$GITHUB_PORT/_mock/reviews" | uv run python -c "
import json, sys
reviews = [r for r in json.load(sys.stdin) if r['repo'] == 'acme/smoke' and r['pr'] == 7]
assert reviews, 'mock GitHub did not receive a review'
assert reviews[-1]['event'] == 'COMMENT' and reviews[-1]['comments'], reviews[-1]
print(f\"mock GitHub received a review with {len(reviews[-1]['comments'])} inline comments\")
"
echo "Smoke test passed"
