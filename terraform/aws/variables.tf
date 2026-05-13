variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "g4dn.xlarge"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "ami_id" {
  description = "Deep Learning AMI (Ubuntu) - update per region"
  type        = string
  default     = "ami-0735c191cf914754d"  # us-west-2 Deep Learning AMI Ubuntu 20.04
}

variable "project_tag" {
  description = "Unique tag for this replicant environment (env_id)"
  type        = string
}
