#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/terraform.sh"

require_commands aws docker terraform
require_terraform_inputs

echo "Checking AWS credentials and Docker."
require_aws_identity
docker info >/dev/null

if [[ "$(tfflag_of application_enabled)" != "true" ]]; then
  echo "Set application_enabled=true to deploy the Core Platform application." >&2
  exit 1
fi

NAME_PREFIX="$(tfvar_of name_prefix)"
NAME_PREFIX="${NAME_PREFIX:-knowledge-intelligence}"
APPLICATION_SECRET_NAME="$(tfvar_of application_secret_name)"
APPLICATION_SECRET_NAME="${APPLICATION_SECRET_NAME:-${NAME_PREFIX}/application}"
KNOWLEDGE_BUCKET="$(tfvar_of knowledge_bucket_name)"
PREFLIGHT_REGION="$(tfvar_of aws_region)"

echo "Checking externally managed prerequisites."

if [[ -z "${KNOWLEDGE_BUCKET}" || -z "${PREFLIGHT_REGION}" ]]; then
  echo "Could not read knowledge_bucket_name and aws_region from ${TFVARS_FILE}" >&2
  exit 1
fi

if ! has_tfvar vpc_cidr || ! has_tfvar public_subnet_cidrs; then
  echo "Core network inputs vpc_cidr and public_subnet_cidrs are required in ${TFVARS_FILE}" >&2
  exit 1
fi

if ! aws s3api head-bucket --bucket "${KNOWLEDGE_BUCKET}" >/dev/null 2>&1; then
  echo "Knowledge bucket does not exist or is not reachable: ${KNOWLEDGE_BUCKET}" >&2
  echo "Terraform does not create it. Create it first, in ${PREFLIGHT_REGION}." >&2
  exit 1
fi

required_secret_keys=()
[[ "$(tfflag_of query_api_enabled)" == "true" ]] &&
  required_secret_keys+=("QUERY_TOKENS")
[[ "$(tfflag_of slack_enabled)" == "true" ]] &&
  required_secret_keys+=("SLACK_BOT_TOKEN" "SLACK_SIGNING_SECRET")
[[ "$(tfflag_of admin_reindex_enabled)" == "true" ]] &&
  required_secret_keys+=("ADMIN_TOKEN")

if [[ ${#required_secret_keys[@]} -gt 0 ]]; then
  if ! SECRET_JSON="$(aws secretsmanager get-secret-value \
    --region "${PREFLIGHT_REGION}" --secret-id "${APPLICATION_SECRET_NAME}" \
    --query SecretString --output text 2>/dev/null)"; then
    echo "Application secret not found or unreadable: ${APPLICATION_SECRET_NAME}" >&2
    echo "Create it in Secrets Manager or set application_secret_name in ${TFVARS_FILE}." >&2
    exit 1
  fi
  for key in "${required_secret_keys[@]}"; do
    if ! printf '%s' "${SECRET_JSON}" | grep -q "\"${key}\""; then
      echo "Application secret is missing required key: ${key}" >&2
      exit 1
    fi
  done
  unset SECRET_JSON
fi

terraform_init

echo "Planning infrastructure changes."
apply_reviewed_plan

AWS_REGION="$(terraform_output aws_region)"
export AWS_REGION

echo "Core VPC: $(terraform_output vpc_id)"
echo "Public subnets: $(terraform -chdir="${INFRA_DIR}" output -json public_subnet_ids)"

echo "Building and pushing the latest container image."
"${ROOT_DIR}/build.sh"

ECS_CLUSTER_ARN="$(terraform_output ecs_cluster_arn)"
ECS_SERVICE_NAME="$(terraform_output ecs_service_name)"

echo "Starting a fresh ECS deployment for the latest image."
aws ecs update-service \
  --region "${AWS_REGION}" \
  --cluster "${ECS_CLUSTER_ARN}" \
  --service "${ECS_SERVICE_NAME}" \
  --force-new-deployment \
  >/dev/null

echo "Waiting for ECS to become stable."
aws ecs wait services-stable \
  --region "${AWS_REGION}" \
  --cluster "${ECS_CLUSTER_ARN}" \
  --services "${ECS_SERVICE_NAME}"

echo "Deployment completed."
echo "API URL: $(terraform_output api_gateway_url)"
echo "Slack events URL: $(terraform_output slack_events_url)"
