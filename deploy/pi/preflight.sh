#!/usr/bin/env bash
#
# Read-only prerequisite survey for the BrewCTL hardware service.
#
#   ./deploy/pi/preflight.sh                             # on the Pi
#   ssh tomas@coldbrewer.local 'bash -s' < $0            # from a checkout, before
#                                                        # the Pi has the code
#
# Installs nothing, writes nothing, restarts nothing. Safe to run on a Pi that is
# mid-brew -- which is the point: the answer to "can this box run the service"
# should never require taking the current one down.
#
# Run it before the first install.sh. Every check here maps to something that
# otherwise fails deep inside pip, or -- worse -- succeeds and leaves the service
# driving MockScale/MockValve while /health cheerfully reports healthy.
#
# Exits non-zero if any HARD check failed, so it works as a gate. Missing packages
# are reported as an apt line to run, not installed: that is the operator's call.

set -uo pipefail   # deliberately no -e; a failed check must not abort the survey

REPO_DIR="${BREWCTL_REPO_DIR:-$HOME/coldbrewer}"
SERVICE_USER="${BREWCTL_USER:-$(id -un)}"
ENV_FILE=/etc/brewctl/hardware.env
SCALE_MAC_DEFAULT=60:8a:10:4d:5f:ac

HARD_FAILED=0
MISSING_PKGS=()

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '   \033[1;32mok\033[0m    %s\n' "$*"; }
soft() { printf '   \033[1;33mwarn\033[0m  %s\n' "$*"; }
hard() { printf '   \033[1;31mFAIL\033[0m  %s\n' "$*"; HARD_FAILED=$((HARD_FAILED + 1)); }
info() { printf '         %s\n' "$*"; }

# --------------------------------------------------------------- architecture
log "Architecture and Python"
arch=$(uname -m)
case "$arch" in
    aarch64|arm64)
        ok "$arch -- prebuilt wheels available" ;;
    armv7l|armv6l)
        # base.txt pins fastapi[standard], which pulls pydantic-core: a Rust
        # extension with no 32-bit ARM wheels. pip falls back to compiling Rust
        # on a 416 MB Pi Zero 2 W, which will not realistically finish.
        hard "$arch is 32-bit -- pydantic-core has no wheel and will try to build from source"
        info "reimage to 64-bit Raspberry Pi OS, or add piwheels as an extra pip index" ;;
    *)
        soft "$arch -- untested; wheel availability unknown" ;;
esac
[[ -r /etc/os-release ]] && info "$(. /etc/os-release; echo "$PRETTY_NAME")"

pyver=$(python3 -V 2>&1)
ok "$pyver"

# install.sh runs `python3 -m venv`, which needs ensurepip. Debian splits that
# into python3-venv and Pi OS Lite does not ship it.
if python3 -c 'import ensurepip' 2>/dev/null; then
    ok "ensurepip present (python3 -m venv will work)"
else
    hard "ensurepip missing -- 'python3 -m venv' fails"
    pymm=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
    MISSING_PKGS+=("python${pymm:-3}-venv")
fi

# --------------------------------------------------------------- system deps
log "System packages"
have_pkg() { dpkg -s "$1" >/dev/null 2>&1; }

# bluepy 1.3.0 compiles bluepy-helper, the binary the BLE connection actually
# runs on, against glib headers.
if have_pkg libglib2.0-dev; then
    ok "libglib2.0-dev (bluepy builds bluepy-helper against it)"
else
    hard "libglib2.0-dev missing -- bluepy will fail to build"
    MISSING_PKGS+=(libglib2.0-dev)
fi

if have_pkg python3-dev; then
    ok "python3-dev"
else
    soft "python3-dev missing -- some C extensions need it"
    MISSING_PKGS+=(python3-dev)
fi

command -v git >/dev/null && ok "git" || { hard "git missing"; MISSING_PKGS+=(git); }

# --------------------------------------------------------------------- I2C
log "I2C (MotorKit valve)"
i2c_devs=$(ls /dev/i2c-* 2>/dev/null)
if [[ -n "$i2c_devs" ]]; then
    ok "$(echo "$i2c_devs" | tr '\n' ' ')"
else
    hard "no /dev/i2c-* -- enable it with: sudo raspi-config nonint do_i2c 0 (then reboot)"
fi

groups_have=$(id -nG "$SERVICE_USER" 2>/dev/null)
info "groups for $SERVICE_USER: $groups_have"
for g in i2c gpio; do
    if getent group "$g" >/dev/null 2>&1; then
        if [[ " $groups_have " == *" $g "* ]]; then
            ok "$SERVICE_USER is in $g"
        else
            hard "$SERVICE_USER not in $g -- sudo usermod -aG $g $SERVICE_USER (then log out and back in)"
        fi
    fi
