"""
app.py

Streamlit app to control FFmpeg streaming to YouTube Live using a local
playlist (concat demuxer). The app scans `videos/`, shows detected files,
allows shuffle, and starts/stops an FFmpeg process safely.

Notes:
- FFmpeg does the actual streaming; this app only starts/stops the process.
- Supply YouTube stream key via the UI or environment variable `STREAM_KEY`.

"""
import os
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import shutil

import streamlit as st

from playlist_manager import scan_and_write_playlist, scan_videos


# Configuration
BASE_DIR = Path(__file__).parent.resolve()
# Allow overriding via environment variables for flexibility in different setups
# Default to a `videos/` folder next to the app when no env vars are provided.
VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", str(BASE_DIR / "videos")))
PLAYLIST_PATH = Path(os.environ.get("PLAYLIST_PATH", str(BASE_DIR / "playlist.txt")))
# Encoding defaults (can be tuned via env vars)
# VIDEO_BITRATE example: "4500k" or "23500k"
VIDEO_BITRATE = os.environ.get("VIDEO_BITRATE", "4500k")
AUDIO_BITRATE = os.environ.get("AUDIO_BITRATE", "160k")
FRAMERATE = os.environ.get("FRAMERATE", "30")
# RESOLUTION example: "1920x1080" or "3840x2160". If empty, no scaling is applied.
RESOLUTION = os.environ.get("RESOLUTION", "1920x1080")
# Buffer size controls variability; default kept at 2x video bitrate if not provided.
BUF_SIZE = os.environ.get("BUF_SIZE", "9000k")
LOG_PATH = BASE_DIR / "stream.log"
PID_PATH = BASE_DIR / "ffmpeg_stream.pid"

# Ensure videos dir exists
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Helper to ensure a path is a regular file. If a directory exists at the
# location, move it aside (backup) and create an empty file. This prevents
# IsADirectoryError when opening logs or other files.
def _ensure_file(path: Path):
    """Ensure `path` is a regular file. If a directory exists at `path`, move
    it to a backup name and return the backup path. Returns list of backups (may be empty).
    """
    backups = []
    if path.exists():
        if path.is_dir():
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup = path.with_name(path.name + f'.bak-{ts}')
            try:
                shutil.move(str(path), str(backup))
                backups.append(str(backup))
            except Exception:
                # try remove if empty
                try:
                    path.rmdir()
                except Exception:
                    raise
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
    return backups


# Ensure log and playlist files exist and are regular files
_backups_log = _ensure_file(LOG_PATH)
_backups_playlist = _ensure_file(PLAYLIST_PATH)


def log_event(message: str) -> None:
    ts = datetime.utcnow().isoformat() + "Z"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")

# After log_event is available, record any backups created during startup
try:
    for b in _backups_log + _backups_playlist:
        if b:
            log_event(f"Startup: moved unexpected directory to backup {b}")
except Exception:
    # If logging fails, nothing more we can do here
    pass


