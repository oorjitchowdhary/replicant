resource "aws_iam_role" "replicant" {
  name = "replicant-${var.project_tag}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    replicant_env = var.project_tag
  }
}

resource "aws_iam_role_policy" "replicant_ecr" {
  name = "replicant-ecr-access"
  role = aws_iam_role.replicant.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchDeleteImage",
        ]
        Resource = aws_ecr_repository.replicant.arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "replicant" {
  name = "replicant-${var.project_tag}"
  role = aws_iam_role.replicant.name
}
