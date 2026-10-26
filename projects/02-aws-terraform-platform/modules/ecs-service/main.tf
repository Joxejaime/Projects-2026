terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

data "aws_region" "current" {}

locals {
  https_enabled  = var.certificate_arn != null
  listener_port  = local.https_enabled ? 443 : 80
  alarm_actions  = var.alarm_sns_topic_arn == null ? [] : [var.alarm_sns_topic_arn]
  container_name = var.name
}

# --- Logging and cluster ---------------------------------------------------

resource "aws_cloudwatch_log_group" "this" {
  #checkov:skip=CKV_AWS_158:Logs use the default CloudWatch encryption; a customer-managed KMS key is a listed next improvement
  #checkov:skip=CKV_AWS_338:Retention is set per environment (dev 14d, prod 90d) as a cost trade-off, not hard-coded to 1 year
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "this" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# --- IAM: separate execution role (pull image, write logs) from task role ---

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what application code assumes. It starts with NO permissions;
# grant least-privilege policies to it from the calling environment.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# --- Networking: security groups -------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Load balancer ingress"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_listener" {
  for_each = toset(var.alb_ingress_cidrs)

  security_group_id = aws_security_group.alb.id
  description       = "Listener traffic"
  cidr_ipv4         = each.value
  from_port         = local.listener_port
  to_port           = local.listener_port
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_redirect" {
  for_each = local.https_enabled ? toset(var.alb_ingress_cidrs) : toset([])

  security_group_id = aws_security_group.alb.id
  description       = "HTTP, redirected to HTTPS"
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_tasks" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to tasks only"
  referenced_security_group_id = aws_security_group.tasks.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "tasks" {
  name        = "${var.name}-tasks"
  description = "Tasks accept traffic from the load balancer only"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-tasks" }
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "App port from ALB"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_https_out" {
  security_group_id = aws_security_group.tasks.id
  description       = "HTTPS egress (image pulls, AWS APIs) via NAT"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# --- Load balancer -----------------------------------------------------------

resource "aws_lb" "this" {
  #checkov:skip=CKV_AWS_91:ALB access logs need an S3 bucket and policy; listed as a next improvement
  #checkov:skip=CKV_AWS_150:Deletion protection is a variable: enabled in prod, disabled in dev so the dev stack can be destroyed
  #checkov:skip=CKV2_AWS_28:WAF is a listed next improvement; it adds a recurring per-rule cost
  name                       = var.name
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.enable_deletion_protection
}

resource "aws_lb_target_group" "this" {
  name                 = var.name
  port                 = var.container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "main" {
  load_balancer_arn = aws_lb.this.arn
  port              = local.listener_port
  protocol          = local.https_enabled ? "HTTPS" : "HTTP"
  ssl_policy        = local.https_enabled ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  count = local.https_enabled ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# --- Task definition and service -------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name                   = local.container_name
      image                  = var.image
      essential              = true
      user                   = "10001:10001"
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = var.container_port, protocol = "tcp" }]
      stopTimeout            = 30
      environment = [
        for key, value in merge({ PORT = tostring(var.container_port) }, var.environment_variables) :
        { name = key, value = value }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "app"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  name                               = var.name
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.this.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 30
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Roll back automatically if new tasks never become healthy.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = local.container_name
    container_port   = var.container_port
  }

  # Autoscaling owns desired_count after creation.
  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener.main]
}

# --- Autoscaling -----------------------------------------------------------

resource "aws_appautoscaling_target" "this" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_capacity
  max_capacity       = var.max_capacity
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.name}-cpu-target"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = var.cpu_target_percent
    scale_in_cooldown  = 120
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# --- Alarms ----------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.name}-alb-5xx"
  alarm_description   = "Target 5xx responses are elevated."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.name}-unhealthy-hosts"
  alarm_description   = "At least one target is failing health checks."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.this.arn_suffix
  }
}
