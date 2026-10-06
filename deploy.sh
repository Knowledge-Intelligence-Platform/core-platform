#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly INFRA_DIR="${SCRIPT_DIR}/infra"
readonly BACKEND_CONFIG_INPUT="${BACKEND_CONFIG:-backend.hcl}"
readonly TFVARS_FILE_INPUT="${TFVARS_FILE:-terraform.tfvars}"
readonly BACKEND_CONFIG="$(
  [[ "${BACKEND_CONFIG_INPUT}" = /* ]] \
    && printf '%s' "${BACKEND_CONFIG_INPUT}" \
    || printf '%s/%s' "${INFRA_DIR}" "${BACKEND_CONFIG_INPUT}"
)"
readonly TFVARS_FILE="$(
  [[ "${TFVARS_FILE_INPUT}" = /* ]] \
    && printf '%s' "${TFVARS_FILE_INPUT}" \
    || printf '%s/%s' "${INFRA_DIR}" "${TFVARS_FILE_INPUT}"
)"

export TF_IN_AUTOMATION=true

on_error() {
  local exit_code=$?
  echo "Deployment failed at line ${BASH_LINENO[0]}." >&2
  exit "${exit_code}"
}
trap on_error ERR

for command in aws docker terraform; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

if [[ ! -f "${BACKEND_CONFIG}" ]]; then
  echo "Terraform backend configuration not found: ${BACKEND_CONFIG}" >&2
  exit 1
fi

if [[ ! -f "${TFVARS_FILE}" ]]; then
  echo "Terraform variable file not found: ${TFVARS_FILE}" >&2
  exit 1
fi

echo "Checking AWS credentials and Docker."
aws sts get-caller-identity >/dev/null
docker info >/dev/null

tfvar_of() {
  sed -n "s/^[[:space:]]*${1}[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "${TFVARS_FILE}" | head -1
}

tfflag_of() {
  sed -n "s/^[[:space:]]*${1}[[:space:]]*=[[:space:]]*\([a-z]*\).*/\1/p" "${TFVARS_FILE}" | head -1
}

has_tfvar() {
  grep -Eq "^[[:space:]]*${1}[[:space:]]*=" "${TFVARS_FILE}"
}

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

echo "Initialising Terraform."
terraform -chdir="${INFRA_DIR}" init \
  -input=false \
  -reconfigure \
  -backend-config="${BACKEND_CONFIG}"

echo "Deploying infrastructure."
terraform -chdir="${INFRA_DIR}" apply \
  -input=false \
  -auto-approve \
  -var-file="${TFVARS_FILE}"

AWS_REGION="$(
  terraform -chdir="${INFRA_DIR}" output -raw aws_region
)"
export AWS_REGION

VPC_ID="$(terraform -chdir="${INFRA_DIR}" output -raw vpc_id)"
PUBLIC_SUBNET_IDS="$(terraform -chdir="${INFRA_DIR}" output -json public_subnet_ids)"
echo "Core VPC: ${VPC_ID}"
echo "Public subnets: ${PUBLIC_SUBNET_IDS}"

echo "Building and pushing the latest container image."
"${SCRIPT_DIR}/build.sh"

ECS_CLUSTER_ARN="$(
  terraform -chdir="${INFRA_DIR}" output -raw ecs_cluster_arn
)"
ECS_SERVICE_NAME="$(
  terraform -chdir="${INFRA_DIR}" output -raw ecs_service_name
)"

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

API_URL="$(terraform -chdir="${INFRA_DIR}" output -raw api_gateway_url)"
SLACK_URL="$(terraform -chdir="${INFRA_DIR}" output -raw slack_events_url)"

echo "Deployment completed."
echo "API URL: ${API_URL}"
echo "Slack events URL: ${SLACK_URL}"
