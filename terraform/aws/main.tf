terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# ── VPC ─────────────────────────────────────────────────────────────────────

resource "aws_vpc" "replicant" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name          = "replicant-${var.project_tag}"
    replicant_env = var.project_tag
  }
}

resource "aws_internet_gateway" "replicant" {
  vpc_id = aws_vpc.replicant.id

  tags = {
    Name          = "replicant-${var.project_tag}-igw"
    replicant_env = var.project_tag
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.replicant.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true

  tags = {
    Name          = "replicant-${var.project_tag}-public"
    replicant_env = var.project_tag
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.replicant.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.replicant.id
  }

  tags = {
    Name          = "replicant-${var.project_tag}-rt"
    replicant_env = var.project_tag
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ── Security group ───────────────────────────────────────────────────────────

resource "aws_security_group" "replicant" {
  name        = "replicant-${var.project_tag}-sg"
  description = "Replicant environment security group"
  vpc_id      = aws_vpc.replicant.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name          = "replicant-${var.project_tag}-sg"
    replicant_env = var.project_tag
  }
}

# ── SSH key pair ─────────────────────────────────────────────────────────────

resource "tls_private_key" "replicant" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "replicant" {
  key_name   = "replicant-${var.project_tag}"
  public_key = tls_private_key.replicant.public_key_openssh

  tags = {
    replicant_env = var.project_tag
  }
}

resource "local_file" "private_key" {
  content         = tls_private_key.replicant.private_key_pem
  filename        = pathexpand("~/.replicant/keys/${var.project_tag}.pem")
  file_permission = "0600"
}
