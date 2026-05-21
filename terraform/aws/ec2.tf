resource "aws_instance" "replicant" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.replicant.id]
  key_name               = aws_key_pair.replicant.key_name
  iam_instance_profile   = aws_iam_instance_profile.replicant.name

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update -y
    apt-get install -y docker.io awscli
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ubuntu
  EOF

  tags = {
    Name          = "replicant-${var.project_tag}"
    replicant_env = var.project_tag
  }
}
