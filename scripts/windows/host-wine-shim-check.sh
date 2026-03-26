#!/usr/bin/env bash
set -euo pipefail

# Host-level Wine checks for Windows batch wrappers.
# Runs as an unprivileged user with an isolated disposable WINEPREFIX.

log() {
  echo "[host-wine-shim-check] $*"
}

if [[ "$(uname -s)" != "Linux" ]]; then
  log "SKIP: host Wine checks are Linux-only."
  exit 0
fi

if ! command -v wine >/dev/null 2>&1; then
  log "SKIP: wine is not installed on host."
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
wineprefix="$(mktemp -d /tmp/mdview-host-wineprefix.XXXXXX)"
stub_dir="$(mktemp -d /tmp/mdview-host-wine-stubs.XXXXXX)"
trap 'rm -rf "$wineprefix" "$stub_dir"' EXIT

cat >"$stub_dir/py.bat" <<'EOF'
@echo off
exit /b 33
EOF
cat >"$stub_dir/python.bat" <<'EOF'
@echo off
exit /b 44
EOF

win_path() {
  local path="$1"
  path="${path//\//\\}"
  printf 'Z:%s' "$path"
}

run_case() {
  local rel_bat="$1"
  local expected_rc="$2"
  local label="$3"
  local extra="${4:-}"

  local bat_win
  bat_win="$(win_path "$repo_root/$rel_bat")"
  local stub_win
  stub_win="$(win_path "$stub_dir")"

  set +e
  local out
  out="$(
    WINEPREFIX="$wineprefix" WINEDEBUG=-all \
      wine cmd /c "set PATH=$stub_win;%PATH% && \"$bat_win\" $extra" 2>&1
  )"
  local rc=$?
  set -e

  if [[ $rc -eq $expected_rc ]]; then
    log "PASS: $label (rc=$rc)"
    return 0
  fi

  log "FAIL: $label expected rc=$expected_rc, got rc=$rc"
  echo "$out"
  return 1
}

log "Case set A: py preferred over python"
run_case "scripts/windows/run-tool.bat" 33 "run-tool py preferred" "black"
run_case "scripts/windows/bootstrap.bat" 33 "bootstrap py preferred"

log "Case set B: python fallback when py absent"
rm -f "$stub_dir/py.bat"
run_case "scripts/windows/run-tool.bat" 44 "run-tool python fallback" "black"
run_case "scripts/windows/bootstrap.bat" 44 "bootstrap python fallback"

log "Case set C: missing interpreter path returns explicit failure"
rm -f "$stub_dir/python.bat"
run_case "scripts/windows/run-tool.bat" 1 "run-tool missing interpreter" "black"
run_case "scripts/windows/bootstrap.bat" 1 "bootstrap missing interpreter"

log "All host Wine shim checks passed."
