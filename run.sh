#!/usr/bin/env bash
set -euo pipefail

# Minimal run.sh - simple commands for local development
# Supported commands: start [--bg] [PORT], stop, status, logs, help

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT_DIR/.venv"
LOG="$ROOT_DIR/stream.log"
PIDFILE="$ROOT_DIR/streamlit.pid"
APP="$ROOT_DIR/app.py"
REQS="$ROOT_DIR/requirements.txt"

info(){ echo "[INFO] $*"; }
err(){ echo "[ERROR] $*" >&2; }

ensure_venv(){
  if [ ! -d "$VENV" ]; then
    info "Creating virtualenv at $VENV"
    python3 -m venv "$VENV"
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
    pip install --upgrade pip setuptools wheel || true
    if [ -f "$REQS" ]; then
      info "Installing requirements from $REQS"
      pip install -r "$REQS"
    fi
  else
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
  fi
}

start(){
  BG=false
  PORT=""
  # parse args: optional --bg and optional PORT
  for a in "$@"; do
    if [ "$a" = "--bg" ]; then
      BG=true
    else
      PORT="$a"
    fi
  done

  if [ ! -f "$APP" ]; then
    err "$APP not found"
    return 2
  fi

  ensure_venv

  if [ "$BG" = "true" ]; then
    if [ -z "$PORT" ]; then
      info "Starting Streamlit in background (Streamlit will choose port)"
      nohup streamlit run "$APP" --server.address 0.0.0.0 >> "$LOG" 2>&1 &
    else
      info "Starting Streamlit in background on port $PORT"
      nohup streamlit run "$APP" --server.port "$PORT" --server.address 0.0.0.0 >> "$LOG" 2>&1 &
    fi
    PID=$!
    echo "$PID" > "$PIDFILE"
    disown "$PID" || true
    info "Streamlit started (PID=$PID)"
  else
    if [ -z "$PORT" ]; then
      info "Starting Streamlit in foreground (Streamlit will choose port)"
      streamlit run "$APP" --server.address 0.0.0.0
    else
      info "Starting Streamlit in foreground on port $PORT"
      streamlit run "$APP" --server.port "$PORT" --server.address 0.0.0.0
    fi
  fi
}

stop(){
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [ -n "$PID" ]; then
      info "Stopping Streamlit (PID=$PID)"
      kill "$PID" || true
      sleep 1
      if kill -0 "$PID" >/dev/null 2>&1; then
        info "PID $PID still alive; sending SIGKILL"
        kill -9 "$PID" || true
      fi
      rm -f "$PIDFILE" || true
      return 0
    fi
  fi
  err "No pidfile found at $PIDFILE"
  return 2
}

status(){
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
    echo "PIDFILE: $PIDFILE -> $PID"
    if [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1; then
      ps -p "$PID" -o pid,cmd
      return 0
    else
      echo "Stale pidfile or process not running"
      return 1
    fi
  else
    echo "No pidfile ($PIDFILE). Streamlit may be running foreground or not started."
    ps aux | egrep "streamlit" | egrep -v "egrep|run.sh" || true
    return 1
  fi
}

logs(){
  if [ -f "$LOG" ]; then
    tail -n +1 -f "$LOG"
  else
    err "$LOG not found"
    return 2
  fi
}

case "${1:-}" in
  start)
    shift || true
    start "$@"
    ;;
  stop)
    stop
    ;;
  status)
    status
    ;;
  logs)
    logs
    ;;
  --help|-h|help|"")
    cat <<EOF
Usage: $0 <command>
Commands:
  start [--bg] [PORT]   Start Streamlit (optional background and optional port)
  stop                  Stop background Streamlit started with --bg
  status                Show pid / process for background Streamlit
  logs                  Tail the stream log
  help                  Show this message
EOF
    ;;
  *)
    err "Unknown command: ${1:-}"
    exit 2
    ;;
esac