done

# ---------------------------------------------------------------- bluetooth
log "Bluetooth (Acaia scale)"
# The unit declares After=bluetooth.target but does not enable bluetooth itself.
bt_state=$(systemctl is-active bluetooth 2>/dev/null)
if [[ "$bt_state" == "active" ]]; then
    ok "bluetooth.service is active"
else
    hard "bluetooth.service is $bt_state -- sudo systemctl enable --now bluetooth"
fi

if command -v bluetoothctl >/dev/null; then
    # Whatever MAC the env file (or the shipped example) points at is what
    # create_scale() will try to connect to.
    mac="$SCALE_MAC_DEFAULT"
    if [[ -r "$ENV_FILE" ]]; then
        from_env=$(sudo -n grep -m1 '^BREWCTL_SCALE_MAC_ADDRESS=' "$ENV_FILE" 2>/dev/null | cut -d= -f2)
        [[ -n "$from_env" ]] && mac="$from_env"
    fi
    if bluetoothctl devices 2>/dev/null | grep -qi "$mac"; then
        ok "scale $mac is known to bluetoothctl"
    else
        soft "scale $mac not in 'bluetoothctl devices' -- power the scale on and run: bluetoothctl scan on"
    fi
else
    soft "bluetoothctl not found -- cannot confirm the scale MAC"
fi

# ---------------------------------------------------------------- resources
log "Resources"
root_avail_kb=$(df -Pk / | awk 'NR==2 {print $4}')
root_avail_mb=$((root_avail_kb / 1024))
if (( root_avail_mb > 1024 )); then
    ok "${root_avail_mb} MB free on /"
else
    soft "${root_avail_mb} MB free on / -- the venv and wheels want ~1 GB"
fi

mem_total=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
swap_total=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
info "RAM ${mem_total} MB, swap ${swap_total} MB"
(( swap_total < 100 )) && soft "little or no swap -- pip on a 416 MB box may be OOM-killed"

# ------------------------------------------------------------ existing state
log "Existing state"
for d in "$REPO_DIR" "$HOME/coldbrewer.git"; do
    if [[ -d "$d" ]]; then
        ok "$d exists"
    else
        info "$d does not exist yet"
    fi
done

if [[ -d "$HOME/coldbrewer.git" ]]; then
    # post-receive checks out HEAD, not the ref that was pushed, so HEAD decides
    # what actually deploys.
    head_ref=$(git -C "$HOME/coldbrewer.git" symbolic-ref HEAD 2>/dev/null)
    info "bare repo HEAD -> ${head_ref:-<unset>} (this is what post-receive checks out)"
    [[ -x "$HOME/coldbrewer.git/hooks/post-receive" ]] \
        && ok "post-receive hook installed and executable" \
        || info "post-receive hook not installed yet"
fi

# A surviving env file is how mock mode outlives a "clean" reinstall: install.sh
# deliberately never overwrites it.
if [[ -f "$ENV_FILE" ]]; then
    soft "$ENV_FILE already exists -- install.sh will NOT overwrite it"
    info "check it really has BREWCTL_IS_PROD=true: sudo grep IS_PROD $ENV_FILE"
else
    info "$ENV_FILE absent -- install.sh will install the example"
fi

log "Services"
for u in coldbrew-backend.service coldbrew-frontend.service brewctl-hardware.service; do
    state=$(systemctl is-active "$u" 2>/dev/null)
    case "$u:$state" in
        coldbrew-*:active) soft "$u is $state -- install.sh will disable it" ;;
        *)                 info "$u is $state" ;;
    esac
done

# The new unit binds 0.0.0.0:8000. The old backend may already hold it, which is
# fine -- install.sh stops it -- but anything else is a conflict.
port_holder=$(ss -lntp 2>/dev/null | awk '$4 ~ /:8000$/ {print; exit}')
if [[ -n "$port_holder" ]]; then
    soft "port 8000 in use: $port_holder"
else
    ok "port 8000 free"
fi

# ------------------------------------------------------------------ summary
log "Summary"
if (( ${#MISSING_PKGS[@]} )); then
    printf '   install missing packages:\n\n     sudo apt update && sudo apt install -y %s\n\n' "${MISSING_PKGS[*]}"
fi

if (( HARD_FAILED )); then
    printf '   \033[1;31m%d hard check(s) failed\033[0m -- fix these before running install.sh\n' "$HARD_FAILED"
    exit 1
fi
printf '   \033[1;32mready\033[0m -- run ./deploy/pi/install.sh\n'
