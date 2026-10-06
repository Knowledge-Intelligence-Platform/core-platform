resource "aws_iam_openid_connect_provider" "github" {
  count           = var.registry_publish_enabled && var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = []
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.registry_publish_enabled && !var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? one(aws_iam_openid_connect_provider.github[*].arn) : one(data.aws_iam_openid_connect_provider.github[*].arn)
}

data "aws_iam_policy_document" "registry_publish_assume_role" {
  count = var.registry_publish_enabled ? 1 : 0

  statement {
    sid     = "GitHubActionsPublishesRegistry"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.registry_repository}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "registry_publish" {
  count = var.registry_publish_enabled ? 1 : 0

  statement {
    sid       = "PublishComponentRegistry"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.registry_prefix, "/")}/*"]
  }

  dynamic "statement" {
    for_each = var.registry_appconfig_enabled ? [1] : []

    content {
      sid    = "DeployComponentRegistry"
      effect = "Allow"

      actions = [
        "appconfig:StartDeployment",
        "appconfig:GetDeployment",
      ]

      resources = [
        aws_appconfig_environment.registry[0].arn,
        aws_appconfig_configuration_profile.registry[0].arn,
        aws_appconfig_deployment_strategy.registry[0].arn,
      ]
    }
  }

  dynamic "statement" {
    for_each = var.application_enabled ? [1] : []

    content {
      sid    = "RestartServiceOntoTheNewRegistry"
      effect = "Allow"

      actions = [
        "ecs:UpdateService",
        "ecs:DescribeServices",
      ]

      resources = [aws_ecs_service.application[0].id]
    }
  }
}

resource "aws_iam_role" "registry_publish" {
  count                = var.registry_publish_enabled ? 1 : 0
  name                 = "${local.name_prefix}-registry-publish-role"
  description          = "Assumed by the component registry repository to publish the merged registry."
  assume_role_policy   = data.aws_iam_policy_document.registry_publish_assume_role[0].json
  permissions_boundary = var.permissions_boundary_arn

  tags = {
    Component = "component-registry"
  }
}

resource "aws_iam_policy" "registry_publish" {
  count       = var.registry_publish_enabled ? 1 : 0
  name        = "${local.name_prefix}-registry-publish-policy"
  description = "Writes the merged component registry document."
  policy      = data.aws_iam_policy_document.registry_publish[0].json
}

resource "aws_iam_role_policy_attachment" "registry_publish" {
  count      = var.registry_publish_enabled ? 1 : 0
  role       = aws_iam_role.registry_publish[0].name
  policy_arn = aws_iam_policy.registry_publish[0].arn
}
