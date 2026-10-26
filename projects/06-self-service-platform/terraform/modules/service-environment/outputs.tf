output "ecr_repository_url" {
  description = "Where this service's CI pushes images."
  value       = aws_ecr_repository.this.repository_url
}

output "deploy_role_arn" {
  description = "Role for GitHub Actions to assume (aws-actions/configure-aws-credentials)."
  value       = aws_iam_role.deploy.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
