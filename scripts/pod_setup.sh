#!/usr/bin/env bash
# OpenField Studio: bring up ComfyUI + comfy-api-proxy on a rented GPU box (Ubuntu, CUDA, SSH).
#
#   export HF_TOKEN=hf_xxx            # read-only token; LTX 2.5 must be unlocked on your account
#   bash pod_setup.sh [up|down|status|logs]
#
# Copy this file, fetch_template_models.py and manifest.json to the box first (they live side by side).
# Nothing is exposed publicly: ComfyUI (:8188) and the proxy (:8189) bind to 127.0.0.1 and you
# reach them through an SSH tunnel (printed at the end). The token is only given to the downloader:
# ComfyUI and the proxy are started without it, and it is never written to disk or echoed.
set -euo pipefail

COMFY_VERSION="${COMFY_VERSION:-v0.41.0}"
WORKDIR="${WORKDIR:-/workspace}"
COMFY_DIR="${COMFY_DIR:-$WORKDIR/ComfyUI}"
VENV_DIR="${VENV_DIR:-$WORKDIR/venv}"
TORCH_INDEX="${TORCH_INDEX:-}"            # e.g. https://download.pytorch.org/whl/cu128 if torch is missing
COMFY_PORT="${COMFY_PORT:-8188}"
PROXY_PORT="${PROXY_PORT:-8189}"
# the tunnel's ends on your own computer (printed by tunnel_help); not used on the box itself
LOCAL_COMFY_PORT="${LOCAL_COMFY_PORT:-9188}"
LOCAL_PROXY_PORT="${LOCAL_PROXY_PORT:-9189}"
MAX_UPLOAD_MB="${MAX_UPLOAD_MB:-500}"
MIN_DISK_GB="${MIN_DISK_GB:-150}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$WORKDIR/logs"

say() { printf '\033[1m[openfield]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[openfield] warning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[31m[openfield] %s\033[0m\n' "$*" >&2; exit 1; }

# True when a pid is alive and its command line contains the text: a stale pid file (after the box was
# restarted) must never get an unrelated process killed.
is_ours() { # pid, text expected in its command line
  [ -n "${1:-}" ] && [ -r "/proc/$1/cmdline" ] && tr '\0' ' ' <"/proc/$1/cmdline" | grep -q -- "$2"
}

wait_http() { # url, timeout_seconds
  local url="$1" limit="$2" waited=0
  until curl -fsS -m 3 "$url" >/dev/null 2>&1; do
    sleep 2; waited=$((waited + 2))
    [ "$waited" -ge "$limit" ] && return 1
  done
}

