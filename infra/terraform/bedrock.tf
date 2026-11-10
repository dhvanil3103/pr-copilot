# The worker calls Claude in Amazon Bedrock with this role, assumed through EKS Pod Identity,
# so no AWS keys are stored in the cluster.
locals {
  # A cross-region inference profile ID (us.anthropic.x) routes to the foundation model
  # (anthropic.x) in several regions, and IAM checks both ARNs.
  bedrock_foundation_models = [
    for id in var.bedrock_model_ids : replace(id, "/^(us|eu|apac|global)\\./", "")
  ]
  bedrock_inference_profiles = [
    for id in var.bedrock_model_ids : id if can(regex("^(us|eu|apac|global)\\.", id))
  ]
}

resource "aws_iam_role" "worker_bedrock" {
  name = "${var.cluster_name}-worker-bedrock"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy" "worker_bedrock" {
  name = "invoke-review-models"
  role = aws_iam_role.worker_bedrock.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      # Converse and ConverseStream are authorized by these two actions.
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = concat(
        [
          for id in local.bedrock_inference_profiles :
          "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${id}"
        ],
        # Any region: the profile picks one at request time; "*" also matches the empty
        # region of a global profile's model ARN.
        [for id in local.bedrock_foundation_models : "arn:aws:bedrock:*::foundation-model/${id}"],
      )
    }]
  })
}

resource "aws_eks_pod_identity_association" "worker_bedrock" {
  cluster_name    = module.eks.cluster_name
  namespace       = var.app_namespace
  service_account = var.worker_service_account
  role_arn        = aws_iam_role.worker_bedrock.arn
}
