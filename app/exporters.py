import json
from typing import Any


def format_timestamp_srt(seconds: float) -> str:
    """Convierte segundos a formato SRT: HH:MM:SS,mmm"""
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Convierte segundos a formato WebVTT: HH:MM:SS.mmm"""
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def format_timestamp_human(seconds: float) -> str:
    """Convierte segundos a formato legible: MM:SS o HH:MM:SS"""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def export_txt(job: dict[str, Any], include_timestamps: bool = False) -> str:
    segments = job.get("segments", [])
    if not include_timestamps:
        lines = [seg["text"].strip() for seg in segments if seg.get("text", "").strip()]
        return " ".join(lines).strip() + "\n"

    lines = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start_str = format_timestamp_human(seg.get("start", 0.0))
        end_str = format_timestamp_human(seg.get("end", 0.0))
        lines.append(f"[{start_str} - {end_str}] {text}")
    return "\n".join(lines) + "\n"


def export_srt(job: dict[str, Any]) -> str:
    segments = job.get("segments", [])
    blocks = []
    idx = 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = format_timestamp_srt(seg.get("start", 0.0))
        end = format_timestamp_srt(max(seg.get("end", 0.0), seg.get("start", 0.0) + 0.1))
        blocks.append(f"{idx}\n{start} --> {end}\n{text}")
        idx += 1
    return "\n\n".join(blocks) + "\n"


def export_vtt(job: dict[str, Any]) -> str:
    segments = job.get("segments", [])
    blocks = ["WEBVTT"]
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = format_timestamp_vtt(seg.get("start", 0.0))
        end = format_timestamp_vtt(max(seg.get("end", 0.0), seg.get("start", 0.0) + 0.1))
        blocks.append(f"{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + "\n"


def export_json(job: dict[str, Any]) -> str:
    segments = job.get("segments", [])
    full_text = " ".join(
        seg["text"].strip() for seg in segments if seg.get("text", "").strip()
    )
    payload = {
        "id": job.get("id"),
        "title": job.get("title"),
        "source_type": job.get("source_type"),
        "source_url": job.get("source_url"),
        "language": job.get("detected_language") or job.get("language"),
        "duration": job.get("duration"),
        "engine": job.get("engine"),
        "model": job.get("model"),
        "device_used": job.get("device_used"),
        "created_at": job.get("created_at"),
        "full_text": full_text,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