preflight() {
  command -v nvidia-smi >/dev/null || die "nvidia-smi not found: this does not look like a GPU box."
  local vram_mb disk_gb
  vram_mb="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')"
  say "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1), ${vram_mb} MiB"
  [ "$vram_mb" -ge 24000 ] || die "need >= 24 GB VRAM (32 GB+ recommended for LTX 2.5)."
  [ "$vram_mb" -ge 31000 ] || warn "under 32 GB VRAM: LTX 2.5 may need offloading; expect slower or OOM runs."
  mkdir -p "$WORKDIR" "$LOG_DIR"
  disk_gb="$(df -BG --output=avail "$WORKDIR" | tail -1 | tr -dc '0-9')"
  say "free disk in $WORKDIR: ${disk_gb} GB"
  [ "$disk_gb" -ge "$MIN_DISK_GB" ] || warn "less than ${MIN_DISK_GB} GB free; the models are large (tens of GB) and ${MIN_DISK_GB} GB is a comfortable minimum."
  command -v git >/dev/null || die "git is required."
  command -v python3 >/dev/null || die "python3 is required."
  python3 - <<'PY' || die "Python 3.10+ is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

install_comfy() {
  if [ -d "$COMFY_DIR/.git" ]; then
    say "ComfyUI already present at $COMFY_DIR ($(git -C "$COMFY_DIR" describe --tags --always))"
  else
    say "cloning ComfyUI $COMFY_VERSION"
    git clone --depth 1 --branch "$COMFY_VERSION" https://github.com/Comfy-Org/ComfyUI.git "$COMFY_DIR"
  fi
}

install_python_env() {
  if [ ! -d "$VENV_DIR" ]; then
    say "creating venv (reusing the image's torch if it has one)"
    python3 -m venv --system-site-packages "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
  python -m pip install --quiet --upgrade pip
  if ! python -c "import torch" 2>/dev/null; then
    [ -n "$TORCH_INDEX" ] || die "torch is not installed. Re-run with TORCH_INDEX=https://download.pytorch.org/whl/cu128 (match your CUDA)."
    say "installing torch from $TORCH_INDEX"
    python -m pip install --quiet torch torchvision torchaudio --index-url "$TORCH_INDEX"
  fi
  python -c "import torch; print('[openfield] torch', torch.__version__, '| cuda', torch.version.cuda, '| available', torch.cuda.is_available())"
  python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" || die "torch cannot see the GPU."
  say "installing ComfyUI requirements, huggingface_hub, comfy-api-proxy"
  python -m pip install --quiet -r "$COMFY_DIR/requirements.txt"
  python -m pip install --quiet huggingface_hub hf_xet comfy-api-proxy
}

fetch_models() {
  local fetcher="$SCRIPT_DIR/fetch_template_models.py"
  [ -f "$fetcher" ] || die "fetch_template_models.py must sit next to this script."
  [ -f "$SCRIPT_DIR/manifest.json" ] || say "note: manifest.json is not next to this script, so the file list is read from GitHub and guessed (copy openfield/engine/manifest.json here for the exact list)."
  [ -n "${HF_TOKEN:-}" ] || warn "HF_TOKEN is not set: the gated LTX 2.5 files will be refused."
  say "downloading models (resumable; safe to re-run)"
  python "$fetcher" --comfy-dir "$COMFY_DIR"
}

start_services() {
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
  stop_services quiet
  say "starting ComfyUI on 127.0.0.1:$COMFY_PORT (previews on)"
  nohup env -u HF_TOKEN -u HUGGING_FACE_HUB_TOKEN \
    python "$COMFY_DIR/main.py" --listen 127.0.0.1 --port "$COMFY_PORT" --preview-method auto \
    >"$LOG_DIR/comfyui.log" 2>&1 &
  echo $! >"$WORKDIR/comfyui.pid"
  wait_http "http://127.0.0.1:$COMFY_PORT/system_stats" 300 \
    || die "ComfyUI did not come up; see $LOG_DIR/comfyui.log"
  say "starting comfy-api-proxy on 127.0.0.1:$PROXY_PORT (uploads up to ${MAX_UPLOAD_MB} MB)"
  nohup env -u HF_TOKEN -u HUGGING_FACE_HUB_TOKEN \
    comfy-api-proxy run --comfyui "http://127.0.0.1:$COMFY_PORT" --host 127.0.0.1 --port "$PROXY_PORT" \
    --comfyui-base-dir "$COMFY_DIR" --max-upload-mb "$MAX_UPLOAD_MB" --state-dir "$WORKDIR/proxy-state" \
    >"$LOG_DIR/proxy.log" 2>&1 &
  echo $! >"$WORKDIR/proxy.pid"
  wait_http "http://127.0.0.1:$PROXY_PORT/api/v2/health" 60 \
    || die "comfy-api-proxy did not come up; see $LOG_DIR/proxy.log"
}

stop_services() {
  local marker pid
  for name in proxy comfyui; do
    if [ -f "$WORKDIR/$name.pid" ]; then
      pid="$(cat "$WORKDIR/$name.pid")"
      marker="comfy-api-proxy"; [ "$name" = comfyui ] && marker="$COMFY_DIR/main.py"
      if is_ours "$pid" "$marker"; then
        kill "$pid" 2>/dev/null || true
        [ "${1:-}" = quiet ] || say "stopped $name"
      elif [ "${1:-}" != quiet ]; then
        say "$name: the saved pid $pid is not this service any more; leaving it alone"
      fi
      rm -f "$WORKDIR/$name.pid"
    fi
  done
}

status() {
  nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader || true
  df -h "$WORKDIR" | tail -1
  local marker
  for name in comfyui proxy; do
    marker="comfy-api-proxy"; [ "$name" = comfyui ] && marker="$COMFY_DIR/main.py"
    if [ -f "$WORKDIR/$name.pid" ] && is_ours "$(cat "$WORKDIR/$name.pid")" "$marker"; then
      say "$name running (pid $(cat "$WORKDIR/$name.pid"))"
    else
      say "$name not running"
    fi
  done
  curl -fsS -m 3 "http://127.0.0.1:$PROXY_PORT/api/v2/health" && echo || true
}

tunnel_help() {
  cat <<EOF

[openfield] Ready. On YOUR computer, open a tunnel (replace host and port with the box's SSH details):

    ssh -N -L ${LOCAL_COMFY_PORT}:127.0.0.1:${COMFY_PORT} -L ${LOCAL_PROXY_PORT}:127.0.0.1:${PROXY_PORT} -p <SSH_PORT> root@<BOX_IP>

then, in a second terminal on your computer:

    set COMFY_BASE_URL=http://127.0.0.1:${LOCAL_PROXY_PORT}            (PowerShell: \$env:COMFY_BASE_URL = "http://127.0.0.1:${LOCAL_PROXY_PORT}")
    ComfyUI itself (for template export / node checks): http://127.0.0.1:${LOCAL_COMFY_PORT}

The local ports differ from the box's on purpose: you may already run ComfyUI on 8188 locally, and
Windows reserves some port ranges (if ssh says it cannot bind, pick other local ports, for example
LOCAL_COMFY_PORT=19188 LOCAL_PROXY_PORT=19189 bash pod_setup.sh tunnel).
No credentials are needed through the loopback tunnel. Stop the box when you are done rendering.
EOF
}

# run the command only when executed, not when sourced (the tests source this file for its functions)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-up}" in
    up)     preflight; install_comfy; install_python_env; fetch_models; start_services; tunnel_help ;;
    down)   stop_services ;;
    status) status ;;
    tunnel) tunnel_help ;;
    logs)   tail -n 60 -f "$LOG_DIR/comfyui.log" "$LOG_DIR/proxy.log" ;;
    *)      die "usage: $0 [up|down|status|tunnel|logs]" ;;
  esac
fi
