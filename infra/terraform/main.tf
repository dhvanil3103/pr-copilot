data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  tags = {
    project = "pr-copilot"
  }
  # EKS needs subnets in at least two availability zones.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}
