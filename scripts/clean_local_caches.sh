#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/clean_local_caches.sh [--dry-run|--apply]

Removes repo-local generated cache clutter while preserving stateful ignored
directories such as data/, venv/, .engram/, and docs/superpowers/.
USAGE
}

mode="dry-run"
case "${1:---dry-run}" in
  --dry-run)
    mode="dry-run"
    ;;
  --apply)
    mode="apply"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ -n "${ENGRAM_CACHE_CLEAN_ROOT:-}" ]]; then
  root="${ENGRAM_CACHE_CLEAN_ROOT}"
else
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  root="$(cd -- "${script_dir}/.." && pwd)"
fi

if [[ ! -d "${root}" ]]; then
  echo "Cache clean root does not exist: ${root}" >&2
  exit 2
fi

protected_prunes=(
  "${root}/.git"
  "${root}/.claude"
  "${root}/.engram"
  "${root}/.planning"
  "${root}/data"
  "${root}/docs/superpowers"
  "${root}/venv"
)

find_prunes=()
for protected in "${protected_prunes[@]}"; do
  find_prunes+=( -path "${protected}" -prune -o )
done

relative_path() {
  local path="$1"
  if [[ "${path}" == "${root}" ]]; then
    printf '.\n'
  else
    printf './%s\n' "${path#"${root}/"}"
  fi
}

collect_targets() {
  {
    find "${root}" "${find_prunes[@]}" \
      -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".pytest_tmp" \) \
      -print -prune
    find "${root}" "${find_prunes[@]}" \
      -type f \( -name "*.pyc" -o -name "*.pyo" \) \
      ! -path "*/__pycache__/*" \
      -print
  } | sort
}

target_count=0
while IFS= read -r target; do
  [[ -n "${target}" ]] || continue
  target_count=$((target_count + 1))
  relative_path "${target}"
  if [[ "${mode}" == "apply" ]]; then
    rm -rf -- "${target}"
  fi
done < <(collect_targets)

if [[ "${target_count}" -eq 0 ]]; then
  echo "No local cache targets found."
fi
