output "instance_public_ip" {
  value = aws_instance.replicant.public_ip
}

output "ecr_repo_url" {
  value = aws_ecr_repository.replicant.repository_url
}

output "instance_id" {
  value = aws_instance.replicant.id
}

output "key_path" {
  value = local_file.private_key.filename
}
