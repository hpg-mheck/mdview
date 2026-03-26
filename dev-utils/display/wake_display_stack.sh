#!/usr/bin/env bash
set -u -o pipefail

usage() {
  cat <<'EOF'
Usage:
  dev-utils/display/wake_display_stack.sh [--force] [--dry-run] [--quiet]

Purpose:
  Attempt to wake and recover a local Linux display stack (Wayland or X11),
  including compositor output power-on hints and screensaver unlock signals.

Options:
  --force      Try stronger recovery steps (VT flip, display-manager restart).
  --dry-run    Print actions without executing them.
  --quiet      Reduce non-error output.
  -h, --help   Show this help text.
EOF
}

force_mode=0
dry_run=0
quiet=0

while (($#)); do
  case "$1" in
    --force)
      force_mode=1
      ;;
    --dry-run)
      dry_run=1
      ;;
    --quiet)
      quiet=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[wake-display] ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

log() {
  if [[ $quiet -eq 0 ]]; then
    echo "[wake-display] $*"
  fi
}

warn() {
  echo "[wake-display] WARN: $*" >&2
}

attempted=0
succeeded=0

run_cmd() {
  local desc="$1"
  shift
  attempted=$((attempted + 1))
  if [[ $dry_run -eq 1 ]]; then
    log "DRY-RUN: $desc :: $*"
    succeeded=$((succeeded + 1))
    return 0
  fi
  if "$@" >/dev/null 2>&1; then
    log "OK: $desc"
    succeeded=$((succeeded + 1))
    return 0
  fi
  warn "No-op or failed: $desc"
  return 1
}

run_root_cmd() {
  local desc="$1"
  shift
  if [[ $dry_run -eq 1 ]]; then
    attempted=$((attempted + 1))
    log "DRY-RUN(root): $desc :: $*"
    succeeded=$((succeeded + 1))
    return 0
  fi

  attempted=$((attempted + 1))
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    if "$@" >/dev/null 2>&1; then
      log "OK(root): $desc"
      succeeded=$((succeeded + 1))
      return 0
    fi
    warn "No-op or failed as root: $desc"
    return 1
  fi

  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    if sudo "$@" >/dev/null 2>&1; then
      log "OK(sudo): $desc"
      succeeded=$((succeeded + 1))
      return 0
    fi
    warn "No-op or failed via sudo: $desc"
    return 1
  fi

  warn "Skipping root-required step (need root/sudo): $desc"
  return 1
}

loginctl_prop() {
  local session_id="$1"
  local prop="$2"
  loginctl show-session "$session_id" -p "$prop" --value 2>/dev/null || true
}

select_graphical_session() {
  local sid type remote name state
  local preferred=""
  local fallback=""

  while IFS= read -r sid; do
    [[ -n "$sid" ]] || continue
    type="$(loginctl_prop "$sid" Type)"
    remote="$(loginctl_prop "$sid" Remote)"
    name="$(loginctl_prop "$sid" Name)"
    state="$(loginctl_prop "$sid" State)"
    if [[ "$type" =~ ^(wayland|x11)$ && "$remote" == "no" ]]; then
      if [[ "$name" == "${USER:-}" && "$state" == "active" ]]; then
        echo "$sid"
        return 0
      fi
      if [[ "$name" == "${USER:-}" && -z "$preferred" ]]; then
        preferred="$sid"
      fi
      if [[ -z "$fallback" ]]; then
        fallback="$sid"
      fi
    fi
  done < <(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}')

  if [[ -n "$preferred" ]]; then
    echo "$preferred"
    return 0
  fi
  if [[ -n "$fallback" ]]; then
    echo "$fallback"
    return 0
  fi
  return 1
}

