import os
import sys
import math
import time
import shutil
import inspect
import subprocess
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.config import (
    AUDIO_DIR,
    MODELS_DIR,
    detect_gpu,
    ensure_ffmpeg,
    setup_nvidia_dlls,
)
from app.storage import store

setup_nvidia_dlls()


def _patch_pyav_compat() -> None:
    """Compatibilidad con PyAV >= 17 donde se eliminó el argumento 'metadata_errors' de av.open()."""
    try:
        import av

        sig = inspect.signature(av.open)
        if "metadata_errors" not in sig.parameters:
            orig_open = av.open

            def _compat_open(*args: Any, **kwargs: Any):
                kwargs.pop("metadata_errors", None)
                return orig_open(*args, **kwargs)

            av.open = _compat_open
    except Exception:
        pass


_patch_pyav_compat()

_model_lock = threading.Lock()
_cached_model: dict[str, Any] = {
    "key": None,
    "instance": None,
}

BROWSER_NATIVE_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}
MAX_CLOUD_BYTES = 23 * 1024 * 1024  # 23 MB margen seguro bajo límite de 25 MB


class TranscriptionCancelledError(Exception):
    pass


def probe_duration(file_path: Path) -> float | None:
    """Obtiene la duración en segundos usando PyAV o ffprobe."""
    try:
        import av
        with av.open(str(file_path)) as container:
            if container.duration:
                return float(container.duration) / 1_000_000.0
    except Exception:
        pass

    ensure_ffmpeg()
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            res = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception:
            pass
    return None


def prepare_playable_audio(src_path: Path, job_id: str) -> Path:
    """
    Si el archivo subido es un video (mp4, mkv, mov, webm...) o un formato no estándar,
    extrae el audio a MP3 para reproducción fluida en el navegador y procesamiento ligero.
    """
    ext = src_path.suffix.lower()
    if ext == ".mp3":
        return src_path

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        return src_path

    target_mp3 = AUDIO_DIR / f"{job_id}.mp3"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "4",
        str(target_mp3),
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if res.returncode == 0 and target_mp3.exists() and target_mp3.stat().st_size > 0:
        if src_path != target_mp3:
            src_path.unlink(missing_ok=True)
        return target_mp3
    return src_path


def _get_local_whisper_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    key = (model_name, device, compute_type)
    with _model_lock:
        if _cached_model["key"] == key and _cached_model["instance"] is not None:
            return _cached_model["instance"]

        # Liberar referencia anterior antes de cargar nuevo modelo
        _cached_model["instance"] = None
        _cached_model["key"] = None

        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(MODELS_DIR),
        )
        _cached_model["key"] = key
        _cached_model["instance"] = model
        return model


def decode_audio_16k(audio_path: Path) -> np.ndarray:
    """Decodifica cualquier archivo de audio/video a PCM mono 16kHz float32 usando FFmpeg."""
    ffmpeg_bin = ensure_ffmpeg()
    if ffmpeg_bin:
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-threads",
            "0",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0 and res.stdout:
            return np.frombuffer(res.stdout, np.int16).flatten().astype(np.float32) / 32768.0

    from faster_whisper.audio import decode_audio
    return decode_audio(str(audio_path), sampling_rate=16000)


def _is_cuda_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    cuda_markers = (
        "cuda",
        "cudnn",
        "cublas",
        "nvrtc",
        "out of memory",
        "gpu",
        "dll",
        "device",
    )
    return any(m in msg for m in cuda_markers)


