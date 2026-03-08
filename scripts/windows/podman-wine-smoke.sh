#!/usr/bin/env bash
set -euo pipefail

# Rootless Podman + Wine smoke checks for Windows batch shims.
# This script is local-validation only; Windows CI remains authoritative.

IMAGE="${MDVIEW_WINE_IMAGE:-docker.io/scottyhardy/docker-wine:latest}"
PODMAN_ROOT="${MDVIEW_PODMAN_ROOT:-/tmp/podman-root}"
PODMAN_RUNROOT="${MDVIEW_PODMAN_RUNROOT:-/tmp/podman-runroot}"
PODMAN_TMPDIR="${MDVIEW_PODMAN_TMPDIR:-/tmp/podman-tmp}"
XDG_RUNTIME="${MDVIEW_PODMAN_XDG_RUNTIME:-/tmp/podman-xdg-runtime}"
OCI_RUNTIME="${MDVIEW_PODMAN_OCI_RUNTIME:-/usr/bin/crun}"

log() {
  echo "[podman-wine-smoke] $*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1"
    exit 2
  fi
}

podman_run() {
  XDG_RUNTIME_DIR="$XDG_RUNTIME" TMPDIR="$PODMAN_TMPDIR" \
    podman \
      --root "$PODMAN_ROOT" \
      --runroot "$PODMAN_RUNROOT" \
      --tmpdir "$PODMAN_TMPDIR" \
      --runtime "$OCI_RUNTIME" \
      "$@"
}

require_cmd podman
mkdir -p "$PODMAN_ROOT" "$PODMAN_RUNROOT" "$PODMAN_TMPDIR" "$XDG_RUNTIME"

set +e
podman_info_output="$(podman_run info 2>&1)"
podman_info_rc=$?
set -e
if [[ $podman_info_rc -ne 0 ]]; then
  if grep -Eqi "permission denied|rootless_lock|cannot clone|operation not permitted" <<<"$podman_info_output"; then
    log "SKIP: Podman unavailable in current permission context."
    log "Detail: $(head -n 1 <<<"$podman_info_output")"
    exit 0
  fi
  log "FAIL: Podman preflight failed."
  echo "$podman_info_output"
  exit 1
fi

log "Pulling image: $IMAGE"
podman_run pull "$IMAGE" >/dev/null

log "Wine version check"
podman_run run --rm --entrypoint /bin/bash --user 0 "$IMAGE" -lc \
  "wine --version" >/dev/null

log "Wine cmd smoke check"
set +e
cmd_output="$(
  podman_run run --rm --entrypoint /bin/bash --user 0 "$IMAGE" -lc \
    'WINEDEBUG=-all wine cmd /c "echo WINE_CMD_OK"' 2>&1
)"
cmd_rc=$?
set -e

if [[ $cmd_rc -ne 0 ]]; then
  diag_output="$(
    podman_run run --rm --entrypoint /bin/bash --user 0 "$IMAGE" -lc \
      'wine cmd /c "echo WINE_CMD_OK"' 2>&1 || true
  )"
  full_output="$cmd_output"$'\n'"$diag_output"
  if grep -Eqi "noexec filesystem|map_image_into_view failed to set|cannot apply additional memory protection|virtual_setup_exception" <<<"$full_output"; then
    log "SKIP: Wine cmd blocked by host noexec/memory-protection policy."
    log "Detail: $(head -n 1 <<<"$full_output")"
    exit 0
  fi
  log "FAIL: Wine cmd smoke test failed."
  echo "$full_output"
  exit 1
fi

stub_dir="$(mktemp -d /tmp/mdview-wine-stubs.XXXXXX)"
trap 'rm -rf "$stub_dir"' EXIT

cat >"$stub_dir/py.bat" <<'EOF'
@echo off
exit /b 33
EOF
cat >"$stub_dir/python.bat" <<'EOF'
@echo off
exit /b 44
EOF

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

run_bat_case() {
  local bat_path="$1"
  local expected_rc="$2"
  local label="$3"

  set +e
  out="$(
    podman_run run --rm --entrypoint /bin/bash --user 0 \
      -v "$repo_root:/workspace/repo:Z" \
      -v "$stub_dir:/workspace/stubs:Z" \
      "$IMAGE" -lc \
      "WINEDEBUG=-all wine cmd /c \"set PATH=Z:\\workspace\\stubs;%PATH% && Z:\\workspace\\repo\\$bat_path\""
      2>&1
  )"
  rc=$?
  set -e

  if [[ $rc -eq $expected_rc ]]; then
    log "PASS: $label exit propagation (rc=$rc)"
    return 0
  fi

  log "FAIL: $label expected rc=$expected_rc, got rc=$rc"
  echo "$out"
  return 1
}

run_bat_case "scripts\\windows\\run-tool.bat black" 33 "run-tool.bat py"
run_bat_case "scripts\\windows\\bootstrap.bat" 33 "bootstrap.bat py"

log "All Podman/Wine shim checks passed."
