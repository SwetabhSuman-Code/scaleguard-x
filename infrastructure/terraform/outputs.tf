output "load_balancer_dns_name" {
  description = "Public DNS name for the ScaleGuard pilot ALB."
  value       = aws_lb.scaleguard.dns_name
}

output "api_gateway_target_group_arn" {
  description = "Target group used by the API gateway service."
  value       = aws_lb_target_group.api_gateway.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster hosting ScaleGuard services."
  value       = aws_ecs_cluster.scaleguard.name
}

output "worker_service_name" {
  description = "ECS service scaled by the ScaleGuard autoscaler."
  value       = aws_ecs_service.worker.name
}

output "rds_endpoint" {
  description = "Postgres endpoint used by the pilot deployment."
  value       = aws_db_instance.scaleguard.address
}

output "redis_endpoint" {
  description = "Redis endpoint used by the pilot deployment."
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}
