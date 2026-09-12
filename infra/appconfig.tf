resource "aws_appconfig_application" "registry" {
  count       = var.registry_appconfig_enabled ? 1 : 0
  name        = "${local.name_prefix}-component-registry"
  description = "Component registry consumed by the Knowledge Intelligence Platform."
}

resource "aws_appconfig_environment" "registry" {
  count          = var.registry_appconfig_enabled ? 1 : 0
  name           = "production"
  description    = "Deployment target for the component registry."
  application_id = aws_appconfig_application.registry[0].id
}

data "aws_iam_policy_document" "appconfig_retrieval_assume_role" {
  count = var.registry_appconfig_enabled ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["appconfig.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "appconfig_retrieval" {
  count = var.registry_appconfig_enabled ? 1 : 0

  statement {
    sid       = "ReadPublishedRegistry"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}/${trim(var.registry_prefix, "/")}/*"]
  }

  statement {
    sid    = "ListKnowledgeBucket"
    effect = "Allow"

    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
    ]

    resources = ["arn:aws:s3:::${var.knowledge_bucket_name}"]
  }

  statement {
    sid       = "ListBucketsForConfigurationLookup"
    effect    = "Allow"
    actions   = ["s3:ListAllMyBuckets"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "appconfig_retrieval" {
  count                = var.registry_appconfig_enabled ? 1 : 0
  name                 = "${local.name_prefix}-appconfig-retrieval-role"
  description          = "Lets AWS AppConfig read the published component registry from S3."
  assume_role_policy   = data.aws_iam_policy_document.appconfig_retrieval_assume_role[0].json
  permissions_boundary = var.permissions_boundary_arn
}

resource "aws_iam_policy" "appconfig_retrieval" {
  count       = var.registry_appconfig_enabled ? 1 : 0
  name        = "${local.name_prefix}-appconfig-retrieval-policy"
  description = "Reads the published component registry document."
  policy      = data.aws_iam_policy_document.appconfig_retrieval[0].json
}

resource "aws_iam_role_policy_attachment" "appconfig_retrieval" {
  count      = var.registry_appconfig_enabled ? 1 : 0
  role       = aws_iam_role.appconfig_retrieval[0].name
  policy_arn = aws_iam_policy.appconfig_retrieval[0].arn
}

resource "aws_appconfig_configuration_profile" "registry" {
  count              = var.registry_appconfig_enabled ? 1 : 0
  application_id     = aws_appconfig_application.registry[0].id
  name               = "components"
  description        = "The merged component registry document published by CI."
  location_uri       = "s3://${var.knowledge_bucket_name}/${trim(var.registry_prefix, "/")}/registry.yaml"
  retrieval_role_arn = aws_iam_role.appconfig_retrieval[0].arn
  type               = "AWS.Freeform"
}

resource "aws_appconfig_deployment_strategy" "registry" {
  count                          = var.registry_appconfig_enabled ? 1 : 0
  name                           = "${local.name_prefix}-registry-rollout"
  description                    = "Deploys the component registry with a bake time for rollback."
  deployment_duration_in_minutes = 0
  final_bake_time_in_minutes     = var.registry_bake_time_in_minutes
  growth_factor                  = 100
  growth_type                    = "LINEAR"
  replicate_to                   = "NONE"
}

data "aws_iam_policy_document" "appconfig_read" {
  count = var.registry_appconfig_enabled ? 1 : 0

  statement {
    sid    = "ReadComponentRegistryConfiguration"
    effect = "Allow"

    actions = [
      "appconfig:StartConfigurationSession",
      "appconfig:GetLatestConfiguration",
    ]

    resources = [
      "${aws_appconfig_application.registry[0].arn}/environment/${aws_appconfig_environment.registry[0].environment_id}/configuration/${aws_appconfig_configuration_profile.registry[0].configuration_profile_id}",
    ]
  }
}

resource "aws_iam_policy" "appconfig_read" {
  count       = var.registry_appconfig_enabled ? 1 : 0
  name        = "${local.name_prefix}-appconfig-read-policy"
  description = "Lets the service read the component registry from AppConfig."
  policy      = data.aws_iam_policy_document.appconfig_read[0].json
}

resource "aws_iam_role_policy_attachment" "appconfig_read" {
  count      = var.registry_appconfig_enabled ? 1 : 0
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.appconfig_read[0].arn
}
