#!/usr/bin/env bash
#
# Apply deploy/nas/app.yaml to the TrueNAS custom app.
#
#   ./deploy/nas/apply.sh deploy/nas/app.yaml [--force] [--render] [--image REF]
#
#   --force        deploy even during an active brew, or when brew state is unknown
#   --render       print the rendered manifest and exit; no network calls
#   --image REF    use REF instead of image.tag. For an emergency rollback to an
#                  image already on the box -- leaves the running app diverged
#                  from git, so follow it with a real commit.
#
# The manifest carries an @IMAGE@ placeholder; the deployed reference lives in
# image.tag beside it (override with --image-tag-file). Splitting them is what
# makes a promotion a one-line diff in a file that contains nothing else, and lets
# the deploy workflow trigger on exactly that file.
#
# env:
#   TRUENAS_URL       https://192.168.0.69
#   TRUENAS_API_KEY   API key with APPS_WRITE
#   TRUENAS_APP       app name (default brewctl-api)
#   BREWCTL_API_URL   where the running api is reachable, for the brew preflight
#                     (default http://192.168.0.69:8000)
#
# The deploy logic lives here rather than in workflow YAML on purpose: applying is
# one idempotent PUT of one file, so whether it is invoked by CI (push) or by a
# systemd timer on the NAS (pull) is a ~10 line decision, not an architecture.
#
# WARNING: this replaces the app's ENTIRE config. Anything set through the TrueNAS
# UI that app.yaml does not represent is wiped. Before the first run, diff:
#   curl -sk "$TRUENAS_URL/api/v2.0/app/id/$TRUENAS_APP" -H "Authorization: Bearer $KEY" \
#     | jq -r .custom_compose_config_string
#
# The app must already exist -- PUT is update, not create. Create it once via the
# Custom App UI.

set -euo pipefail

MANIFEST=""
FORCE=0
RENDER_ONLY=0
IMAGE_REF=""
IMAGE_TAG_FILE=""

while (( $# )); do
    case "$1" in
        --force)          FORCE=1 ;;
        --render)         RENDER_ONLY=1 ;;
        --image)          IMAGE_REF="${2:-}"; shift ;;
        --image-tag-file) IMAGE_TAG_FILE="${2:-}"; shift ;;
        -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
        -*)               printf 'unknown option: %s\n' "$1" >&2; exit 1 ;;
        *)                MANIFEST="$1" ;;
    esac
    shift
done

TRUENAS_APP="${TRUENAS_APP:-brewctl-api}"
BREWCTL_API_URL="${BREWCTL_API_URL:-http://192.168.0.69:8000}"
DEPLOY_TIMEOUT_SECONDS="${DEPLOY_TIMEOUT_SECONDS:-180}"

# The TrueNAS cert is the self-signed iXsystems one, so verification cannot
# succeed. Deliberate and scoped to this host, not a blanket habit.
CURL=(curl -sk --max-time 30)

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
# Progress goes to stderr, not stdout: `--render` writes the manifest to stdout
# and it must be pipeable into a YAML parser without ANSI noise in front of it.
log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }

[[ -n "$MANIFEST" ]] || die "usage: apply.sh <path-to-app.yaml> [--force] [--render] [--image REF]"
[[ -f "$MANIFEST" ]] || die "no such manifest: $MANIFEST"

# ------------------------------------------------------------------ render ---
# The manifest is the shape of the deployment; image.tag is the deploy. Rendering
# happens here rather than in the workflow so that `--render` reproduces exactly
# what CI would PUT, and so a local `make deploy-nas` and CI cannot diverge.

# Strip comments and blank lines; the first surviving line is the reference.
read_image_tag() {
    local file="$1"
    [[ -f "$file" ]] || die "no image tag file: $file (expected beside the manifest)"
    local ref
    ref=$(sed -e 's/#.*//' -e 's/[[:space:]]*$//' "$file" | grep -m1 -v '^[[:space:]]*$') \
        || die "$file contains no image reference (only comments?)"
    printf '%s' "$ref"
}

