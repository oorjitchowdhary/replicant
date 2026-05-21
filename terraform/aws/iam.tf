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

resource "aws_iam_role_policy" "replicant_s3" {
  name = "replicant-s3-access"
  role = aws_iam_role.replicant.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "replicant" {
  name = "replicant-${var.project_tag}"
  role = aws_iam_role.replicant.name
}
