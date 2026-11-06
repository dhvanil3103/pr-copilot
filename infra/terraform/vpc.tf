# Public subnets only, and no NAT gateway: nodes get public IPs and reach the
# internet through the internet gateway. A NAT gateway would roughly double the
# hourly bill. In production, nodes would sit in private subnets behind NAT.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = var.cluster_name
  cidr = "10.20.0.0/16"
  azs  = local.azs

  public_subnets          = ["10.20.0.0/20", "10.20.16.0/20"]
  map_public_ip_on_launch = true
  enable_nat_gateway      = false

  public_subnet_tags = {
    # Tells the Kubernetes AWS cloud provider these subnets can host internet-facing load balancers.
    "kubernetes.io/role/elb" = 1
  }

  tags = local.tags
}
