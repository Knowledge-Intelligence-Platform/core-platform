#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly INFRA_DIR="${SCRIPT_DIR}/infra"
BACKEND_CONFIG_INPUT="${BACKEND_CONFIG:-backend.hcl}"
TFVARS_FILE_INPUT="${TFVARS_FILE:-terraform.tfvars}"
[[ "${BACKEND_CONFIG_INPUT}" = /* ]] || BACKEND_CONFIG_INPUT="${INFRA_DIR}/${BACKEND_CONFIG_INPUT}"
[[ "${TFVARS_FILE_INPUT}" = /* ]] || TFVARS_FILE_INPUT="${INFRA_DIR}/${TFVARS_FILE_INPUT}"
readonly BACKEND_CONFIG="${BACKEND_CONFIG_INPUT}"
readonly TFVARS_FILE="${TFVARS_FILE_INPUT}"

if [[ ! -f "${TFVARS_FILE}" ]]; then
  echo "Terraform variables file not found: ${TFVARS_FILE}" >&2
  exit 1
fi

for command in aws terraform; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

tfvar_of() {
  sed -n "s/^[[:space:]]*${1}[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "${TFVARS_FILE}" | head -1
}

AWS_REGION="$(tfvar_of aws_region)"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="$(tfvar_of aws_account_id)"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
NAME_PREFIX="$(tfvar_of name_prefix)"
NAME_PREFIX="${NAME_PREFIX:-knowledge-intelligence}"
VECTOR_BUCKET_NAME="$(tfvar_of vector_bucket_name)"
VECTOR_BUCKET_NAME="${VECTOR_BUCKET_NAME:-knowledge-intelligence-vectors}"

terraform -chdir="${INFRA_DIR}" init \
  -input=false \
  -reconfigure \
  -backend-config="${BACKEND_CONFIG}"

import_if_missing() {
  local address="$1"
  local resource_id="$2"

  if terraform -chdir="${INFRA_DIR}" state show "${address}" >/dev/null 2>&1; then
    echo "Already in state: ${address}"
    return 0
  fi

  echo "Importing ${address}"
  terraform -chdir="${INFRA_DIR}" import \
    -input=false \
    -var-file="${TFVARS_FILE}" \
    "${address}" "${resource_id}"
}

if [[ -n "${AWS_REGION}" && -n "${AWS_ACCOUNT_ID}" ]]; then
  ALB_ARN="$(aws elbv2 describe-load-balancers \
    --region "${AWS_REGION}" \
    --names "${NAME_PREFIX}" \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text 2>/dev/null || true)"
  [[ "${ALB_ARN}" != "None" && -n "${ALB_ARN}" ]] && import_if_missing aws_lb.application "${ALB_ARN}"

  if [[ "${ALB_ARN}" != "None" && -n "${ALB_ARN}" ]]; then
    LISTENER_ARN="$(aws elbv2 describe-listeners \
      --region "${AWS_REGION}" \
      --load-balancer-arn "${ALB_ARN}" \
      --query 'Listeners[?Port==`80`].ListenerArn | [0]' \
      --output text 2>/dev/null || true)"
    [[ "${LISTENER_ARN}" != "None" && -n "${LISTENER_ARN}" ]] && import_if_missing aws_lb_listener.http "${LISTENER_ARN}"
  fi

  TARGET_GROUP_ARN="$(aws elbv2 describe-target-groups \
    --region "${AWS_REGION}" \
    --names "${NAME_PREFIX}-api" \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text 2>/dev/null || true)"
  [[ "${TARGET_GROUP_ARN}" != "None" && -n "${TARGET_GROUP_ARN}" ]] && import_if_missing aws_lb_target_group.application "${TARGET_GROUP_ARN}"

  for log_group in "/aws/apigateway/${NAME_PREFIX}" "/ecs/${NAME_PREFIX}"; do
    if aws logs describe-log-groups \
      --region "${AWS_REGION}" \
      --log-group-name-prefix "${log_group}" \
      --query "logGroups[?logGroupName=='${log_group}'].logGroupName | [0]" \
      --output text 2>/dev/null | grep -qx "${log_group}"; then
      if [[ "${log_group}" == "/aws/apigateway/${NAME_PREFIX}" ]]; then
        import_if_missing aws_cloudwatch_log_group.api_gateway "${log_group}"
      else
        import_if_missing aws_cloudwatch_log_group.application "${log_group}"
      fi
    fi
  done

  for role_name in \
    "${NAME_PREFIX}-execution-role" \
    "${NAME_PREFIX}-task-role" \
    "${NAME_PREFIX}-vector-ingestion-role"; do
    if aws iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
      case "${role_name}" in
        "${NAME_PREFIX}-execution-role") import_if_missing aws_iam_role.ecs_execution "${role_name}" ;;
        "${NAME_PREFIX}-task-role") import_if_missing aws_iam_role.ecs_task "${role_name}" ;;
        *) import_if_missing aws_iam_role.vector_ingestion "${role_name}" ;;
      esac
    fi
  done

  for policy_name in \
    "${NAME_PREFIX}-bedrock-runtime-policy" \
    "${NAME_PREFIX}-execution-secrets-policy" \
    "${NAME_PREFIX}-knowledge-bucket-read-policy" \
    "${NAME_PREFIX}-feedback-write-policy" \
    "${NAME_PREFIX}-vector-runtime-policy" \
    "${NAME_PREFIX}-vector-ingestion-policy"; do
    policy_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${policy_name}"
    if aws iam get-policy --policy-arn "${policy_arn}" >/dev/null 2>&1; then
      case "${policy_name}" in
        "${NAME_PREFIX}-bedrock-runtime-policy") import_if_missing aws_iam_policy.bedrock_runtime "${policy_arn}" ;;
        "${NAME_PREFIX}-execution-secrets-policy") import_if_missing 'aws_iam_policy.ecs_execution_secrets[0]' "${policy_arn}" ;;
        "${NAME_PREFIX}-knowledge-bucket-read-policy") import_if_missing aws_iam_policy.knowledge_bucket_read "${policy_arn}" ;;
        "${NAME_PREFIX}-feedback-write-policy") import_if_missing aws_iam_policy.feedback_write "${policy_arn}" ;;
        "${NAME_PREFIX}-vector-runtime-policy") import_if_missing aws_iam_policy.vector_runtime "${policy_arn}" ;;
        *) import_if_missing aws_iam_policy.vector_ingestion "${policy_arn}" ;;
      esac
    fi
  done

  if aws ecr describe-repositories \
    --region "${AWS_REGION}" \
    --repository-names "${NAME_PREFIX}" >/dev/null 2>&1; then
    import_if_missing aws_ecr_repository.application "${NAME_PREFIX}"
    import_if_missing aws_ecr_lifecycle_policy.application "${NAME_PREFIX}"
  fi

  VECTOR_BUCKET_ARN="arn:aws:s3vectors:${AWS_REGION}:${AWS_ACCOUNT_ID}:bucket/${VECTOR_BUCKET_NAME}"
  if aws s3vectors get-vector-bucket \
    --region "${AWS_REGION}" \
    --vector-bucket-name "${VECTOR_BUCKET_NAME}" >/dev/null 2>&1; then
    import_if_missing aws_s3vectors_vector_bucket.platform_knowledge "${VECTOR_BUCKET_ARN}"

    if aws s3vectors get-index \
      --region "${AWS_REGION}" \
      --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
      --index-name platform-knowledge >/dev/null 2>&1; then
      import_if_missing aws_s3vectors_index.platform_knowledge "${VECTOR_BUCKET_ARN}/index/platform-knowledge"
    fi
  fi
fi

echo "Existing resource import completed. Review terraform plan before applying."
