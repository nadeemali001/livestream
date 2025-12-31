# YouTube 24x7 Video Loop Streamer

This repository provides a Streamlit-based controller that streams your locally-stored video files to YouTube Live using FFmpeg. The container runs FFmpeg (no OBS, no browser) and is designed for continuous, 24x7 streaming.

Key features
- Scans `videos/` for `.mp4`, `.mkv`, `.mov` files and auto-generates `playlist.txt` in the FFmpeg concat demuxer format.
- Supports shuffle/non-shuffle modes and infinite looping with `-stream_loop -1`.
- Start/Stop streaming via Streamlit UI.
- Prevents multiple FFmpeg processes from running at once using a pidfile and process checks.
- Basic logging to `stream.log`.

File layout
- `app.py` — Streamlit UI and FFmpeg controller.
- `playlist_manager.py` — Scans `videos/` and writes `playlist.txt`.
- `requirements.txt` — Python requirements.
- `Dockerfile` — Builds the container (Ubuntu + FFmpeg + Python).
- `docker-compose.yml` — Compose file that mounts `./videos` and restarts container on failure.

Local development

Prerequisites:
- Docker and docker-compose (optional for local only testing use Python and FFmpeg installed locally)

Run without Docker (for development):

1. Create a `videos/` folder alongside the repository and add supported video files (.mp4, .mkv, .mov).
2. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3. Provide your YouTube stream key via environment or enter it in the UI.

4. Run Streamlit:

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Open http://localhost:8501 and use the UI to start/stop streaming.

Using Docker

1. Create `videos/` in the repo root and add video files.
2. (Optional) Set `STREAM_KEY` environment variable locally or pass it when running Docker.

Build and run with docker-compose:

```bash
docker-compose up -d --build
```

This maps `./videos` into the container at `/app/videos`, `stream.log` and `playlist.txt` are available locally.

The `docker-compose.yml` has `restart: always` so the container restarts on failure.

Container healthcheck
- A small in-container healthcheck (`healthcheck.sh`) verifies that an `ffmpeg` process referencing the playlist is running. Docker will mark the container unhealthy if FFmpeg is not detected and the compose `restart` policy will cause a container restart. This provides system-level safety in addition to the app-level watchdog.

Adding new videos safely
- Copy new files into the `videos/` folder on the host (volume). The app detects files at each UI refresh.
- Click "Rescan videos / Regenerate playlist" in the UI to update `playlist.txt` immediately.
- If the stream is currently running, you can safely regenerate the playlist; the existing FFmpeg process will continue the currently running playlist until you choose to restart the stream.

Restarting stream without downtime
- To update the playlist without losing the stream, you can:
  1. Regenerate playlist via UI (this writes `playlist.txt`).
  2. Use the UI to click "Stop Streaming" then immediately click "Start Streaming". The stop/start cycle is intended to be fast; however, a seamless, gapless transition requires more advanced techniques (e.g. two FFmpeg processes and RTMP handover) which are out of scope.

Security note
- Keep your YouTube stream key secret. Do not commit it to source control.