if [[ -n "$IMAGE_REF" ]]; then
    # Loud: the box now runs something git does not record, which is the exact
    # property the whole split-manifest design exists to protect.
    printf '\033[1;33mwarning:\033[0m --image overrides %s; the deployed state will not match git\n' \
        "${IMAGE_TAG_FILE:-$(dirname "$MANIFEST")/image.tag}" >&2
else
    IMAGE_REF=$(read_image_tag "${IMAGE_TAG_FILE:-$(dirname "$MANIFEST")/image.tag}")
fi

# `|` as the delimiter: image references contain `/`.
RENDERED=$(sed "s|@IMAGE@|${IMAGE_REF}|g" "$MANIFEST")

# An unrendered placeholder would be PUT verbatim and leave the app CRASHED with
# nothing pointing at the cause. Refuse instead.
if printf '%s' "$RENDERED" | grep -q '@IMAGE@'; then
    die "@IMAGE@ survived rendering -- substitution failed"
fi
# REPLACE_ME is the placeholder shipped in image.tag; it is never a real image.
if [[ "$IMAGE_REF" == *REPLACE_ME* ]]; then
    die "image reference is still the placeholder ($IMAGE_REF) -- set a real tag in image.tag"
fi

log "Image: $IMAGE_REF"

if [[ "$RENDER_ONLY" == 1 ]]; then
    printf '%s\n' "$RENDERED"
    exit 0
fi

[[ -n "${TRUENAS_URL:-}" ]] || die "TRUENAS_URL is not set"
[[ -n "${TRUENAS_API_KEY:-}" ]] || die "TRUENAS_API_KEY is not set"
command -v jq >/dev/null || die "jq is required"

AUTH=(-H "Authorization: Bearer $TRUENAS_API_KEY")
JSON=(-H "Content-Type: application/json")
APP_URL="$TRUENAS_URL/api/v2.0/app/id/$TRUENAS_APP"

# --------------------------------------------------------------- preflight ---
# Refuse to deploy during a brew. A redeploy restarts the api, and brew state is
# in-process only (cur_brew), so the brew is destroyed: the heartbeat stops, the
# hardware watchdog closes the valve, and a ~6 hour batch is lost.
#
# Fail OPEN when the api is unreachable. Failing closed would mean a crashlooping
# api blocks the deploy that fixes it.
log "Checking for an active brew at $BREWCTL_API_URL"
# Generous timeout: /api/brew/status takes seconds, occasionally tens of seconds,
# when InfluxDB is slow or unreachable.
brew_json=$(curl -s --max-time 30 "$BREWCTL_API_URL/api/brew/status" 2>/dev/null) || curl_rc=$?
curl_rc=${curl_rc:-0}

# A timeout is NOT the same as "nothing is there". A slow api is a *running* api,
# quite possibly mid-brew, so treating a timeout as unreachable would fail open
# and destroy the brew. Only a refused connection (7) or an unresolvable host (6)
# means there is genuinely nothing to protect.
if [[ "$curl_rc" != 0 && "$curl_rc" != 6 && "$curl_rc" != 7 ]]; then
    if [[ "$FORCE" == 1 ]]; then
        log "Brew status check failed (curl $curl_rc) -- proceeding anyway (--force)"
    else
        die "could not determine brew state (curl exit $curl_rc, likely a timeout). The api may be mid-brew. Retry, or pass --force."
    fi
elif [[ "$curl_rc" == 0 && -n "$brew_json" ]]; then
    # Gate on the state, not on a brew merely existing: cur_brew survives
    # COMPLETED, so "is there a brew" would block deploys forever after the first
    # finished brew.
    state=$(printf '%s' "$brew_json" | jq -r '.brew_state // "unknown"')
    case "$state" in
        # ERROR counts as active: brew_step_task loops while status is BREWING or
        # ERROR and keeps driving the valve, so an errored brew is still holding
        # hardware and is still recoverable.
        brewing|paused|error)
            if [[ "$FORCE" == 1 ]]; then
                log "Brew is $state -- proceeding anyway (--force). This will destroy it."
            else
                die "a brew is $state and still holds the valve; deploying would destroy it. Wait, or pass --force."
            fi
            ;;
        *)
            log "No active brew (state: $state)"
            ;;
    esac
