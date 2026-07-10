#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly pyenv_repo="https://github.com/pyenv/pyenv.git"
readonly pyenv_release="v2.7.3"
readonly managed_python_version="3.14.6"

usage() {
  cat <<'EOF'
Usage: ./install.sh [stage-2-options]

Install or bootstrap from this checkout.

Default behavior:
  - normal user: user-local non-development install
  - ./install.sh --mode dev: repo-local development install
  - ./install.sh --mode venv-only: repo-local toolchain-only refresh
  - sudo ./install.sh --system: system-level non-development install

Options:
  -h, --help  Show this help, then show the current stage-2 options when a
              usable Python interpreter is already available.
  --system    Pass through to stage 2 for a system-level standard install.
              Requires root or sudo and is invalid with development mode.
  --user-home PATH
              Use an explicit absolute home for user-scoped paths. Required
              when HOME is an isolated Codex or Claude environment.

All remaining options are passed through to scripts/install-stage-2.py.
EOF
}

python_is_supported() {
  local candidate="$1"
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

find_python() {
  local candidate
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

show_help() {
  usage

  local python_path
  if python_path="$(find_python 2>/dev/null)"; then
    printf '\nStage-2 options:\n\n'
    "$python_path" "${repo_root}/scripts/install-stage-2.py" --help
    return 0
  fi

  cat <<'EOF'

Stage-2 options are unavailable until a Python 3.9+ interpreter is present.
EOF
}

has_flag() {
  local flag="$1"
  shift
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "$flag" ]]; then
      return 0
    fi
  done
  return 1
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    printf 'apt-get\n'
    return 0
  fi
  if command -v dnf >/dev/null 2>&1; then
    printf 'dnf\n'
    return 0
  fi
  if command -v yum >/dev/null 2>&1; then
    printf 'yum\n'
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    printf 'brew\n'
    return 0
  fi
  return 1
}

install_root_dependencies() {
  local manager="$1"
  if [[ "$manager" == "apt-get" ]]; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      python3 python3-pip python3-venv git curl ca-certificates \
      build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
      libsqlite3-dev libffi-dev liblzma-dev tk-dev xz-utils
    return 0
  fi

  if [[ "$manager" == "brew" ]]; then
    brew update
    brew install python git curl
    return 0
  fi

  "$manager" install -y \
    python3 python3-pip git curl ca-certificates gcc make patch \
    zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel \
    openssl-devel libffi-devel xz xz-devel tk-devel findutils
}

ensure_user_pyenv_python() {
  local user_home="$1"
  local pyenv_root="${PYENV_ROOT:-${user_home}/.pyenv}"
  local pyenv_bin="${pyenv_root}/bin/pyenv"
  if ! command -v git >/dev/null 2>&1; then
    echo "install.sh: git is required for the non-root bootstrap path." >&2
    return 1
  fi
  # An existing checkout belongs to the operator and may intentionally be on
  # a detached reviewed tag. Project bootstrap must not update or switch it.
  if [[ ! -x "$pyenv_bin" ]]; then
    git clone --branch "$pyenv_release" --depth 1 "$pyenv_repo" "$pyenv_root"
  fi
  "$pyenv_bin" install -s "$managed_python_version"
  printf '%s\n' "${pyenv_root}/versions/${managed_python_version}/bin/python"
}

