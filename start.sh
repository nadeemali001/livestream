#!/usr/bin/env bash
set -euo pipefail

# start.sh - convenience script to setup and run the YouTube loop streamer
# Usage: ./start.sh [command]
# Commands:
#   setup        Create folders and default files used by the app
#   dev          Run the app locally (requires python3 & ffmpeg installed)
#   docker-up    Build and run container via docker-compose
#   docker-down  Stop container via docker-compose
#   status       Show docker-compose service status (or running processes)
#   logs         Tail the `stream.log` (if present)
#   start        Prefer docker-up if Docker is available, otherwise dev
#   help         Show this message

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VIDEOS_DIR="$ROOT_DIR/videos"
LOG_FILE="$ROOT_DIR/stream.log"
PLAYLIST="$ROOT_DIR/playlist.txt"

info() { echo "[INFO] $*"; }
err() { echo "[ERROR] $*" >&2; }


run_command() {
  cmd="$1"
  case "$cmd" in
    setup)
      info "Creating folders and touch files..."
      mkdir -p "$VIDEOS_DIR"
      touch "$LOG_FILE" "$PLAYLIST"
      if [ -f "$ROOT_DIR/healthcheck.sh" ]; then
        chmod +x "$ROOT_DIR/healthcheck.sh" || true
      fi
      info "Created $VIDEOS_DIR and placeholder files. Add your videos to $VIDEOS_DIR."
      ;;

    dev)
      info "Running app in development mode"
      if ! command -v python3 >/dev/null 2>&1; then
        err "python3 is required for dev mode"
        return 2
      fi
      if ! command -v ffmpeg >/dev/null 2>&1; then
        err "ffmpeg is required on the host for dev mode"
        return 2
      fi
      if [ ! -d "$VIDEOS_DIR" ]; then
        err "Videos folder not found. Run './start.sh setup' first."
        return 2
      fi
      # Install venv if needed
      if [ ! -d "$ROOT_DIR/.venv" ]; then
        info "Creating virtualenv and installing requirements (this may take a moment)"
        python3 -m venv "$ROOT_DIR/.venv"
        # shellcheck disable=SC1090
        source "$ROOT_DIR/.venv/bin/activate"
        pip install --upgrade pip
        if [ -f "$ROOT_DIR/requirements.txt" ]; then
          pip install -r "$ROOT_DIR/requirements.txt"
        fi
      else
        # Activate
        # shellcheck disable=SC1090
        source "$ROOT_DIR/.venv/bin/activate"
      fi
      info "Starting Streamlit (press Ctrl-C to stop)"
      streamlit run "$ROOT_DIR/app.py" --server.port 8501 --server.address 0.0.0.0
      ;;

    docker-up)
      info "Bringing up container via docker-compose"
      if command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$ROOT_DIR/docker-compose.yml" up -d --build
      elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        docker compose -f "$ROOT_DIR/docker-compose.yml" up -d --build
      else
        err "docker-compose or 'docker compose' is required to run in docker mode"
        return 2
      fi
      ;;

    docker-down)
      info "Stopping container via docker-compose"
      if command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$ROOT_DIR/docker-compose.yml" down
      elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        docker compose -f "$ROOT_DIR/docker-compose.yml" down
      else
        err "docker-compose or 'docker compose' is required to run in docker mode"
        return 2
      fi
      ;;

    status)
      if command -v docker >/dev/null 2>&1; then
        if command -v docker-compose >/dev/null 2>&1; then
          docker-compose -f "$ROOT_DIR/docker-compose.yml" ps || true
        else
          docker compose -f "$ROOT_DIR/docker-compose.yml" ps || true
        fi
      else
        ps aux | egrep "ffmpeg|streamlit" | egrep -v "egrep|start.sh" || true
      fi
      ;;

    logs)
      if [ -f "$LOG_FILE" ]; then
        tail -n +1 -f "$LOG_FILE"
      else
        err "$LOG_FILE not found"
        return 2
      fi
      ;;

    start)
      # Prefer docker if available
      if command -v docker >/dev/null 2>&1; then
        "$0" docker-up
      else
        "$0" dev
      fi
      ;;

    stop)
      # stop docker if present, otherwise attempt to kill ffmpeg pidfile
      if command -v docker >/dev/null 2>&1; then
        "$0" docker-down
        return 0
      fi
      if [ -f "$ROOT_DIR/ffmpeg_stream.pid" ]; then
        PID=$(cat "$ROOT_DIR/ffmpeg_stream.pid" 2>/dev/null || echo "")
        if [ -n "$PID" ]; then
          info "Stopping ffmpeg (pid=$PID)"
          kill "$PID" || true
          sleep 1
        fi
      fi
      ;;

    help|--help|-h)
      cat <<EOF
Usage: $0 [command]

Commands:
  setup        Create folders and placeholder files
  dev          Run locally (creates .venv and installs requirements)
  docker-up    Build and run with docker-compose
  docker-down  Stop docker-compose service
  status       Show status (docker-compose ps or process listing)
  logs         Tail stream.log
  start        Prefer docker-up if Docker present, otherwise dev
  stop         Stop docker or kill ffmpeg pidfile
  help         Show this message
EOF
      ;;

    *)
      err "Unknown command: $cmd"
      return 2
      ;;
  esac
}

# If no arguments provided, run an interactive menu
if [ "$#" -eq 0 ] && [ -t 0 ]; then
  while true; do
    echo
    echo "========== YouTube Loop Streamer - Menu =========="
    echo "1) setup        - Create folders and placeholder files"
    echo "2) dev          - Run locally (creates .venv and installs requirements)"
    echo "3) docker-up    - Build and run with docker-compose"
    echo "4) docker-down  - Stop docker-compose service"
    echo "5) status       - Show status (docker-compose ps or process listing)"
    echo "6) logs         - Tail stream.log"
    echo "7) start        - Prefer docker-up if Docker present, otherwise dev"
    echo "8) stop         - Stop docker or kill ffmpeg pidfile"
    echo "9) help         - Show help"
    echo "0) quit"
    echo
    read -rp "Select an option [0-9]: " choice
    case "$choice" in
      1) run_command setup ;;
      2) run_command dev ;;
      3) run_command docker-up ;;
      4) run_command docker-down ;;
      5) run_command status ;;
      6) run_command logs ;;
      7) run_command start ;;
      8) run_command stop ;;
      9) run_command help ;;
      0) echo "Goodbye."; exit 0 ;;
      *) echo "Invalid selection" ;;
    esac
  done
elif [ "$#" -eq 0 ]; then
  # Non-interactive with no args: show help
  run_command help
  exit 0
else
  # Single command provided as arg
  run_command "$1"
fi

exit 0
