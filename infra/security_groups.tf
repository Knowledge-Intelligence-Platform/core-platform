resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Controls inbound and outbound traffic for the Knowledge Intelligence ALB."
  vpc_id      = aws_vpc.this.id

  tags = {
    Name      = "${local.name_prefix}-alb-sg"
    Component = "load-balancer"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_ipv4" {
  for_each = var.alb_ingress_ipv4_cidrs

  security_group_id = aws_security_group.alb.id

  description = "Allow HTTP traffic to the stakeholder demo endpoint."

  ip_protocol = "tcp"
  from_port   = 80
  to_port     = 80
  cidr_ipv4   = each.value

  tags = {
    Name      = "${local.name_prefix}-alb-http-${replace(each.value, "/", "-")}"
    Component = "load-balancer"
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name_prefix}-ecs-tasks-sg"
  description = "Controls traffic to and from Knowledge Intelligence ECS tasks."
  vpc_id      = aws_vpc.this.id

  tags = {
    Name      = "${local.name_prefix}-ecs-tasks-sg"
    Component = "application-runtime"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "ecs_from_alb" {
  security_group_id = aws_security_group.ecs_tasks.id

  description = "Allow FastAPI traffic only from the application load balancer."

  ip_protocol                  = "tcp"
  from_port                    = local.container_port
  to_port                      = local.container_port
  referenced_security_group_id = aws_security_group.alb.id

  tags = {
    Name      = "${local.name_prefix}-ecs-from-alb"
    Component = "application-runtime"
  }
}

resource "aws_vpc_security_group_egress_rule" "alb_to_ecs" {
  security_group_id = aws_security_group.alb.id

  description = "Allow the ALB to forward requests and health checks to ECS tasks."

  ip_protocol                  = "tcp"
  from_port                    = local.container_port
  to_port                      = local.container_port
  referenced_security_group_id = aws_security_group.ecs_tasks.id

  tags = {
    Name      = "${local.name_prefix}-alb-to-ecs"
    Component = "load-balancer"
  }
}

resource "aws_vpc_security_group_egress_rule" "ecs_https_ipv4" {
  for_each = var.ecs_outbound_https_ipv4_cidrs

  security_group_id = aws_security_group.ecs_tasks.id

  description = "Allow application and AWS API access over HTTPS."

  ip_protocol = "tcp"
  from_port   = 443
  to_port     = 443
  cidr_ipv4   = each.value

  tags = {
    Name      = "${local.name_prefix}-ecs-https-${replace(each.value, "/", "-")}"
    Component = "application-runtime"
  }
}
