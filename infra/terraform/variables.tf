variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "pr-copilot"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Must be in standard support; extended support costs 6x."
  type        = string
  default     = "1.37"
}

variable "node_instance_type" {
  description = "Node instance type. Must be Graviton (arm64), e.g. t4g.medium."
  type        = string
  default     = "t4g.medium"

  validation {
    condition     = can(regex("^[a-z]+[0-9]+g[a-z]*\\.", var.node_instance_type))
    error_message = "Use a Graviton (arm64) instance type such as t4g.medium; the images and AMI are arm64."
  }
}

variable "node_count" {
  description = "Number of nodes (min = max = desired, so the cost is predictable)."
  type        = number
  default     = 2
}

variable "node_disk_size_gib" {
  description = "Root volume size per node in GiB (gp3)."
  type        = number
  default     = 20
}

variable "use_spot" {
  description = "Run nodes on Spot capacity (cheaper, but nodes can be reclaimed at short notice)."
  type        = bool
  default     = false
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public Kubernetes API endpoint. Narrow this to your IP and GitHub Actions if possible."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "app_namespace" {
  description = "Namespace the app is deployed to; the CI deploy role can only act here."
  type        = string
  default     = "pr-copilot"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name."
  type        = string
  default     = "dhvanil3103/pr-copilot"
}

variable "budget_email" {
  description = "Email address for AWS Budgets alerts."
  type        = string
}

variable "budget_limit_usd" {
  description = "Budget size in USD (roughly the credit pool)."
  type        = number
  default     = 117
}

variable "budget_alert_thresholds_usd" {
  description = "Actual-spend amounts in USD that trigger an email."
  type        = list(number)
  default     = [25, 50, 90]
}

variable "budget_start" {
  description = "Start of the budget period (YYYY-MM-DD_HH:MM), normally the month you start spending credits."
  type        = string
  default     = "2026-11-01_00:00"
}
