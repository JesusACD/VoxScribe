from pathlib import Path
from typing import Callable
import shutil

from app.config import AUDIO_DIR, ensure_ffmpeg


class DownloadCancelledError(Exception):
    pass


def download_audio_from_url(
    url: str,
    job_id: str,
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """
    Descarga el mejor stream de audio desde YouTube (o cualquier sitio compatible con yt-dlp)
    y lo convierte a MP3 reproducible en navegador.
    """
    import yt_dlp

    ffmpeg_bin = ensure_ffmpeg()
    out_template = str(AUDIO_DIR / f"{job_id}.%(ext)s")

    def progress_hook(d: dict) -> None:
        if is_cancelled and is_cancelled():
            raise DownloadCancelledError("Descarga cancelada por el usuario.")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0 and on_progress:
                pct = min(95, int((downloaded / total) * 100))
                speed = d.get("_speed_str", "").strip()
                msg = f"Descargando audio ({pct}%)" + (f" · {speed}" if speed else "")
                on_progress(pct, msg)
        elif status == "finished" and on_progress:
            on_progress(97, "Convirtiendo audio descargado...")

    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }

    if ffmpeg_bin:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Localizar el archivo resultante para este job_id
    candidates = sorted(
        AUDIO_DIR.glob(f"{job_id}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No se encontró el archivo de audio descargado.")

    audio_path = candidates[0]
    return {
        "audio_path": audio_path,
        "audio_filename": audio_path.name,
        "title": info.get("title") or "Video sin título",
        "channel": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or url,
    }
