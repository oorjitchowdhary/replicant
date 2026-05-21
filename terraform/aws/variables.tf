variable "instance_type" {
  description = "EC2 instance type. Use t3.large for standard workloads, g4dn.xlarge for GPU (requires quota increase)."
  type        = string
  default     = "t3.large"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "ami_id" {
  description = "Ubuntu 22.04 LTS AMI - update if deploying outside us-west-2"
  type        = string
  default     = "ami-03f65b8614a860c29"  # us-west-2 Ubuntu 22.04 LTS
}

variable "project_tag" {
  description = "Unique tag for this replicant environment (env_id)"
  type        = string
}