class StreamController:
    """Controls the FFmpeg process (start/stop) and ensures a single
    process can run at a time via pidfile checks and in-process handle.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        # Whether the controller should keep the stream running (used by watchdog)
        self._should_run = False
        self._monitor_thread: Optional[threading.Thread] = None

    def _pidfile_exists_and_alive(self) -> Optional[int]:
        if PID_PATH.exists():
            try:
                pid = int(PID_PATH.read_text().strip())
            except Exception:
                return None
            try:
                os.kill(pid, 0)
                return pid
            except OSError:
                return None
        return None

    def is_running(self) -> bool:
        # Check in-process handle first
        if self._proc and self._proc.poll() is None:
            return True
        # Otherwise check pidfile
        return self._pidfile_exists_and_alive() is not None

    def _build_ffmpeg_cmd(self, stream_key: str) -> List[str]:
        """Construct a robust FFmpeg command tuned for stable 1080p streaming."""
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        # x264 params: enforce constant keyint/gop and disable scenecut for stable GOPs
        x264_params = "keyint=60:min-keyint=60:no-scenecut=1"
        cmd = [
            "ffmpeg",
            "-re",
            "-f",
            "concat",
            "-safe",
            "0",
            "-stream_loop",
            "-1",
            "-i",
            str(PLAYLIST_PATH),
            # input handling
            "-fflags",
            "+genpts",
            # video encoding
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-level:v",
            "4.2",
            "-x264-params",
            x264_params,
            "-threads",
            "0",
            "-b:v",
            VIDEO_BITRATE,
            "-maxrate",
            VIDEO_BITRATE,
            "-bufsize",
            BUF_SIZE,
            "-r",
            FRAMERATE,
            "-pix_fmt",
            "yuv420p",
            "-g",
            "60",
        ]

        # Optionally scale to target resolution (don't upscale by default unless requested)
        if RESOLUTION:
            # Add a video filter to scale; use -s if you prefer a direct size flag
            cmd.extend(["-vf", f"scale={RESOLUTION}"])

        # continue building command with audio and output
        cmd.extend([
            # audio encoding
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            "44100",
            # output format
            "-fflags",
            "+nobuffer",
            "-f",
            "flv",
            rtmp_url,
        ])
        return cmd


    def _launch_ffmpeg(self, cmd: List[str]) -> Optional[subprocess.Popen]:
        """Start ffmpeg process and persist pidfile/logging. Returns Popen or None."""
        lf = open(LOG_PATH, "a", encoding="utf-8")
        try:
            lf.write(f"[{datetime.utcnow().isoformat()}Z] Launching FFmpeg: {shlex.join(cmd)}\n")
            lf.flush()
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL)
        except Exception as e:
            lf.write(f"[{datetime.utcnow().isoformat()}Z] Failed to start ffmpeg: {e}\n")
            lf.close()
            log_event(f"FFmpeg failed to start: {e}")
            return None

        # Persist pid to pidfile
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pf:
                pf.write(str(proc.pid))
        except Exception:
            pass

        self._proc = proc
        log_event(f"Started streaming (pid={proc.pid})")
        return proc


    def start(self, stream_key: str, shuffle: bool = False, autorestart: bool = True) -> bool:
        """Start FFmpeg streaming. Returns True on successful start.

        This will regenerate the playlist before launching FFmpeg.
        """
        with self._lock:
            if self.is_running():
                return False

            files = scan_and_write_playlist(str(VIDEOS_DIR), str(PLAYLIST_PATH), shuffle=shuffle)
            if not files:
                log_event("Start requested but no videos found; aborting start")
                return False

            # mark desired state
            self._should_run = True

            cmd = self._build_ffmpeg_cmd(stream_key=stream_key)
            proc = self._launch_ffmpeg(cmd)
            if not proc:
                return False

            # Start monitor thread to auto-restart if process dies (for 24x7 reliability)
            if autorestart and (self._monitor_thread is None or not self._monitor_thread.is_alive()):
                def monitor():
                    backoff = 1
                    while self._should_run:
                        # wait for process to exit
                        if self._proc is None:
                            time.sleep(1)
                            continue
                        ret = self._proc.wait()
                        log_event(f"FFmpeg exited (code={ret})")
                        # remove pidfile
                        try:
                            PID_PATH.unlink()
                        except Exception:
                            pass

                        if not self._should_run:
                            break

                        # attempt restart with backoff
                        sleep_time = min(backoff, 60)
                        log_event(f"Attempting restart in {sleep_time}s")
                        time.sleep(sleep_time)
                        # regenerate playlist before restart
                        scan_and_write_playlist(str(VIDEOS_DIR), str(PLAYLIST_PATH), shuffle=shuffle)
                        cmd_local = self._build_ffmpeg_cmd(stream_key=stream_key)
                        newproc = self._launch_ffmpeg(cmd_local)
                        if newproc:
                            backoff = 1
                        else:
                            backoff = min(backoff * 2, 60)

                t = threading.Thread(target=monitor, daemon=True)
                self._monitor_thread = t
                t.start()

            return True

    def stop(self, timeout: int = 10) -> bool:
        """Stop the FFmpeg process gracefully, return True if stopped."""
        with self._lock:
            # prevent monitor from restarting
            self._should_run = False
            pid_alive = self._pidfile_exists_and_alive()
            # Prefer in-process handle if available
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.send_signal(signal.SIGTERM)
                except Exception:
                    pass
                # wait
                try:
                    self._proc.wait(timeout=timeout)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                finally:
                    log_event(f"Stopped streaming (pid={self._proc.pid})")
                    try:
                        PID_PATH.unlink()
                    except Exception:
                        pass
                    self._proc = None
                    return True

            if pid_alive:
                try:
                    os.kill(pid_alive, signal.SIGTERM)
                except Exception:
                    pass
                # wait for it to go away
                start = time.time()
                while time.time() - start < timeout:
                    if not self._pidfile_exists_and_alive():
                        break
                    time.sleep(0.5)

                # If still alive, try SIGKILL
                if self._pidfile_exists_and_alive():
                    try:
                        os.kill(pid_alive, signal.SIGKILL)
                    except Exception:
                        pass

                try:
                    PID_PATH.unlink()
                except Exception:
                    pass
                log_event(f"Stopped streaming (pid={pid_alive})")
                self._proc = None
                return True

            # Nothing to stop
            return False

    def tail_logs(self, lines: int = 200) -> str:
        if not LOG_PATH.exists():
            return ""
        try:
            with open(LOG_PATH, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                block = 1024
                data = bytearray()
                while len(data) < 65536 and size > 0 and len(data.splitlines()) <= lines:
                    read_size = min(block, size)
                    f.seek(size - read_size)
                    chunk = f.read(read_size)
                    data[:0] = chunk
                    size -= read_size
                text = data.decode(errors="replace")
                return "\n".join(text.splitlines()[-lines:])
        except Exception:
            return ""


# Global controller instance (module-level) so it's shared between Streamlit reruns
controller = StreamController()


def _get_stream_key_from_env_or_ui() -> str:
    # Prefer environment variable if set
    env_key = os.environ.get("STREAM_KEY")
    return env_key or ""


def main():
    st.set_page_config(page_title="YouTube Loop Streamer", page_icon="📺")

    st.title("YouTube 24x7 Video Loop Streamer")

    # Stream key input
    env_key = _get_stream_key_from_env_or_ui()
    if env_key:
        st.info("Using `STREAM_KEY` from environment; you can override below.")

    stream_key = st.text_input("YouTube Stream Key", value=env_key, type="password")

    # Shuffle option
    shuffle = st.checkbox("Shuffle playlist", value=False)

    # Show detected videos and regenerate automatically each run
    files = scan_videos(str(VIDEOS_DIR))
    st.subheader("Detected videos")
    if files:
        for f in files:
            st.write(f.name)
    else:
        st.info("No videos found. Add .mp4/.mkv/.mov files to the `videos/` folder.")

    # Buttons for start/stop/regenerate
    col1, col2, col3 = st.columns([1, 1, 1])
    started = False
    with col1:
        if st.button("Start Streaming"):
            if not stream_key:
                st.error("Please provide a YouTube stream key first.")
            else:
                ok = controller.start(stream_key=stream_key, shuffle=shuffle)
                if ok:
                    st.success("Streaming started")
                else:
                    st.warning("FFmpeg already running or failed to start.")
    with col2:
        if st.button("Stop Streaming"):
            ok = controller.stop()
            if ok:
                st.success("Streaming stopped")
            else:
                st.info("No running FFmpeg process found.")
    with col3:
        if st.button("Rescan videos / Regenerate playlist"):
            files = scan_and_write_playlist(str(VIDEOS_DIR), str(PLAYLIST_PATH), shuffle=shuffle)
            st.success(f"Regenerated playlist ({len(files)} files)")

    st.markdown("---")

    # Status
    st.subheader("Stream status")
    running = controller.is_running()
    st.write("Running" if running else "Stopped")

    # Logs
    st.subheader("Stream log (tail)")
    logs = controller.tail_logs(lines=200)
    st.text_area("Logs", value=logs, height=300)

    st.markdown("---")
    st.write("Playlist file is at:", str(PLAYLIST_PATH))
    st.write("Videos folder is mounted at:", str(VIDEOS_DIR))


if __name__ == "__main__":
    main()
