#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper for long-standing mdview setup entry points.
# `./install.sh` is now the canonical Unix-like installer/bootstrap command.
# Keep this wrapper tiny and argument-transparent so older automation can
# reach the new stage-one entry point without reimplementing any policy here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FORWARD_ARGS=("$@")

# Backward-compatible passthrough for legacy invocation styles that included a
# leading `--` only to forward arguments to the old Python installer.
if [ "${#FORWARD_ARGS[@]}" -gt 0 ] && [ "${FORWARD_ARGS[0]}" = "--" ]; then
  FORWARD_ARGS=("${FORWARD_ARGS[@]:1}")
fi

exec "$ROOT_DIR/install.sh" "${FORWARD_ARGS[@]}"