def transcribe_local(
    *,
    job_id: str,
    audio_path: Path,
    model_name: str,
    language: str | None,
    device_pref: str = "auto",
    vad_filter: bool = True,
    task: str = "transcribe",
) -> None:
    gpu_info = detect_gpu()
    if device_pref == "auto":
        target_device = "cuda" if gpu_info["cuda_available"] else "cpu"
    else:
        target_device = device_pref

    lang_arg = None if (not language or language == "auto") else language

    store.update_job(
        job_id,
        status="preparing",
        stage_message="Decodificando onda de audio...",
        progress=5,
    )
    waveform = decode_audio_16k(audio_path)
    duration = round(float(len(waveform)) / 16000.0, 2) if len(waveform) > 0 else probe_duration(audio_path)
    if duration:
        store.update_job(job_id, duration=duration)

    attempts = []
    if target_device == "cuda":
        attempts.append(("cuda", "float16"))
        if device_pref == "auto":
            attempts.append(("cpu", "int8"))
    else:
        attempts.append(("cpu", "int8"))

    last_error = None
    for idx, (dev, ctype) in enumerate(attempts):
        if store.is_cancelled(job_id):
            raise TranscriptionCancelledError()

        if idx > 0:
            store.add_note(
                job_id,
                f"CUDA falló ({last_error}); usando CPU automáticamente.",
            )
            store.update_job(job_id, segments=[])

        dev_label = f"GPU CUDA ({ctype})" if dev == "cuda" else f"CPU ({ctype})"
        store.update_job(
            job_id,
            status="preparing",
            device_used=dev_label,
            stage_message=f"Cargando modelo Faster-Whisper '{model_name}' en {dev_label}...",
            progress=7,
        )

        try:
            model = _get_local_whisper_model(model_name, dev, ctype)
            if store.is_cancelled(job_id):
                raise TranscriptionCancelledError()

            store.update_job(
                job_id,
                status="transcribing",
                stage_message=f"Transcribiendo con {model_name} ({dev_label})...",
                progress=10,
            )

            def _run_whisper_pass(use_vad: bool) -> int:
                segments_gen, info = model.transcribe(
                    waveform,
                    language=lang_arg,
                    task=task,
                    vad_filter=use_vad,
                    vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 600} if use_vad else None,
                    condition_on_previous_text=use_vad,
                    no_speech_threshold=0.65,
                    beam_size=5,
                )

                total_dur = duration or getattr(info, "duration", None) or 0.0
                detected_lang = getattr(info, "language", None)
                store.update_job(
                    job_id,
                    detected_language=detected_lang,
                    duration=round(total_dur, 2) if total_dur else duration,
                )

                seg_idx = 0
                for seg in segments_gen:
                    if store.is_cancelled(job_id):
                        raise TranscriptionCancelledError()

                    text = seg.text.strip()
                    if not text:
                        continue

                    seg_idx += 1
                    pct = 95
                    if total_dur > 0:
                        pct = min(98, max(10, int((seg.end / total_dur) * 88) + 10))

                    store.update_job(
                        job_id,
                        stage_message=f"Transcribiendo ({pct}%) · {seg_idx} segmentos...",
                        progress=pct,
                    )
                    store.append_segment(
                        job_id,
                        {
                            "id": seg_idx,
                            "start": round(float(seg.start), 2),
                            "end": round(float(seg.end), 2),
                            "text": text,
                        },
                        progress=pct,
                    )
                return seg_idx

            count = _run_whisper_pass(vad_filter)
            # Si el usuario activó VAD en una canción y filtró casi toda la voz cantada, reintentar sin VAD
            if vad_filter and count <= 2 and (duration or 0) > 30:
                store.add_note(
                    job_id,
                    "Se detectó música/canto; desactivando filtro VAD automáticamente para capturar toda la letra.",
                )
                store.update_job(job_id, segments=[], progress=12)
                _run_whisper_pass(False)
            return

        except TranscriptionCancelledError:
            raise
        except Exception as exc:
            last_error = exc
            if dev == "cuda" and idx + 1 < len(attempts) and _is_cuda_error(exc):
                continue
            raise last_error


