resource "aws_lb" "application" {
  name               = local.alb_name
  internal           = false
  load_balancer_type = "application"

  security_groups = [
    aws_security_group.alb.id
  ]

  subnets = aws_subnet.public[*].id

  enable_deletion_protection = var.alb_deletion_protection_enabled
  idle_timeout               = 60

  drop_invalid_header_fields = true

  tags = {
    Name      = local.alb_name
    Component = "load-balancer"
  }
}

resource "aws_lb_target_group" "application" {
  name = local.target_group_name

  port        = local.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.this.id

  deregistration_delay = 30

  health_check {
    enabled = true

    protocol = "HTTP"
    port     = "traffic-port"
    path     = "/health"

    matcher = "200"

    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name      = local.target_group_name
    Component = "application-runtime"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.application.arn

  port     = 80
  protocol = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.application.arn
  }

  tags = {
    Component = "load-balancer"
  }
}
