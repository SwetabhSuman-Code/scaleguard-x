terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  common_env = [
    { name = "POSTGRES_HOST", value = aws_db_instance.scaleguard.address },
    { name = "POSTGRES_PORT", value = tostring(aws_db_instance.scaleguard.port) },
    { name = "POSTGRES_USER", value = aws_db_instance.scaleguard.username },
    { name = "POSTGRES_DB", value = aws_db_instance.scaleguard.db_name },
    { name = "REDIS_HOST", value = aws_elasticache_cluster.redis.cache_nodes[0].address },
    { name = "REDIS_PORT", value = tostring(aws_elasticache_cluster.redis.port) },
    { name = "JWT_SECRET_KEY", value = var.jwt_secret_key },
    { name = "JWT_ISSUER", value = "scaleguard-api" },
    { name = "JWT_AUDIENCE", value = "scaleguard-services" },
    { name = "APP_ENV", value = var.environment },
  ]
}

resource "aws_cloudwatch_log_group" "scaleguard" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Public ALB access for ScaleGuard"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name_prefix}-ecs"
  description = "Service-to-service traffic for ScaleGuard ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group" "data" {
  name        = "${local.name_prefix}-data"
  description = "Database and cache access from ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_ecs_cluster" "scaleguard" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.common_tags
}

resource "aws_lb" "scaleguard" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
  tags               = local.common_tags
}

resource "aws_lb_target_group" "api_gateway" {
  name        = "${local.name_prefix}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 5
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.scaleguard.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_gateway.arn
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name_prefix}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_db_subnet_group" "scaleguard" {
  name       = "${local.name_prefix}-db"
  subnet_ids = var.private_subnet_ids
  tags       = local.common_tags
}

resource "aws_db_instance" "scaleguard" {
  identifier             = "${local.name_prefix}-postgres"
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = "db.t4g.medium"
  allocated_storage      = 50
  max_allocated_storage  = 200
  db_name                = "scaleguard"
  username               = "scaleguard"
  password               = var.db_password
  skip_final_snapshot    = true
  deletion_protection    = false
  db_subnet_group_name   = aws_db_subnet_group.scaleguard.name
  vpc_security_group_ids = [aws_security_group.data.id]
  publicly_accessible    = false
  multi_az               = false
  backup_retention_period = 7
  storage_encrypted      = true
  apply_immediately      = true
  tags                   = local.common_tags
}

resource "aws_elasticache_subnet_group" "scaleguard" {
  name       = "${local.name_prefix}-redis"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${local.name_prefix}-redis"
  engine               = "redis"
  node_type            = "cache.t4g.small"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.scaleguard.name
  security_group_ids   = [aws_security_group.data.id]
  tags                 = local.common_tags
}

resource "aws_ecs_task_definition" "api_gateway" {
  family                   = "${local.name_prefix}-api"
  cpu                      = 512
  memory                   = 1024
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "api-gateway"
      image     = var.api_gateway_image
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      environment = concat(local.common_env, [
        { name = "API_GATEWAY_HOST", value = "0.0.0.0" },
        { name = "API_GATEWAY_PORT", value = "8000" },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scaleguard.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "ingestion" {
  family                   = "${local.name_prefix}-ingestion"
  cpu                      = 256
  memory                   = 512
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "ingestion-service"
      image     = var.ingestion_image
      essential = true
      environment = local.common_env
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scaleguard.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ingestion"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "prediction" {
  family                   = "${local.name_prefix}-prediction"
  cpu                      = 1024
  memory                   = 2048
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "prediction-engine"
      image     = var.prediction_image
      essential = true
      environment = concat(local.common_env, [
        { name = "PROPHET_HISTORY_MINUTES", value = "20160" },
        { name = "PROPHET_RETRAIN_MINUTES", value = "360" },
        { name = "LSTM_TRAINING_SAMPLES", value = "300" },
        { name = "LSTM_EPOCHS", value = "4" },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scaleguard.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "prediction"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "autoscaler" {
  family                   = "${local.name_prefix}-autoscaler"
  cpu                      = 512
  memory                   = 1024
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "autoscaler"
      image     = var.autoscaler_image
      essential = true
      environment = concat(local.common_env, [
        { name = "AUTOSCALER_RPS_PER_WORKER", value = "300" },
        { name = "AUTOSCALER_MIN_WORKERS", value = "2" },
        { name = "AUTOSCALER_MAX_WORKERS", value = "8" },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scaleguard.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "autoscaler"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_service" "api_gateway" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.scaleguard.id
  task_definition = aws_ecs_task_definition.api_gateway.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = var.private_subnet_ids
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_gateway.arn
    container_name   = "api-gateway"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
  tags       = local.common_tags
}

resource "aws_ecs_service" "ingestion" {
  name            = "${local.name_prefix}-ingestion"
  cluster         = aws_ecs_cluster.scaleguard.id
  task_definition = aws_ecs_task_definition.ingestion.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = var.private_subnet_ids
  }

  tags = local.common_tags
}

resource "aws_ecs_service" "prediction" {
  name            = "${local.name_prefix}-prediction"
  cluster         = aws_ecs_cluster.scaleguard.id
  task_definition = aws_ecs_task_definition.prediction.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = var.private_subnet_ids
  }

  tags = local.common_tags
}

resource "aws_ecs_service" "autoscaler" {
  name            = "${local.name_prefix}-autoscaler"
  cluster         = aws_ecs_cluster.scaleguard.id
  task_definition = aws_ecs_task_definition.autoscaler.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.ecs_tasks.id]
    subnets          = var.private_subnet_ids
  }

  tags = local.common_tags
}