else
    log "API unreachable -- proceeding (cannot deploy a fix otherwise)"
fi
# Note: TOCTOU is accepted. A brew can start between here and the PUT below.

# ------------------------------------------------------------------- apply ---
if ! current=$("${CURL[@]}" "${AUTH[@]}" "$APP_URL"); then
    die "could not reach the TrueNAS API at $TRUENAS_URL"
fi
if ! printf '%s' "$current" | jq -e '.name?' >/dev/null 2>&1; then
    die "app '$TRUENAS_APP' not found. PUT cannot create it -- make it once in the Custom App UI. Response: $current"
fi

log "Applying $MANIFEST to $TRUENAS_APP"
payload=$(printf '%s\n' "$RENDERED" | jq -Rs '{custom_compose_config_string: .}')
response=$("${CURL[@]}" -X PUT "$APP_URL" "${AUTH[@]}" "${JSON[@]}" -d "$payload") \
    || die "PUT failed: $response"

# app.update runs as a middleware job. Depending on the gateway this returns
# either the app object or a bare job id -- and a FAILED job can still come back
# as HTTP 200, so the status code alone must never be treated as success. If we
# got a job id, watch the job; otherwise fall through to polling app state.
if job_id=$(printf '%s' "$response" | jq -er 'select(type=="number")' 2>/dev/null); then
    log "Tracking job $job_id"
    deadline=$((SECONDS + DEPLOY_TIMEOUT_SECONDS))
    while (( SECONDS < deadline )); do
        job=$("${CURL[@]}" "${AUTH[@]}" "$TRUENAS_URL/api/v2.0/core/get_jobs?id=$job_id")
        jstate=$(printf '%s' "$job" | jq -r '.[0].state // "UNKNOWN"')
        case "$jstate" in
            SUCCESS) log "Job succeeded"; break ;;
            FAILED|ABORTED)
                die "deploy job $jstate: $(printf '%s' "$job" | jq -r '.[0].error // "no error given"')" ;;
            *) sleep 3 ;;
        esac
    done
fi

# ------------------------------------------------------------------ verify ---
# The app object exposes only `state` (CRASHED|DEPLOYING|RUNNING|STOPPED|
# STOPPING) -- there is no container health field -- so wait for it to settle and
# then ask the api itself.
log "Waiting for the app to leave DEPLOYING"
deadline=$((SECONDS + DEPLOY_TIMEOUT_SECONDS))
state=UNKNOWN
while (( SECONDS < deadline )); do
    state=$("${CURL[@]}" "${AUTH[@]}" "$APP_URL" | jq -r '.state // "UNKNOWN"')
    [[ "$state" != "DEPLOYING" ]] && break
    sleep 3
done
[[ "$state" == "RUNNING" ]] || die "app is $state after deploy"

log "Waiting for the api to report healthy"
deadline=$((SECONDS + DEPLOY_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
    if health=$(curl -s --max-time 10 "$BREWCTL_API_URL/api/health" 2>/dev/null); then
        status=$(printf '%s' "$health" | jq -r '.status // "unknown"')
        if [[ "$status" == "healthy" || "$status" == "degraded" ]]; then
            log "api reports $status"
            # Surfaced rather than fatal: the Pi is deployed by hand and may
            # simply not have been pushed yet. Brews will be refused until it is.
            if [[ "$(printf '%s' "$health" | jq -r '.hardware.compatible // "unknown"')" != "true" ]]; then
                printf '\033[1;33mwarning:\033[0m hardware contract mismatch -- run `make deploy-pi`\n' >&2
            fi
            exit 0
        fi
    fi
    sleep 3
done

die "api did not become healthy within ${DEPLOY_TIMEOUT_SECONDS}s"
