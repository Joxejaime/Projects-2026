output "alb_dns_name" {
  description = "Public DNS name of the load balancer."
  value       = aws_lb.this.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_role_name" {
  description = "Attach least-privilege policies to this role for application permissions."
  value       = aws_iam_role.task.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
