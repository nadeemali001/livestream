"""
playlist_manager.py

Scans a videos directory for supported video files and writes an FFmpeg
concat demuxer playlist file (playlist.txt). Supports shuffle and safe
path quoting for FFmpeg.

Usage:
  from playlist_manager import scan_and_write_playlist
  files = scan_and_write_playlist("/Users/nadeemali/Movies/VN/Uploaded", "/Users/nadeemali/Movies/VN/Uploaded/playlist.txt", shuffle=False)

"""
from pathlib import Path
import random
from typing import List
import shutil
from datetime import datetime

SUPPORTED_EXTS = {".mp4", ".mkv", ".mov"}


def _is_supported(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS


def _quote_for_concat(path: Path) -> str:
    # FFmpeg concat demuxer expects lines like: file '/abs/path.mp4'
    # Escape single quotes by closing, escaping, and reopening.
    p = path.as_posix()
    if "'" in p:
        p = p.replace("'", "'\\''")
    return f"file '{p}'\n"


def scan_videos(videos_dir: str) -> List[Path]:
    """Return a list of video Paths in videos_dir sorted by name.

    This does not write the playlist file; just finds files.
    """
    p = Path(videos_dir)
    if not p.exists():
        return []
    found = [x for x in p.iterdir() if _is_supported(x)]
    found.sort(key=lambda x: x.name)
    return found


def write_playlist(paths: List[Path], playlist_path: str) -> None:
    """Write the FFmpeg concat demuxer playlist file at playlist_path."""
    pp = Path(playlist_path)
    # If playlist_path exists as a directory, move it aside to avoid IsADirectoryError
    if pp.exists() and pp.is_dir():
        timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        backup = Path(f"{str(pp)}.bak-{timestamp}")
        try:
            shutil.move(str(pp), str(backup))
        except Exception:
            # If move fails, try to remove directory if empty
            try:
                pp.rmdir()
            except Exception:
                raise

    pp.parent.mkdir(parents=True, exist_ok=True)
    # Write playlist file atomically: write to temp then rename
    tmp = pp.with_suffix(pp.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for p in paths:
            f.write(_quote_for_concat(p))
    # Replace target
    try:
        tmp.replace(pp)
    except Exception:
        # Fallback: move
        shutil.move(str(tmp), str(pp))


def scan_and_write_playlist(videos_dir: str, playlist_path: str, shuffle: bool = False) -> List[Path]:
    """Scan `videos_dir`, optionally shuffle, write playlist to `playlist_path`.

    Returns the final ordered list of Path objects written into the playlist.
    """
    files = scan_videos(videos_dir)
    if shuffle:
        random.shuffle(files)
    write_playlist(files, playlist_path)
    return files
