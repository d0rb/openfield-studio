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

# 2. a process that really is the service (its command line names it) is stopped.
# The name is given with `exec -a`, which sets argv[0] and so the command line is_ours() reads, rather than by
# copying a binary into the work directory and running it: mktemp -d lands under /tmp, which a CI runner may mount
# noexec, and there the copy could never start at all.
( exec -a "$WORKDIR/comfy-api-proxy" sleep 30 ) &
service=$!
echo "$service" >"$WORKDIR/proxy.pid"
# the job is forked before it is exec'd, so for a moment /proc/<pid>/cmdline still names bash: wait, do not race
for _ in $(seq 1 50); do is_ours "$service" "comfy-api-proxy" && break; sleep 0.1; done
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
