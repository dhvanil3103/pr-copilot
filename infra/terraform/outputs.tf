output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.region
}

output "update_kubeconfig_command" {
  description = "Run this to point kubectl at the new cluster."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.github_deploy.arn
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
