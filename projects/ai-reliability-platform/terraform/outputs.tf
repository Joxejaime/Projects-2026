output "alb_dns_name" {
  description = "Public DNS name of the load balancer."
  value       = aws_lb.this.dns_name
}

output "ecr_repository_url" {
  description = "Push the gateway image here."
  value       = aws_ecr_repository.gateway.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.gateway.name
}

output "log_group" {
  value = aws_cloudwatch_log_group.gateway.name
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