def _prepare_cloud_chunks(audio_path: Path, job_id: str) -> list[tuple[Path, float]]:
    """
    Garantiza que el audio enviado a la API en la nube no supere los 25 MB.
    Si es grande, lo comprime a 16kHz mono 48kbps y lo divide en fragmentos de 20 min.
    Devuelve lista de (ruta_chunk, offset_segundos).
    """
    if audio_path.stat().st_size <= MAX_CLOUD_BYTES and audio_path.suffix.lower() in {
        ".mp3",
        ".m4a",
        ".wav",
        ".ogg",
        ".webm",
        ".flac",
    }:
        return [(audio_path, 0.0)]

    ffmpeg_bin = ensure_ffmpeg()
    if not ffmpeg_bin:
        raise RuntimeError(
            "El archivo supera 24 MB y se requiere FFmpeg para comprimirlo/dividirlo antes de enviarlo a la API."
        )

    # Primero comprimir a 16kHz mono 48kbps (~21 MB por hora)
    compressed = AUDIO_DIR / f"{job_id}_cloud.mp3"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "48k",
            str(compressed),
        ],
        capture_output=True,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    if compressed.stat().st_size <= MAX_CLOUD_BYTES:
        return [(compressed, 0.0)]

    # Dividir en bloques de 1200 segundos (20 min ~ 7 MB c/u)
    chunk_seconds = 1200
    total_dur = probe_duration(compressed) or 3600.0
    num_chunks = max(1, math.ceil(total_dur / chunk_seconds))
    chunks: list[tuple[Path, float]] = []

    for i in range(num_chunks):
        offset = i * chunk_seconds
        chunk_path = AUDIO_DIR / f"{job_id}_chunk_{i:03d}.mp3"
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-ss",
                str(offset),
                "-t",
                str(chunk_seconds),
                "-i",
                str(compressed),
                "-acodec",
                "copy",
                str(chunk_path),
            ],
            capture_output=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if chunk_path.exists() and chunk_path.stat().st_size > 0:
            chunks.append((chunk_path, float(offset)))

    compressed.unlink(missing_ok=True)
    return chunks


