#!/usr/bin/env bash
# voice_native.sh - start/stop the native voice STT (mlx-whisper on the Mac GPU), detached.
#
# What it does:
#   start: syncs services/voice-native, then launches uvicorn on 127.0.0.1:$VOICE_PORT (default 8093) in the
#          background. PID and log go to work/voice-native/. The model warms at start (first run may download it
#          into work/models/hf). stop: kills that PID.
# When to use it:
#   Via `make voice-native` / `make voice-native-stop`. Do not install it as a service from here (see RUNBOOK).
# Inputs:
#   .env (FL_VOICE_TOKEN, FL_WHISPER_PATH; read with grep, never sourced), env VOICE_PORT. macOS only.
# Outputs / side effects:
#   work/voice-native/{pid,voice-native.log}. The log carries timings only, never audio or transcripts.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${VOICE_PORT:-8093}"
RUN="$ROOT/work/voice-native"

envv() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

case "${1:-start}" in
  start)
    [ "$(uname -s)" = Darwin ] || { echo "voice-native needs macOS (Apple silicon); on Linux the 'voice' container is the engine" >&2; exit 1; }
    mkdir -p "$RUN" "$ROOT/work/models/hf"
    if [ -f "$RUN/pid" ] && kill -0 "$(cat "$RUN/pid")" 2>/dev/null; then
      echo "voice-native already running (pid $(cat "$RUN/pid"))"
      exit 0
    fi
    (cd services/voice-native && uv sync -q)
    token="$(envv FL_VOICE_TOKEN)"
    path="$(envv FL_WHISPER_PATH)"
    (
      cd services/voice-native
      HF_HOME="$ROOT/work/models/hf" FL_WHISPER_PATH="$path" FL_VOICE_TOKEN="$token" \
        exec nohup uv run uvicorn falcon_voice_native:app --host 127.0.0.1 --port "$PORT" --log-level warning
    ) >"$RUN/voice-native.log" 2>&1 </dev/null &
    echo $! >"$RUN/pid"
    echo "voice-native starting on 127.0.0.1:$PORT (warm-up 10-60 s; first run may download the model). Check: make voice-native-status"
    ;;
  stop)
    if [ -f "$RUN/pid" ]; then
      pid="$(cat "$RUN/pid")"
      # uv run spawns the server as a child: stop the group's children too
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
      rm -f "$RUN/pid"
      echo "voice-native stopped"
    else
      echo "voice-native not started by this script"
    fi
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
