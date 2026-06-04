resource "aws_ecr_repository" "replicant" {
  name                 = "replicant-${var.project_tag}"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = {
    replicant_env = var.project_tag
  }
}

resource "aws_ecr_lifecycle_policy" "replicant" {
  repository = aws_ecr_repository.replicant.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the latest image"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 1
      }
      action = { type = "expire" }
    }]
  })
}