run_session_cmd() {
  local desc="$1"
  shift
  attempted=$((attempted + 1))
  if [[ $dry_run -eq 1 ]]; then
    if [[ ${#session_env[@]} -gt 0 ]]; then
      log "DRY-RUN(session): $desc :: env ${session_env[*]} $*"
    else
      log "DRY-RUN(session): $desc :: $*"
    fi
    succeeded=$((succeeded + 1))
    return 0
  fi

  if [[ ${#session_env[@]} -gt 0 ]]; then
    if env "${session_env[@]}" "$@" >/dev/null 2>&1; then
      log "OK(session): $desc"
      succeeded=$((succeeded + 1))
      return 0
    fi
  else
    if "$@" >/dev/null 2>&1; then
      log "OK: $desc"
      succeeded=$((succeeded + 1))
      return 0
    fi
  fi

  warn "No-op or failed: $desc"
  return 1
}

log "Starting display wake sequence"
log "Session type: ${XDG_SESSION_TYPE:-unknown}"
log "Session id: ${XDG_SESSION_ID:-unknown}"

session_id=""
session_uid="$(id -u)"
session_xdg_runtime="${XDG_RUNTIME_DIR:-}"
session_dbus="${DBUS_SESSION_BUS_ADDRESS:-}"
session_wayland="${WAYLAND_DISPLAY:-}"
session_display="${DISPLAY:-}"
session_leader=""
session_env=()

if command -v loginctl >/dev/null 2>&1; then
  if [[ -n "${XDG_SESSION_ID:-}" ]]; then
    xdg_type="$(loginctl_prop "${XDG_SESSION_ID}" Type)"
    xdg_remote="$(loginctl_prop "${XDG_SESSION_ID}" Remote)"
    if [[ "$xdg_type" =~ ^(wayland|x11)$ && "$xdg_remote" == "no" ]]; then
      session_id="${XDG_SESSION_ID}"
    fi
  fi

  if [[ -z "$session_id" ]]; then
    session_id="$(select_graphical_session || true)"
  fi

  if [[ -n "$session_id" ]]; then
    session_uid_candidate="$(loginctl_prop "$session_id" User)"
    if [[ "$session_uid_candidate" =~ ^[0-9]+$ ]]; then
      session_uid="$session_uid_candidate"
    fi
    session_leader="$(loginctl_prop "$session_id" Leader)"

    run_cmd "Unlock login session ${session_id}" \
      loginctl unlock-session "$session_id" || true
    run_cmd "Activate login session ${session_id}" \
      loginctl activate "$session_id" || true
  else
    warn "Could not determine a graphical login session."
  fi
fi

if [[ -z "$session_xdg_runtime" ]]; then
  session_xdg_runtime="/run/user/${session_uid}"
fi

if [[ "$session_leader" =~ ^[0-9]+$ ]] && [[ -r "/proc/${session_leader}/environ" ]]
then
  while IFS= read -r -d '' entry; do
    case "$entry" in
      XDG_RUNTIME_DIR=*)
        session_xdg_runtime="${entry#*=}"
        ;;
      DBUS_SESSION_BUS_ADDRESS=*)
        session_dbus="${entry#*=}"
        ;;
      WAYLAND_DISPLAY=*)
        session_wayland="${entry#*=}"
        ;;
      DISPLAY=*)
        session_display="${entry#*=}"
        ;;
    esac
  done <"/proc/${session_leader}/environ"
fi

if [[ -z "$session_dbus" && -S "${session_xdg_runtime}/bus" ]]; then
  session_dbus="unix:path=${session_xdg_runtime}/bus"
fi

if [[ -z "$session_wayland" ]]; then
  for wayland_candidate in wayland-0 wayland-1 wayland-2; do
    if [[ -S "${session_xdg_runtime}/${wayland_candidate}" ]]; then
      session_wayland="$wayland_candidate"
      break
    fi
  done
fi

if [[ -z "$session_display" && -S /tmp/.X11-unix/X0 ]]; then
  session_display=":0"
fi

if [[ -n "$session_xdg_runtime" ]]; then
  session_env+=("XDG_RUNTIME_DIR=${session_xdg_runtime}")
fi
if [[ -n "$session_dbus" ]]; then
  session_env+=("DBUS_SESSION_BUS_ADDRESS=${session_dbus}")
fi
if [[ -n "$session_wayland" ]]; then
  session_env+=("WAYLAND_DISPLAY=${session_wayland}")
fi
if [[ -n "$session_display" ]]; then
  session_env+=("DISPLAY=${session_display}")
fi

log "Target graphical session: ${session_id:-unknown}"
log "Resolved runtime dir: ${session_xdg_runtime:-unknown}"
log "Resolved display: ${session_display:-unknown}"
log "Resolved wayland display: ${session_wayland:-unknown}"

if command -v gdbus >/dev/null 2>&1; then
  run_session_cmd "freedesktop screensaver SetActive(false)" \
    gdbus call --session \
      --dest org.freedesktop.ScreenSaver \
      --object-path /org/freedesktop/ScreenSaver \
      --method org.freedesktop.ScreenSaver.SetActive false || true

  run_session_cmd "GNOME screensaver SetActive(false)" \
    gdbus call --session \
      --dest org.gnome.ScreenSaver \
      --object-path /org/gnome/ScreenSaver \
      --method org.gnome.ScreenSaver.SetActive false || true

  run_session_cmd "GNOME screensaver SimulateUserActivity()" \
    gdbus call --session \
      --dest org.gnome.ScreenSaver \
      --object-path /org/gnome/ScreenSaver \
      --method org.gnome.ScreenSaver.SimulateUserActivity || true
elif command -v dbus-send >/dev/null 2>&1; then
  run_session_cmd "freedesktop screensaver SetActive(false) via dbus-send" \
    dbus-send --session \
      --dest=org.freedesktop.ScreenSaver \
      --type=method_call \
      /org/freedesktop/ScreenSaver \
      org.freedesktop.ScreenSaver.SetActive boolean:false || true
fi

if command -v swaymsg >/dev/null 2>&1; then
  run_session_cmd "sway output power on" swaymsg "output * power on" || true
fi

if command -v hyprctl >/dev/null 2>&1; then
  run_session_cmd "hyprland dpms on" hyprctl dispatch dpms on || true
fi

if command -v wlr-randr >/dev/null 2>&1; then
  wlr_randr_output=""
  if [[ ${#session_env[@]} -gt 0 ]]; then
    wlr_randr_output="$(env "${session_env[@]}" wlr-randr 2>/dev/null || true)"
  else
    wlr_randr_output="$(wlr-randr 2>/dev/null || true)"
  fi
  while IFS= read -r output_name; do
    [[ -n "$output_name" ]] || continue
    run_session_cmd "wlr-randr output ${output_name} on" \
      wlr-randr --output "$output_name" --on || true
  done < <(printf '%s\n' "$wlr_randr_output" | awk '/^[^[:space:]]/ {print $1}')
fi

if [[ -n "${session_display}" ]] && command -v xset >/dev/null 2>&1; then
  run_session_cmd "X11 DPMS force on" xset dpms force on || true
  run_session_cmd "X11 screensaver reset" xset s reset || true
fi

if [[ $force_mode -eq 1 ]]; then
  log "Force mode enabled: attempting stronger recovery actions."

  if command -v fgconsole >/dev/null 2>&1 && command -v chvt >/dev/null 2>&1
  then
    current_vt="$(fgconsole 2>/dev/null || true)"
    if [[ "$current_vt" =~ ^[0-9]+$ ]]; then
      run_root_cmd "VT flip ${current_vt} -> 2 -> ${current_vt}" \
        sh -c "chvt 2 && sleep 1 && chvt ${current_vt}" || true
    else
      warn "Skipping VT flip: could not determine active VT."
    fi
  fi

  if command -v systemctl >/dev/null 2>&1; then
    run_root_cmd "Restart display-manager.service" \
      systemctl restart display-manager.service || true
  fi
fi

if [[ $attempted -eq 0 ]]; then
  warn "No compatible wake action was available on this host."
  exit 2
fi

if [[ $succeeded -eq 0 ]]; then
  warn "Display wake sequence ran but no action succeeded."
  exit 1
fi

log "Completed display wake sequence (${succeeded}/${attempted} actions)."
exit 0
