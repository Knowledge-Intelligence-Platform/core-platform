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

NAME_PREFIX="$(tfvar_of name_prefix)"
NAME_PREFIX="${NAME_PREFIX:-knowledge-intelligence}"
KNOWLEDGE_BUCKET="$(tfvar_of knowledge_bucket_name)"
PREFLIGHT_REGION="$(tfvar_of aws_region)"

echo "Checking what Terraform reads but never creates."

if [[ -z "${KNOWLEDGE_BUCKET}" || -z "${PREFLIGHT_REGION}" ]]; then
  echo "Could not read knowledge_bucket_name and aws_region from ${TFVARS_FILE}" >&2
  exit 1
fi

if ! aws s3api head-bucket --bucket "${KNOWLEDGE_BUCKET}" >/dev/null 2>&1; then
  echo "Knowledge bucket does not exist or is not reachable: ${KNOWLEDGE_BUCKET}" >&2
  echo "Terraform does not create it. Create it first, in ${PREFLIGHT_REGION}." >&2
  exit 1
fi

APPLICATION_SECRET="${NAME_PREFIX}/application"
SECRET_JSON="$(
  aws secretsmanager get-secret-value \
    --region "${PREFLIGHT_REGION}" \
    --secret-id "${APPLICATION_SECRET}" \
    --query SecretString \
    --output text 2>/dev/null || true
)"

if [[ -z "${SECRET_JSON}" ]]; then
  echo "Secret not found or unreadable: ${APPLICATION_SECRET}" >&2
  echo "Terraform reads it but never creates it. Create it first." >&2
  exit 1
fi

required_secret_keys=("OPENAI_API_KEY")
[[ "$(tfflag_of slack_enabled)" == "true" ]] &&
  required_secret_keys+=("SLACK_BOT_TOKEN" "SLACK_SIGNING_SECRET")
[[ "$(tfflag_of github_enabled)" == "true" ]] &&
  required_secret_keys+=("GITHUB_TOKEN")

missing_secret_keys=()
for key in "${required_secret_keys[@]}"; do
  if ! printf '%s' "${SECRET_JSON}" | grep -q "\"${key}\""; then
    missing_secret_keys+=("${key}")
  fi
done

if [[ ${#missing_secret_keys[@]} -gt 0 ]]; then
  echo "Secret ${APPLICATION_SECRET} is missing: ${missing_secret_keys[*]}" >&2
  echo "The service would start and then crash-loop without them." >&2
  exit 1
fi

echo "Initialising Terraform."
terraform -chdir="${INFRA_DIR}" init \
  -input=false \
  -backend-config="${BACKEND_CONFIG}"

echo "Creating the ECR repository first."
terraform -chdir="${INFRA_DIR}" apply \
  -input=false \
  -auto-approve \
  -var-file="${TFVARS_FILE}" \
  -target=aws_ecr_repository.application

AWS_REGION="$(
  terraform -chdir="${INFRA_DIR}" output -raw aws_region
)"
export AWS_REGION

echo "Building and pushing the latest container image."
"${SCRIPT_DIR}/build.sh"

echo "Deploying the remaining infrastructure."
terraform -chdir="${INFRA_DIR}" apply \
  -input=false \
  -auto-approve \
  -var-file="${TFVARS_FILE}"

APPCONFIG_APPLICATION_ID="$(
  terraform -chdir="${INFRA_DIR}" output -raw registry_appconfig_application_id 2>/dev/null || true
)"

if [[ -n "${APPCONFIG_APPLICATION_ID}" ]]; then
  APPCONFIG_ENVIRONMENT_ID="$(
    terraform -chdir="${INFRA_DIR}" output -raw registry_appconfig_environment_id
  )"

  EXISTING_DEPLOYMENT="$(
    aws appconfig list-deployments \
      --region "${AWS_REGION}" \
      --application-id "${APPCONFIG_APPLICATION_ID}" \
      --environment-id "${APPCONFIG_ENVIRONMENT_ID}" \
      --max-results 1 \
      --query 'Items[0].DeploymentNumber' \
      --output text
  )"

  if [[ "${EXISTING_DEPLOYMENT}" == "None" || -z "${EXISTING_DEPLOYMENT}" ]]; then
    KNOWLEDGE_BUCKET="$(
      terraform -chdir="${INFRA_DIR}" output -raw knowledge_bucket_name
    )"
    REGISTRY_KEY="$(
      terraform -chdir="${INFRA_DIR}" output -raw registry_document_key
    )"

    REGISTRY_VERSION="$(
      aws s3api head-object \
        --region "${AWS_REGION}" \
        --bucket "${KNOWLEDGE_BUCKET}" \
        --key "${REGISTRY_KEY}" \
        --query VersionId \
        --output text 2>/dev/null || true
    )"

    if [[ -z "${REGISTRY_VERSION}" || "${REGISTRY_VERSION}" == "None" ]]; then
      echo "No component registry has been published yet; the service will use its bundled snapshot."
    else
      APPCONFIG_PROFILE_ID="$(
        terraform -chdir="${INFRA_DIR}" output -raw registry_appconfig_profile_id
      )"
      APPCONFIG_STRATEGY_ID="$(
        terraform -chdir="${INFRA_DIR}" output -raw registry_appconfig_strategy_id
      )"

      echo "Making the published registry live for the first time."
      DEPLOYMENT_NUMBER="$(
        aws appconfig start-deployment \
          --region "${AWS_REGION}" \
          --application-id "${APPCONFIG_APPLICATION_ID}" \
          --environment-id "${APPCONFIG_ENVIRONMENT_ID}" \
          --configuration-profile-id "${APPCONFIG_PROFILE_ID}" \
          --deployment-strategy-id "${APPCONFIG_STRATEGY_ID}" \
          --configuration-version "${REGISTRY_VERSION}" \
          --description "First registry deployment from deploy.sh" \
          --query DeploymentNumber \
          --output text
      )"

      echo "Waiting for registry deployment ${DEPLOYMENT_NUMBER} to complete."
      aws appconfig wait deployment-complete \
        --region "${AWS_REGION}" \
        --application-id "${APPCONFIG_APPLICATION_ID}" \
        --environment-id "${APPCONFIG_ENVIRONMENT_ID}" \
        --deployment-number "${DEPLOYMENT_NUMBER}"
    fi
  else
    echo "The component registry is already deployed; leaving it to the registry repository."
  fi
fi

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
