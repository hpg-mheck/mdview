#!/usr/bin/env bash
set -euo pipefail

# Layered local verification for Windows shell shims while developing on Linux.
# Runs container preflight first, then host Wine checks when available.

log() {
  echo "[verify-windows-shims-linux] $*" >&2
}

if [[ "$(uname -s)" != "Linux" ]]; then
  log "SKIP: Linux-only local workflow."
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
podman_script="$repo_root/scripts/windows/podman-wine-smoke.sh"
host_script="$repo_root/scripts/windows/host-wine-shim-check.sh"

run_and_classify() {
  local label="$1"
  local script_path="$2"
  local tmp
  tmp="$(mktemp /tmp/mdview-${label}.XXXXXX)"
  set +e
  "$script_path" >"$tmp" 2>&1
  local rc=$?
  set -e

  cat "$tmp" >&2
  if [[ $rc -ne 0 ]]; then
    rm -f "$tmp"
    log "FAIL: $label check failed."
    exit $rc
  fi

  if grep -q "SKIP:" "$tmp"; then
    rm -f "$tmp"
    echo "skip"
    return 0
  fi

  rm -f "$tmp"
  echo "pass"
}

if [[ ! -x "$podman_script" ]]; then
  log "FAIL: missing executable $podman_script"
  exit 1
fi
if [[ ! -x "$host_script" ]]; then
  log "FAIL: missing executable $host_script"
  exit 1
fi

log "Step 1/2: containerized rootless Podman + Wine preflight"
podman_state="$(run_and_classify "podman-smoke" "$podman_script")"

log "Step 2/2: host Wine shim checks (isolated disposable WINEPREFIX)"
host_state="$(run_and_classify "host-wine" "$host_script")"

if [[ "$podman_state" == "skip" && "$host_state" == "skip" ]]; then
  log "SKIP: local Windows emulation unavailable. Use Windows CI as gate."
  exit 0
fi

if [[ "$host_state" == "pass" ]]; then
  log "PASS: host Wine executed shim checks successfully."
  exit 0
fi

log "PASS: container preflight succeeded; host Wine check skipped."
exit 0
