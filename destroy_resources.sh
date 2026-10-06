#!/usr/bin/env bash

set -Eeuo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/terraform.sh"

require_commands aws terraform
require_terraform_inputs

echo "Checking AWS credentials."
require_aws_identity

terraform_init

declare -a destroy_targets=()
declare -a preserved_resources=()

while IFS= read -r address; do
  [[ -z "${address}" ]] && continue

  case "${address}" in
    aws_lb.application|*.aws_lb.application|aws_ecs_service.application*|*.aws_ecs_service.application*)
      destroy_targets+=("-target=${address}")
      ;;
    *)
      preserved_resources+=("${address}")
      ;;
  esac
done <<<"$(terraform -chdir="${INFRA_DIR}" state list)"

if ((${#destroy_targets[@]} == 0)); then
  echo "No idle-cost runtime resources were found in the Terraform state."
  exit 0
fi

echo "Resources preserved because they have no idle cost:"
if ((${#preserved_resources[@]} == 0)); then
  echo "  - No preservable resources are present in state."
else
  printf '  - %s\n' "${preserved_resources[@]}"
fi
echo "  - The existing knowledge S3 bucket (not managed by this Terraform state)."
echo
echo "Idle-cost resources selected for destruction: the ALB and the ECS service."
echo "Terraform also removes what depends on them: the ALB listener and the API Gateway"
echo "integration, route and stage. The plan below lists every resource."

apply_reviewed_plan -destroy "${destroy_targets[@]}"

echo
echo "Idle-cost resources destroyed. The VPC, knowledge base, container images, logs"
echo "and other no-idle-cost resources were preserved."
echo "Run ./deploy.sh to recreate them."