def transcribe_cloud(
    *,
    job_id: str,
    audio_path: Path,
    provider: str,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    language: str | None,
    task: str = "transcribe",
) -> None:
    from openai import OpenAI

    resolved_key = (api_key or "").strip()
    if not resolved_key:
        if provider == "groq":
            resolved_key = os.getenv("GROQ_API_KEY", "").strip()
        else:
            resolved_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not resolved_key:
        raise ValueError(
            f"Falta la API Key para el proveedor '{provider.upper()}'. Ingrésala en la interfaz o configúrala en el archivo .env."
        )

    if base_url and base_url.strip():
        resolved_url = base_url.strip()
    elif provider == "groq":
        resolved_url = "https://api.groq.com/openai/v1"
    else:
        resolved_url = None  # Por defecto OpenAI oficial

    duration = probe_duration(audio_path)
    if duration:
        store.update_job(job_id, duration=round(duration, 2))

    provider_label = provider.upper()
    store.update_job(
        job_id,
        status="preparing",
        device_used=f"Cloud API ({provider_label})",
        stage_message="Preparando audio para envío a la API...",
        progress=10,
    )

    chunks = _prepare_cloud_chunks(audio_path, job_id)
    cleanup_files = [p for p, _ in chunks if p != audio_path]

    try:
        client = OpenAI(api_key=resolved_key, base_url=resolved_url)
        lang_arg = None if (not language or language == "auto") else language
        seg_counter = 0

        for idx, (chunk_path, offset) in enumerate(chunks):
            if store.is_cancelled(job_id):
                raise TranscriptionCancelledError()

            pct_base = 15 + int((idx / len(chunks)) * 80)
            chunk_label = (
                f" (parte {idx + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            )
            store.update_job(
                job_id,
                status="transcribing",
                stage_message=f"Transcribiendo en {provider_label} ({model_name}){chunk_label}...",
                progress=pct_base,
            )

            with chunk_path.open("rb") as audio_file:
                if task == "translate":
                    resp = client.audio.translations.create(
                        model=model_name,
                        file=audio_file,
                        response_format="verbose_json",
                    )
                else:
                    kwargs: dict[str, Any] = {
                        "model": model_name,
                        "file": audio_file,
                        "response_format": "verbose_json",
                        "timestamp_granularities": ["segment"],
                    }
                    if lang_arg:
                        kwargs["language"] = lang_arg
                    resp = client.audio.transcriptions.create(**kwargs)

            resp_dict = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            detected_lang = resp_dict.get("language")
            if detected_lang and idx == 0:
                store.update_job(job_id, detected_language=detected_lang)

            raw_segments = resp_dict.get("segments") or []
            if raw_segments:
                for s in raw_segments:
                    text = (s.get("text") or "").strip()
                    if not text:
                        continue
                    seg_counter += 1
                    store.append_segment(
                        job_id,
                        {
                            "id": seg_counter,
                            "start": round(float(s.get("start", 0.0)) + offset, 2),
                            "end": round(float(s.get("end", 0.0)) + offset, 2),
                            "text": text,
                        },
                        progress=min(98, pct_base + int(80 / len(chunks))),
                    )
            else:
                full_txt = (resp_dict.get("text") or "").strip()
                if full_txt:
                    seg_counter += 1
                    end_ts = offset + (duration or 0.0)
                    store.append_segment(
                        job_id,
                        {
                            "id": seg_counter,
                            "start": round(offset, 2),
                            "end": round(end_ts, 2),
                            "text": full_txt,
                        },
                        progress=95,
                    )
    finally:
        for temp_path in cleanup_files:
            temp_path.unlink(missing_ok=True)


def run_job_pipeline(
    *,
    job_id: str,
    source_type: str,
    url: str | None,
    uploaded_path: Path | None,
    engine: str,
    provider: str,
    model_name: str,
    language: str | None,
    device_pref: str,
    vad_filter: bool,
    task: str,
    api_key: str | None,
    base_url: str | None,
) -> None:
    """Ejecuta el flujo completo de descarga/preparación y transcripción en un hilo de fondo."""
    from app.youtube import DownloadCancelledError, download_audio_from_url

    t0 = time.time()
    try:
        if source_type == "youtube":
            if not url:
                raise ValueError("URL vacía.")
            store.update_job(
                job_id,
                status="downloading",
                stage_message="Conectando con YouTube / servidor de video...",
                progress=2,
            )

            def on_dl_progress(pct: int, msg: str) -> None:
                # Escalar descarga de 2% a 20%
                scaled = max(2, min(20, int(pct * 0.2)))
                store.update_job(job_id, status="downloading", stage_message=msg, progress=scaled)

            dl_info = download_audio_from_url(
                url=url,
                job_id=job_id,
                on_progress=on_dl_progress,
                is_cancelled=lambda: store.is_cancelled(job_id),
            )
            audio_path = dl_info["audio_path"]
            store.update_job(
                job_id,
                title=dl_info["title"],
                channel=dl_info.get("channel"),
                duration=dl_info.get("duration"),
                thumbnail=dl_info.get("thumbnail"),
                source_url=dl_info.get("webpage_url") or url,
                audio_filename=dl_info["audio_filename"],
                persist=True,
            )
        else:
            if not uploaded_path or not uploaded_path.exists():
                raise ValueError("No se encontró el archivo subido.")
            store.update_job(
                job_id,
                status="preparing",
                stage_message="Preparando pista de audio...",
                progress=4,
            )
            audio_path = prepare_playable_audio(uploaded_path, job_id)
            store.update_job(
                job_id,
                audio_filename=audio_path.name,
                persist=True,
            )

        if store.is_cancelled(job_id):
            raise TranscriptionCancelledError()

        if engine == "cloud":
            transcribe_cloud(
                job_id=job_id,
                audio_path=audio_path,
                provider=provider,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                language=language,
                task=task,
            )
        else:
            transcribe_local(
                job_id=job_id,
                audio_path=audio_path,
                model_name=model_name,
                language=language,
                device_pref=device_pref,
                vad_filter=vad_filter,
                task=task,
            )

        elapsed = round(time.time() - t0, 1)
        store.update_job(
            job_id,
            status="completed",
            stage_message=f"Transcripción completada en {elapsed}s",
            progress=100,
            elapsed_seconds=elapsed,
            persist=True,
        )

    except (TranscriptionCancelledError, DownloadCancelledError):
        store.update_job(
            job_id,
            status="cancelled",
            stage_message="Transcripción cancelada.",
            persist=True,
        )
    except Exception as exc:
        store.update_job(
            job_id,
            status="error",
            stage_message="Error durante el proceso",
            error=str(exc),
            persist=True,
        )
