#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly INFRA_DIR="${SCRIPT_DIR}/infra"

for command in terraform mktemp; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

declare -a destroy_targets=()
declare -a preserved_resources=()

state_addresses="$(terraform -chdir="${INFRA_DIR}" state list)"

while IFS= read -r address; do
  [[ -z "${address}" ]] && continue

  case "${address}" in
    data.*|*.data.*|aws_s3_*|*.aws_s3_*|aws_s3vectors_*|*.aws_s3vectors_*|aws_secretsmanager_*|*.aws_secretsmanager_*|aws_ecr_*|*.aws_ecr_*)
      preserved_resources+=("${address}")
      ;;
    aws_appconfig_*|*.aws_appconfig_*)
      preserved_resources+=("${address}")
      ;;
    aws_iam_role.appconfig_retrieval*|aws_iam_policy.appconfig_retrieval*|aws_iam_role_policy_attachment.appconfig_retrieval*)
      preserved_resources+=("${address}")
      ;;
    *)
      destroy_targets+=("-target=${address}")
      ;;
  esac
done <<<"${state_addresses}"

if ((${#destroy_targets[@]} == 0)); then
  echo "No destroyable resources were found in the Terraform state."
  exit 0
fi

echo "Terraform-managed S3, S3 Vectors, Secrets Manager, ECR, and AppConfig resources"
echo "intentionally preserved:"
if ((${#preserved_resources[@]} == 0)); then
  echo "  - No preservable resources are present in state."
else
  printf '  - %s\n' "${preserved_resources[@]}"
fi
echo "  - The existing knowledge S3 bucket (not managed by this Terraform state)."
echo
echo "All other managed resources will be destroyed, including ALB, API Gateway,"
echo "ECS, CloudWatch log groups, security groups, and IAM resources."

plan_file="$(mktemp "${TMPDIR:-/tmp}/knowledge-intelligence-destroy.XXXXXX.tfplan")"
trap 'rm -f "${plan_file}"' EXIT

terraform -chdir="${INFRA_DIR}" plan \
  -destroy \
  -input=false \
  "${destroy_targets[@]}" \
  -out="${plan_file}"

terraform -chdir="${INFRA_DIR}" apply -input=false "${plan_file}"

echo
echo "Idle-cost resources destroyed. S3, S3 Vectors, Secrets Manager, ECR, and AppConfig"
echo "resources were preserved, so the registry keeps its identifiers and deployment history."
