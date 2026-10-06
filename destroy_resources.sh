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
    aws_lb.application|*.aws_lb.application|aws_lb_listener.http|*.aws_lb_listener.http|aws_ecs_service.application*|*.aws_ecs_service.application*|aws_nat_gateway.*|*.aws_nat_gateway.*|aws_eip.*|*.aws_eip.*)
      destroy_targets+=("-target=${address}")
      ;;
    *)
      preserved_resources+=("${address}")
      ;;
  esac
done <<<"${state_addresses}"

if ((${#destroy_targets[@]} == 0)); then
  echo "No idle-cost runtime resources were found in the Terraform state."
  exit 0
fi

echo "Resources intentionally preserved because they are network, storage,"
echo "identity, knowledge, API, logging or other non-idle-runtime resources:"
if ((${#preserved_resources[@]} == 0)); then
  echo "  - No preservable resources are present in state."
else
  printf '  - %s\n' "${preserved_resources[@]}"
fi
echo "  - The existing knowledge S3 bucket (not managed by this Terraform state)."
echo
echo "Idle-cost resources selected for destruction: ALB, ECS service/tasks,"
echo "and any NAT gateways or Elastic IPs present in the Terraform state."

plan_file="$(mktemp "${TMPDIR:-/tmp}/knowledge-intelligence-destroy.XXXXXX.tfplan")"
trap 'rm -f "${plan_file}"' EXIT

terraform -chdir="${INFRA_DIR}" plan \
  -destroy \
  -input=false \
  "${destroy_targets[@]}" \
  -out="${plan_file}"

terraform -chdir="${INFRA_DIR}" apply -input=false "${plan_file}"

echo
echo "Idle-cost runtime resources destroyed. The Core VPC, public subnets, routing,"
echo "knowledge content, credentials, container images and supporting resources were preserved."
