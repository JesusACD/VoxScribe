import asyncio
import json
import re
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import AUDIO_DIR, STATIC_DIR, ensure_ffmpeg, get_system_info
from app.exporters import export_json, export_srt, export_txt, export_vtt
from app.storage import store
from app.transcriber import run_job_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-inicializar FFmpeg en segundo plano al arrancar para no bloquear el primer uso
    threading.Thread(target=ensure_ffmpeg, daemon=True).start()
    yield


app = FastAPI(
    title="VoxScribe · Transcriptor de YouTube y Audio",
    version="1.0.0",
    lifespan=lifespan,
)


class UrlTranscribeRequest(BaseModel):
    url: str
    engine: str = "local"  # "local" | "cloud"
    provider: str = "groq"  # "groq" | "openai" | "custom"
    model: str = "large-v3-turbo"
    language: str = "auto"
    device: str = "auto"  # "auto" | "cuda" | "cpu"
    vad_filter: bool = False
    task: str = "transcribe"  # "transcribe" | "translate"
    api_key: str | None = None
    base_url: str | None = None


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name or "transcripcion").strip(" ._")
    return (cleaned[:90] or "transcripcion")


@app.get("/api/system-info")
def api_system_info():
    return get_system_info()


@app.get("/api/jobs")
def api_list_jobs():
    return {"jobs": store.list_jobs()}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return job


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str):
    ok = store.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return {"deleted": True}


class RetryJobRequest(BaseModel):
    engine: str = "local"
    provider: str = "groq"
    model: str = "large-v3-turbo"
    language: str = "auto"
    device: str = "auto"
    vad_filter: bool = False
    task: str = "transcribe"
    api_key: str | None = None
    base_url: str | None = None


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str, req: RetryJobRequest):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")

    audio_fn = job.get("audio_filename")
    existing_audio = (AUDIO_DIR / audio_fn) if audio_fn else None
    has_local_audio = bool(existing_audio and existing_audio.exists())

    if not has_local_audio and not job.get("source_url"):
        raise HTTPException(
            status_code=400,
            detail="El archivo de audio original ya no existe; vuelve a subirlo.",
        )

    store._cancelled.discard(job_id)
    updated = store.update_job(
        job_id,
        status="queued",
        stage_message="Reintentando transcripción...",
        progress=2,
        engine=req.engine,
        model=req.model,
        language=req.language or "auto",
        detected_language=None,
        segments=[],
        notes=[],
        error=None,
        persist=True,
    )

    t = threading.Thread(
        target=run_job_pipeline,
        kwargs={
            "job_id": job_id,
            "source_type": "file" if has_local_audio else "youtube",
            "url": None if has_local_audio else job.get("source_url"),
            "uploaded_path": existing_audio if has_local_audio else None,
            "engine": req.engine,
            "provider": req.provider,
            "model_name": req.model,
            "language": req.language,
            "device_pref": req.device,
            "vad_filter": req.vad_filter,
            "task": req.task,
            "api_key": req.api_key,
            "base_url": req.base_url,
        },
        daemon=True,
    )
    t.start()
    return updated


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str):
    ok = store.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return {"cancelled": True}


@app.post("/api/transcribe/url")
def api_transcribe_url(req: UrlTranscribeRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Debes ingresar una URL válida.")

    job = store.create_job(
        title=url,
        source_type="youtube",
        engine=req.engine,
        model=req.model,
        language=req.language,
        source_url=url,
    )

    t = threading.Thread(
        target=run_job_pipeline,
        kwargs={
            "job_id": job["id"],
            "source_type": "youtube",
            "url": url,
            "uploaded_path": None,
            "engine": req.engine,
            "provider": req.provider,
            "model_name": req.model,
            "language": req.language,
            "device_pref": req.device,
            "vad_filter": req.vad_filter,
            "task": req.task,
            "api_key": req.api_key,
            "base_url": req.base_url,
        },
        daemon=True,
    )
    t.start()
    return job


@app.post("/api/transcribe/file")
def api_transcribe_file(
    file: UploadFile = File(...),
    engine: str = Form("local"),
    provider: str = Form("groq"),
    model: str = Form("large-v3-turbo"),
    language: str = Form("auto"),
    device: str = Form("auto"),
    vad_filter: bool = Form(True),
    task: str = Form("transcribe"),
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
):
    original_name = file.filename or "audio_subido"
    suffix = Path(original_name).suffix.lower() or ".bin"
    title = Path(original_name).stem or "Archivo de audio"

    job = store.create_job(
        title=title,
        source_type="file",
        engine=engine,
        model=model,
        language=language,
    )
    job_id = job["id"]
    raw_dest = AUDIO_DIR / f"{job_id}_raw{suffix}"

    try:
        with raw_dest.open("wb") as out_f:
            shutil.copyfileobj(file.file, out_f, length=1024 * 1024)
    finally:
        file.file.close()

    t = threading.Thread(
        target=run_job_pipeline,
        kwargs={
            "job_id": job_id,
            "source_type": "file",
            "url": None,
            "uploaded_path": raw_dest,
            "engine": engine,
            "provider": provider,
            "model_name": model,
            "language": language,
            "device_pref": device,
            "vad_filter": vad_filter,
            "task": task,
            "api_key": api_key,
            "base_url": base_url,
        },
        daemon=True,
    )
    t.start()
    return job


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str):
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")

    async def event_generator():
        cursor = 0
        # Enviar snapshot inicial por si ya tiene segmentos o estado avanzado
        initial = store.get_job(job_id)
        if initial:
            yield f"event: snapshot\ndata: {json.dumps(initial, ensure_ascii=False)}\n\n"
            _, cursor = store.get_events_since(job_id, 999_999_999)

        while True:
            events, cursor = store.get_events_since(job_id, cursor)
            for ev in events:
                ev_name = ev["event"]
                ev_data = json.dumps(ev["data"], ensure_ascii=False)
                yield f"event: {ev_name}\ndata: {ev_data}\n\n"

            current = store.get_job(job_id)
            if not current or current["status"] in ("completed", "error", "cancelled"):
                # Drenar cualquier evento final pendiente
                final_events, cursor = store.get_events_since(job_id, cursor)
                for ev in final_events:
                    yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/audio")
def api_job_audio(job_id: str):
    job = store.get_job(job_id)
    if not job or not job.get("audio_filename"):
        raise HTTPException(status_code=404, detail="Audio no disponible.")
    audio_path = AUDIO_DIR / job["audio_filename"]
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Archivo de audio no encontrado en disco.")
    return FileResponse(audio_path)


@app.get("/api/jobs/{job_id}/export")
def api_export_job(
    job_id: str,
    fmt: str = Query("txt", pattern="^(txt|txt_ts|srt|vtt|json)$"),
):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")

    base_name = _sanitize_filename(job.get("title") or "transcripcion")

    if fmt == "txt":
        content = export_txt(job, include_timestamps=False)
        ext, media = "txt", "text/plain; charset=utf-8"
    elif fmt == "txt_ts":
        content = export_txt(job, include_timestamps=True)
        ext, media = "txt", "text/plain; charset=utf-8"
        base_name += "_timestamps"
    elif fmt == "srt":
        content = export_srt(job)
        ext, media = "srt", "application/x-subrip; charset=utf-8"
    elif fmt == "vtt":
        content = export_vtt(job)
        ext, media = "vtt", "text/vtt; charset=utf-8"
    else:
        content = export_json(job)
        ext, media = "json", "application/json; charset=utf-8"

    return PlainTextResponse(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{base_name}.{ext}"',
        },
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")
