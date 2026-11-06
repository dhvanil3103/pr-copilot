module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = var.cluster_name
  kubernetes_version = var.kubernetes_version
  # STANDARD: at the end of standard support EKS upgrades the cluster instead of
  # silently moving it to extended support, which costs 6x for the control plane.
  upgrade_policy = { support_type = "STANDARD" }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  # Public endpoint so GitHub Actions can deploy; restricted by CIDR (see DESIGN.md).
  endpoint_public_access       = true
  endpoint_private_access      = true
  endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  # Access entries only (no aws-auth ConfigMap). The identity running Terraform is admin.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  # Cost: no control plane logging, no CloudWatch log group, no customer managed KMS key.
  enabled_log_types           = []
  create_cloudwatch_log_group = false
  create_kms_key              = false
  encryption_config           = null

  # The EBS CSI driver uses EKS Pod Identity, so the IRSA OIDC provider is not needed.
  enable_irsa = false

  addons = {
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = { before_compute = true }
    kube-proxy             = {}
    coredns                = {}
    aws-ebs-csi-driver = {
      pod_identity_association = [{
        role_arn        = aws_iam_role.ebs_csi.arn
        service_account = "ebs-csi-controller-sa"
      }]
    }
  }

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = [var.node_instance_type]
      capacity_type  = var.use_spot ? "SPOT" : "ON_DEMAND"

      min_size     = var.node_count
      max_size     = var.node_count
      desired_size = var.node_count

      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.node_disk_size_gib
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }
    }
  }

  access_entries = {
    github_deploy = {
      principal_arn = aws_iam_role.github_deploy.arn
      policy_associations = {
        # Edit rights in the app namespace only, not cluster admin.
        app_namespace = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
          access_scope = {
            type       = "namespace"
            namespaces = [var.app_namespace]
          }
        }
      }
    }
  }

  # Passed explicitly too, so node instances and volumes launched by the node
  # group's launch template are tagged (provider default_tags do not reach them).
  tags = local.tags
}

# IAM role for the EBS CSI driver's controller, assumed through EKS Pod Identity.
resource "aws_iam_role" "ebs_csi" {
  name = "${var.cluster_name}-ebs-csi"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
