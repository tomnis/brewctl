#!/usr/bin/env bash
#
# Install / update the BrewCTL hardware service on the Raspberry Pi.
#
# Idempotent: safe to re-run. Called by hand for the initial setup, and by the
# post-receive git hook on every deploy.
#
#   ./deploy/device/install.sh              # install or update
#   ./deploy/device/install.sh --deps-only  # just refresh the venv (used by the hook)
#
# Existing config at /etc/brewctl/hardware.env is never overwritten.

set -euo pipefail

REPO_DIR="${BREWCTL_REPO_DIR:-$HOME/coldbrewer}"
VENV_DIR="${BREWCTL_VENV_DIR:-$REPO_DIR/backend/.venv}"
SRC_DIR="$REPO_DIR/backend/src"
SERVICE_USER="${BREWCTL_USER:-$(id -un)}"

ENV_DIR=/etc/brewctl
ENV_FILE="$ENV_DIR/hardware.env"
UNIT_NAME=brewctl-hardware.service
UNIT_PATH="/etc/systemd/system/$UNIT_NAME"
SUDOERS_PATH=/etc/sudoers.d/brewctl

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEPS_ONLY=0
[[ "${1:-}" == "--deps-only" ]] && DEPS_ONLY=1

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }

[[ -d "$SRC_DIR" ]] || { warn "no source tree at $SRC_DIR"; exit 1; }

# ---------------------------------------------------------------- python deps
log "Refreshing venv at $VENV_DIR"
[[ -d "$VENV_DIR" ]] || python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/backend/requirements/hardware.txt"

# Fail here rather than at 6am with a valve that will not move: these two are
# imported lazily behind BREWCTL_IS_PROD, so a broken install stays invisible
# until the service tries to talk to real hardware.
log "Verifying device libraries import"
"$VENV_DIR/bin/python" - <<'PY'
from pyacaia import AcaiaScale  # noqa: F401
from adafruit_motorkit import MotorKit  # noqa: F401
from adafruit_motor import stepper  # noqa: F401
print("    device libraries OK")
PY

if [[ "$DEPS_ONLY" == 1 ]]; then
    log "Restarting $UNIT_NAME"
    sudo -n systemctl restart "$UNIT_NAME"
    exit 0
fi

# ------------------------------------------------------------------- env file
if [[ ! -f "$ENV_FILE" ]]; then
    log "Installing $ENV_FILE (edit it: the scale MAC and BREWCTL_IS_PROD matter)"
    sudo install -d -m 0755 "$ENV_DIR"
    sudo install -m 0600 -o root -g root "$HERE/hardware.env.example" "$ENV_FILE"
else
    log "Keeping existing $ENV_FILE"
fi

# ----------------------------------------------------------------- unit file
log "Installing $UNIT_PATH"
sed -e "s|__USER__|$SERVICE_USER|g" \
    -e "s|__VENV__|$VENV_DIR|g" \
    -e "s|__SRC__|$SRC_DIR|g" \
    "$HERE/$UNIT_NAME" | sudo tee "$UNIT_PATH" >/dev/null

# Lets the post-receive hook restart the service without a password prompt.
# Narrowly scoped to this one unit.
log "Installing $SUDOERS_PATH"
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl restart %s, /usr/bin/systemctl stop %s, /usr/bin/systemctl start %s\n' \
    "$SERVICE_USER" "$UNIT_NAME" "$UNIT_NAME" "$UNIT_NAME" \
    | sudo tee "$SUDOERS_PATH" >/dev/null
sudo chmod 0440 "$SUDOERS_PATH"
sudo visudo -c -f "$SUDOERS_PATH"

# --------------------------------------------------- retire the old services
# The frontend now runs on the control host, and the old backend unit ran the pre-split
# monolith out of ~/start_backend.sh. Both are left on disk for rollback.
for old in coldbrew-frontend.service coldbrew-backend.service; do
    if systemctl list-unit-files --no-legend "$old" 2>/dev/null | grep -q .; then
        log "Disabling $old"
        sudo systemctl disable --now "$old" || true
    fi
done

sudo systemctl daemon-reload
sudo systemctl enable "$UNIT_NAME"
sudo systemctl restart "$UNIT_NAME"

log "Done. Verify it is driving real hardware, not mocks:"
echo "    journalctl -u $UNIT_NAME -n 50 | grep -iE 'production|mock'"
echo "    curl -s localhost:8000/health | jq"
