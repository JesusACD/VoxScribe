import json
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from app.config import JOBS_DIR, AUDIO_DIR


class JobStore:
    """Almacén en memoria y persistente en disco para trabajos de transcripción y eventos SSE."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        for path in sorted(JOBS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job_id = data.get("id")
                if job_id:
                    # Si quedó interrumpido al cerrar servidor, marcar como interrumpido
                    if data.get("status") in ("queued", "downloading", "preparing", "transcribing"):
                        data["status"] = "error"
                        data["error"] = "Proceso interrumpido al reiniciar el servidor."
                    self._jobs[job_id] = data
            except Exception:
                continue

    def create_job(
        self,
        *,
        title: str,
        source_type: str,
        engine: str,
        model: str,
        language: str | None,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        job: dict[str, Any] = {
            "id": job_id,
            "title": title,
            "source_type": source_type,  # "youtube" | "file"
            "source_url": source_url,
            "thumbnail": None,
            "channel": None,
            "audio_filename": None,
            "status": "queued",  # queued | downloading | preparing | transcribing | completed | error | cancelled
            "stage_message": "En cola...",
            "progress": 0,
            "engine": engine,
            "model": model,
            "device_used": None,
            "language": language or "auto",
            "detected_language": None,
            "duration": None,
            "elapsed_seconds": None,
            "segments": [],
            "notes": [],
            "error": None,
            "created_at": now,
            "started_ts": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._events[job_id] = []
            self._save_job_unlocked(job_id)
        return dict(job)

    def update_job(self, job_id: str, persist: bool = False, **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.update(updates)
            self._push_event_unlocked(
                job_id,
                "status",
                {
                    "status": job["status"],
                    "stage_message": job["stage_message"],
                    "progress": job["progress"],
                    "title": job["title"],
                    "thumbnail": job["thumbnail"],
                    "channel": job["channel"],
                    "duration": job["duration"],
                    "detected_language": job["detected_language"],
                    "device_used": job["device_used"],
                    "audio_filename": job["audio_filename"],
                    "elapsed_seconds": job["elapsed_seconds"],
                    "notes": job["notes"],
                    "error": job["error"],
                },
            )
            if persist:
                self._save_job_unlocked(job_id)
            return dict(job)

    def append_segment(self, job_id: str, segment: dict[str, Any], progress: int | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["segments"].append(segment)
            if progress is not None:
                job["progress"] = progress
            self._push_event_unlocked(
                job_id,
                "segment",
                {
                    "segment": segment,
                    "progress": job["progress"],
                    "stage_message": job["stage_message"],
                },
            )

    def add_note(self, job_id: str, note: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["notes"].append(note)
            self._push_event_unlocked(job_id, "note", {"note": note})

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            self._cancelled.add(job_id)
            if job["status"] in ("queued", "downloading", "preparing", "transcribing"):
                job["status"] = "cancelled"
                job["stage_message"] = "Cancelado por el usuario."
                self._push_event_unlocked(
                    job_id,
                    "status",
                    {
                        "status": "cancelled",
                        "stage_message": job["stage_message"],
                        "progress": job["progress"],
                    },
                )
                self._save_job_unlocked(job_id)
            return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries = []
            for job in self._jobs.values():
                seg_count = len(job.get("segments", []))
                preview = " ".join(
                    s.get("text", "").strip() for s in job.get("segments", [])[:4]
                )[:180]
                summaries.append(
                    {
                        "id": job["id"],
                        "title": job["title"],
                        "source_type": job["source_type"],
                        "source_url": job.get("source_url"),
                        "thumbnail": job.get("thumbnail"),
                        "status": job["status"],
                        "progress": job.get("progress", 0),
                        "engine": job.get("engine"),
                        "model": job.get("model"),
                        "detected_language": job.get("detected_language") or job.get("language"),
                        "duration": job.get("duration"),
                        "segment_count": seg_count,
                        "preview": preview,
                        "created_at": job.get("created_at"),
                    }
                )
            summaries.sort(key=lambda x: x.get("created_at") or "", reverse=True)
            return summaries

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            self._events.pop(job_id, None)
            self._cancelled.discard(job_id)
            if not job:
                return False
            job_file = JOBS_DIR / f"{job_id}.json"
            if job_file.exists():
                job_file.unlink(missing_ok=True)
            audio_fn = job.get("audio_filename")
            if audio_fn:
                audio_path = AUDIO_DIR / audio_fn
                if audio_path.exists():
                    audio_path.unlink(missing_ok=True)
            return True

    def get_events_since(self, job_id: str, cursor: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            ev_list = self._events.get(job_id, [])
            if cursor >= len(ev_list):
                return [], len(ev_list)
            return ev_list[cursor:], len(ev_list)

    def _push_event_unlocked(self, job_id: str, event_type: str, data: dict[str, Any]) -> None:
        if job_id not in self._events:
            self._events[job_id] = []
        self._events[job_id].append({"event": event_type, "data": data})

    def _save_job_unlocked(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        to_save = {k: v for k, v in job.items() if k != "started_ts"}
        path = JOBS_DIR / f"{job_id}.json"
        path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")


store = JobStore()