select_user_home() {
  local selected="${HOME}"
  local explicit="0"
  local expect_path="0"
  local arg

  for arg in "$@"; do
    if [[ "$expect_path" == "1" ]]; then
      selected="$arg"
      explicit="1"
      expect_path="0"
      continue
    fi
    case "$arg" in
      --user-home)
        expect_path="1"
        ;;
      --user-home=*)
        selected="${arg#--user-home=}"
        explicit="1"
        ;;
    esac
  done

  if [[ "$expect_path" == "1" ]]; then
    echo "install.sh: --user-home requires a path." >&2
    return 1
  fi
  if [[ "$explicit" == "1" ]]; then
    if [[ "$selected" != /* ]]; then
      echo "install.sh: --user-home must be an absolute path." >&2
      return 1
    fi
    if [[ ! -d "$selected" ]]; then
      echo "install.sh: --user-home must name an existing directory: $selected" >&2
      return 1
    fi
    (cd -- "$selected" && pwd -P)
    return 0
  fi

  case "${selected##*/}" in
    .claude-home|.codex-home)
      echo "install.sh: HOME is an isolated assistant environment: $selected" >&2
      echo "install.sh: rerun with --user-home /absolute/path." >&2
      return 1
      ;;
  esac
  (cd -- "$selected" && pwd -P)
}

confirm_root_user_install() {
  if [[ ! -t 0 ]]; then
    echo "install.sh: running as root without --system needs interactive confirmation." >&2
    echo "install.sh: rerun as a normal user for a user-local install," >&2
    echo "install.sh: or use ./install.sh --system for a system install." >&2
    return 1
  fi

  local response
  printf '%s' "install.sh: you are root without --system. Install only for root? [y/N] "
  read -r response
  case "$response" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
  esac

  echo "install.sh: aborted root-only non-system install." >&2
  echo "install.sh: rerun as a normal user for a user-local install," >&2
  echo "install.sh: or use ./install.sh --system for a system install." >&2
  return 1
}

main() {
  local stage_2_args=("$@")
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
      show_help
      return 0
    fi
  done

  local is_root="0"
  if [[ "$(id -u)" -eq 0 ]]; then
    is_root="1"
  fi
  local invoking_user="${SUDO_USER:-}"
  local using_sudo="0"
  if [[ "$is_root" == "1" && -n "$invoking_user" && "$invoking_user" != "root" ]]; then
    using_sudo="1"
  fi
  local system_requested="0"
  if has_flag "--system" "$@"; then
    system_requested="1"
  fi
  local selected_user_home="${HOME}"
  if [[ "$system_requested" != "1" ]]; then
    selected_user_home="$(select_user_home "$@")" || return 1
  fi

  if [[ "$system_requested" == "1" && "$is_root" != "1" ]]; then
    echo "install.sh: --system requires root privileges." >&2
    echo "install.sh: rerun with sudo for a system install, or omit --system" >&2
    echo "install.sh: for a user-local install." >&2
    return 1
  fi

  if [[ "$using_sudo" == "1" && "$system_requested" != "1" ]]; then
    echo "install.sh: sudo is only supported together with --system." >&2
    echo "install.sh: rerun as your normal user for a user-local install," >&2
    echo "install.sh: or use sudo ./install.sh --system for a system install." >&2
    return 1
  fi

  if [[ "$is_root" == "1" && "$system_requested" != "1" && "$using_sudo" != "1" ]]; then
    confirm_root_user_install || return 1
  fi

  local python_path
  if python_path="$(find_python)"; then
    :
  else
    if [[ "$is_root" == "1" ]]; then
      local manager
      manager="$(detect_package_manager)" || {
        echo "install.sh: unsupported package manager." >&2
        return 1
      }
      install_root_dependencies "$manager"
      python_path="$(find_python)" || {
        echo "install.sh: package-manager install did not provide Python 3.9+." >&2
        return 1
      }
    else
      python_path="$(ensure_user_pyenv_python "$selected_user_home")" || {
        echo "install.sh: no Python 3.9+ interpreter is available, and the" >&2
        echo "install.sh: user-local pyenv fallback did not succeed." >&2
        echo "install.sh: install Python 3.9+ first or rerun with sudo" >&2
        echo "install.sh: together with --system." >&2
        return 1
      }
    fi
  fi

  exec env \
    THEKNOWLEDGE_MANAGED_INSTALL_STAGE1=1 \
    "$python_path" "${repo_root}/scripts/install-stage-2.py" "${stage_2_args[@]}"
}

main "$@"
