#!/usr/bin/env bash

set -Eeuo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly INFRA_DIR="${ROOT_DIR}/infra"

infra_path() {
  [[ "${1}" = /* ]] && printf '%s' "${1}" || printf '%s/%s' "${INFRA_DIR}" "${1}"
}

readonly BACKEND_CONFIG="$(infra_path "${BACKEND_CONFIG:-backend.hcl}")"
readonly TFVARS_FILE="$(infra_path "${TFVARS_FILE:-terraform.tfvars}")"
readonly AUTO_APPROVE="${AUTO_APPROVE:-false}"

export TF_IN_AUTOMATION=true

PLAN_FILE=""

on_error() {
  local exit_code=$?
  echo "${0##*/} failed at line ${BASH_LINENO[0]}." >&2
  exit "${exit_code}"
}

cleanup() {
  [[ -n "${PLAN_FILE}" ]] && rm -f "${PLAN_FILE}"
  return 0
}

trap on_error ERR
trap cleanup EXIT

require_commands() {
  local command
  for command in "$@"; do
    if ! command -v "${command}" >/dev/null 2>&1; then
      echo "Required command not found: ${command}" >&2
      exit 1
    fi
  done
}

require_terraform_inputs() {
  local file
  for file in "${BACKEND_CONFIG}" "${TFVARS_FILE}"; do
    if [[ ! -f "${file}" ]]; then
      echo "Terraform input not found: ${file}" >&2
      exit 1
    fi
  done
}

require_aws_identity() {
  local account
  account="$(aws sts get-caller-identity --query Account --output text)"
  echo "AWS account: ${account}"
}

tfvar_of() {
  sed -n "s/^[[:space:]]*${1}[[:space:]]*=[[:space:]]*\"\([^\"]*\)\".*/\1/p" "${TFVARS_FILE}" | head -1
}

tfflag_of() {
  sed -n "s/^[[:space:]]*${1}[[:space:]]*=[[:space:]]*\([a-z]*\).*/\1/p" "${TFVARS_FILE}" | head -1
}

has_tfvar() {
  grep -Eq "^[[:space:]]*${1}[[:space:]]*=" "${TFVARS_FILE}"
}

terraform_init() {
  echo "Initialising Terraform."
  terraform -chdir="${INFRA_DIR}" init \
    -input=false \
    -reconfigure \
    -backend-config="${BACKEND_CONFIG}" \
    >/dev/null
}

terraform_output() {
  terraform -chdir="${INFRA_DIR}" output -raw "${1}"
}

confirm_plan() {
  if [[ "${AUTO_APPROVE}" == "true" ]]; then
    echo "AUTO_APPROVE=true: applying without confirmation."
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "No terminal to confirm the plan. Review it and rerun with AUTO_APPROVE=true." >&2
    exit 1
  fi
  local answer
  read -r -p "Apply this plan? Type 'yes' to continue: " answer
  if [[ "${answer}" != "yes" ]]; then
    echo "Plan not applied."
    exit 1
  fi
}

apply_reviewed_plan() {
  local status=0
  PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/knowledge-intelligence.XXXXXX")"

  terraform -chdir="${INFRA_DIR}" plan \
    -input=false \
    -detailed-exitcode \
    -var-file="${TFVARS_FILE}" \
    -out="${PLAN_FILE}" \
    "$@" || status=$?

  case "${status}" in
    0)
      echo "No infrastructure changes."
      return 0
      ;;
    2) ;;
    *)
      echo "Terraform plan failed." >&2
      exit "${status}"
      ;;
  esac

  confirm_plan
  terraform -chdir="${INFRA_DIR}" apply -input=false "${PLAN_FILE}"
}
