variable "aws_region" {
  description = "AWS region for the ScaleGuard pilot deployment."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Base name used for AWS resources."
  type        = string
  default     = "scaleguard"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "prod"
}

variable "vpc_id" {
  description = "Existing VPC to deploy into."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs used by the load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnet IDs used by ECS tasks."
  type        = list(string)
}

variable "container_image_tag" {
  description = "Container image tag to deploy for all ScaleGuard services."
  type        = string
  default     = "latest"
}

variable "api_gateway_image" {
  description = "Full image URI for the API gateway container."
  type        = string
}

variable "ingestion_image" {
  description = "Full image URI for the ingestion service container."
  type        = string
}

variable "prediction_image" {
  description = "Full image URI for the prediction engine container."
  type        = string
}

variable "autoscaler_image" {
  description = "Full image URI for the autoscaler container."
  type        = string
}

variable "db_password" {
  description = "Database password for the pilot deployment."
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  description = "JWT signing key for API authentication."
  type        = string
  sensitive   = true
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener."
  type        = string
}
