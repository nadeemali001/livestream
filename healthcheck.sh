#!/bin/sh
# Simple healthcheck script for the streamer container.
# Returns 0 if an ffmpeg process using the playlist is running, non-zero otherwise.

PIDFILE="/app/ffmpeg_stream.pid"
PLAYLIST="/app/playlist.txt"

is_running_pid() {
  if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [ -n "$PID" ]; then
      if kill -0 "$PID" 2>/dev/null; then
        # ensure it's an ffmpeg process
        cmd=$(ps -p "$PID" -o comm= 2>/dev/null || echo "")
        case "$cmd" in
          *ffmpeg*) return 0 ;;
          *) return 1 ;;
        esac
      fi
    fi
  fi
  return 1
}

# Fallback: detect any ffmpeg process that references the playlist file
is_running_grep() {
  if pgrep -f "ffmpeg" >/dev/null 2>&1; then
    # check command lines
    if ps aux | grep ffmpeg | grep "${PLAYLIST}" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

if is_running_pid; then
  exit 0
fi

if is_running_grep; then
  exit 0
fi

exit 1
