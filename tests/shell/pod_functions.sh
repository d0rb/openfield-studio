#!/usr/bin/env bash
# Exercises the process-handling functions of scripts/pod_setup.sh on Linux: a stale pid file must never
# get an unrelated process killed, and a real service's pid file must stop it.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WORKDIR="$(mktemp -d)"
export COMFY_DIR="$WORKDIR/ComfyUI"
mkdir -p "$COMFY_DIR" "$WORKDIR/logs"
# shellcheck disable=SC1091
. "$HERE/../../scripts/pod_setup.sh"
set +e +o pipefail

fail() { echo "FAIL: $*"; exit 1; }
alive() { kill -0 "$1" 2>/dev/null; }

# 1. an unrelated process whose pid is in a stale pid file is left alone
sleep 30 &
innocent=$!
echo "$innocent" >"$WORKDIR/comfyui.pid"
echo "$innocent" >"$WORKDIR/proxy.pid"
stop_services quiet
alive "$innocent" || fail "an unrelated process was killed through a stale pid file"
[ ! -e "$WORKDIR/comfyui.pid" ] && [ ! -e "$WORKDIR/proxy.pid" ] || fail "stale pid files were not removed"

# 2. a process that really is the service (its command line names it) is stopped
cp "$(command -v sleep)" "$WORKDIR/comfy-api-proxy"
"$WORKDIR/comfy-api-proxy" 30 &
service=$!
echo "$service" >"$WORKDIR/proxy.pid"
is_ours "$service" "comfy-api-proxy" || fail "is_ours does not recognise a running service"
status >/dev/null 2>&1
stop_services quiet
sleep 0.3
alive "$service" && fail "the real service was not stopped"

# 3. is_ours is false for dead pids, empty input and the wrong name
is_ours "" "x" && fail "empty pid accepted"
is_ours 999999 "sleep" && fail "dead pid accepted"
is_ours "$innocent" "comfy-api-proxy" && fail "wrong command accepted"

kill "$innocent" 2>/dev/null
rm -rf "$WORKDIR"
echo "pod_setup.sh process handling: OK"
