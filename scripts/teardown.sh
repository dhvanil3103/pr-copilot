#!/usr/bin/env bash
# Tear down everything that bills, in the right order.
#
# Kubernetes creates the NLB (for ingress-nginx's LoadBalancer Service) and the EBS
# volumes (for PVCs) itself, so they are not in Terraform state. If the cluster is
# destroyed first, nothing is left to delete them and they keep billing. So:
#   1. uninstall the app (PVCs -> EBS volumes deleted by the CSI driver)
#   2. uninstall ingress-nginx (LoadBalancer Service -> NLB deleted)
#   3. wait until AWS confirms both are gone
#   4. terraform destroy
#   5. list anything tagged project=pr-copilot that is still around
#
# Usage: scripts/teardown.sh [--auto-approve]
# Env: AWS_REGION (default: from terraform output), CLUSTER_NAME, NAMESPACE, RELEASE
set -euo pipefail

cd "$(dirname "$0")/../infra/terraform"
REGION="${AWS_REGION:-$(terraform output -raw region 2>/dev/null || echo us-east-1)}"
CLUSTER_NAME="${CLUSTER_NAME:-$(terraform output -raw cluster_name 2>/dev/null || echo pr-copilot)}"
NAMESPACE="${NAMESPACE:-pr-copilot}"
RELEASE="${RELEASE:-prc}"
APPROVE=""
[ "${1:-}" = "--auto-approve" ] && APPROVE="-auto-approve"

wait_until_empty() {  # wait_until_empty <description> <command printing leftovers>
  local what="$1"; shift
  for _ in $(seq 1 60); do
    if [ -z "$("$@")" ]; then echo "    no $what left"; return 0; fi
    echo "    waiting for $what to be deleted..."
    sleep 10
  done
  echo "!!  $what still present after 10 minutes; check the AWS console before destroying" >&2
  return 1
}

nlbs() {
  aws resourcegroupstaggingapi get-resources --region "$REGION" \
    --resource-type-filters elasticloadbalancing:loadbalancer \
    --tag-filters "Key=kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text
}

csi_volumes() {
  aws ec2 describe-volumes --region "$REGION" \
    --filters "Name=tag:ebs.csi.aws.com/cluster,Values=true" "Name=tag:project,Values=pr-copilot" \
    --query 'Volumes[].VolumeId' --output text
}

echo "==> Connecting to cluster $CLUSTER_NAME in $REGION"
if aws eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" >/dev/null 2>&1; then
  aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER_NAME" >/dev/null

  echo "==> Uninstalling the app (deletes PVCs and their EBS volumes)"
  helm uninstall "$RELEASE" -n "$NAMESPACE" --wait 2>/dev/null || echo "    release not found"
  # Normally removed by the StatefulSet retention policy; delete any stragglers.
  kubectl delete pvc --all -n "$NAMESPACE" --wait=true 2>/dev/null || true

  echo "==> Uninstalling ingress-nginx (deletes the NLB)"
  helm uninstall ingress-nginx -n ingress-nginx --wait 2>/dev/null || echo "    release not found"

  echo "==> Waiting for AWS to delete the NLB and EBS volumes"
  wait_until_empty "load balancers" nlbs
  wait_until_empty "EBS volumes" csi_volumes
else
  echo "    cluster not found, skipping Kubernetes cleanup"
fi

echo "==> terraform destroy"
terraform destroy $APPROVE

echo "==> Leftover check (anything here is still billing)"
echo "-- Load balancers:";  aws elbv2 describe-load-balancers --region "$REGION" \
  --query "LoadBalancers[?contains(LoadBalancerName, 'k8s') || contains(DNSName, '$CLUSTER_NAME')].LoadBalancerArn" --output text
echo "-- EBS volumes tagged project=pr-copilot:"; aws ec2 describe-volumes --region "$REGION" \
  --filters "Name=tag:project,Values=pr-copilot" --query 'Volumes[].[VolumeId,State]' --output text
echo "-- Elastic IPs tagged project=pr-copilot:"; aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:project,Values=pr-copilot" --query 'Addresses[].PublicIp' --output text
echo "-- Any resource still tagged project=pr-copilot:"; aws resourcegroupstaggingapi get-resources \
  --region "$REGION" --tag-filters Key=project,Values=pr-copilot \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
echo "Done. Empty lists above mean nothing is left billing."
