output "instance_public_ip" {
  value = aws_instance.replicant.public_ip
}

output "s3_bucket_name" {
  value = aws_s3_bucket.artifacts.bucket
}

output "instance_id" {
  value = aws_instance.replicant.id
}

output "key_path" {
  value = local_file.private_key.filename
}
