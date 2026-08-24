# backend/routes/transcription_routes.py
from fastapi import APIRouter, UploadFile, File, Body, Request, Form, HTTPException
import os
import uuid
import shutil
from job_queue import JOB_QUEUE, JOB_RESULTS
from services.download_service import download_tiktok
from services.transcription_service import process_video
from services.video_service import apply_mute_edits, trim_video
from config.settings import UPLOAD_DIR, DOWNLOAD_DIR, MAX_FILE_SIZE
from utils.file_utils import delete_later
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def create_transcription_job(
    video_path: str,
    video_filename: str,
    gladia_api_key: str,
    language: str,
    export_available: bool,
    tiktok_metadata: dict = None
):
    """Create a transcription job function for the queue"""
    def job():
        audio_path = None
        try:
            transcript, word_indexes, word_frequencies, audio_filename = process_video(
                video_path,
                video_filename,
                gladia_api_key,
                language
            )
            audio_path = os.path.join(UPLOAD_DIR, audio_filename)
            result = {
                "audio_file": audio_filename,
                "video_file": video_filename,
                "transcript": transcript,
                "word_indexes": word_indexes,
                "word_frequencies": word_frequencies,
                "export_available": export_available
            }
            if tiktok_metadata:
                result["tiktok_metadata"] = tiktok_metadata
            return result
        finally:
            if video_path and os.path.exists(video_path):
                delete_later(video_path, delay=1800)
            if audio_path and os.path.exists(audio_path):
                delete_later(audio_path, delay=1800)
    return job


@router.get("/job/{job_id}")
async def get_job(job_id: str):
    job = JOB_RESULTS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/transcribe-url")
@limiter.limit("5/minute")
async def transcribe_tiktok(request: Request, payload: dict = Body(...)):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("transcribe-url called with payload: %s", payload)
    
    url = payload.get("url")
    language = payload.get("language", "multi")
    gladia_api_key = payload.get("gladia_api_key")
    rapidapi_key = payload.get("rapidapi_key")

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        logger.info("Calling download_tiktok with rapidapi_key: %s", "provided" if rapidapi_key else "not provided")
        video_path, export_available, tiktok_metadata, _ = download_tiktok(url, UPLOAD_DIR, rapidapi_key)
        logger.info("download_tiktok succeeded, video_path: %s", video_path)
        logger.info("export_available: %s", export_available)
        logger.info("tiktok_metadata: %s", tiktok_metadata)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("download_tiktok failed: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

    filename = os.path.basename(video_path)
    job_id = str(uuid.uuid4())
    JOB_RESULTS[job_id] = {"status": "queued"}
    job = create_transcription_job(video_path, filename, gladia_api_key, language, export_available, tiktok_metadata)
    JOB_QUEUE.put((job_id, job, ()))

    return {"job_id": job_id}


@router.post("/transcribe")
@limiter.limit("5/minute")
async def transcribe_video(
    request: Request,
    file: UploadFile = File(...),
    gladia_api_key: str = Form(None),
    language: str = Form("multi")
):
    unique_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{unique_id}{ext}"
    video_path = os.path.join(UPLOAD_DIR, safe_name)

    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    
    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Trim uploaded video if needed
    trimmed_video_path = trim_video(video_path, UPLOAD_DIR)
    
    # Get final filename
    final_filename = os.path.basename(trimmed_video_path)
    
    # If trimmed, clean up original file
    if trimmed_video_path != video_path and os.path.exists(video_path):
        os.remove(video_path)

    # Check if uploaded file is a video
    from services.download_service import is_video_file
    export_available = is_video_file(trimmed_video_path)

    job_id = str(uuid.uuid4())
    JOB_RESULTS[job_id] = {"status": "queued"}
    job = create_transcription_job(trimmed_video_path, final_filename, gladia_api_key, language, export_available)
    JOB_QUEUE.put((job_id, job, ()))

    return {"job_id": job_id}


def create_export_job(video_path, output_path, mutes):
    """Create a video export job function for the queue"""
    def job():
        apply_mute_edits(video_path, output_path, mutes)
        return {"output_path": output_path}
    return job


@router.post("/export-video")
async def export_video(payload: dict = Body(...)):
    filename = payload.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    mutes = payload.get("mutes")
    if mutes and not isinstance(mutes, list):
        raise HTTPException(status_code=400, detail="Invalid mutes format")

    safe_filename = os.path.basename(filename)
    video_path = os.path.join(UPLOAD_DIR, safe_filename)

    output_filename = f"edited_{safe_filename}"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")

    job_id = str(uuid.uuid4())
    JOB_RESULTS[job_id] = {"status": "queued"}
    job = create_export_job(video_path, output_path, mutes)
    JOB_QUEUE.put((job_id, job, ()))
    return {"job_id": job_id, "output_filename": output_filename}

from fastapi.responses import FileResponse

@router.get("/download-file/{filename}")
async def download_file(filename: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=file_path,
        filename=safe_filename,
        media_type="video/mp4",
        content_disposition_type="attachment"
    )