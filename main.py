from fastapi import FastAPI, UploadFile, File, Body, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Form

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from difflib import get_close_matches

import shutil, os, subprocess
import threading
import time
import json
import heapq 
import re
import yt_dlp
import uuid
import queue

from elevenlabs.client import ElevenLabs

TARGET_WORDS = [
    "tiktok", "facebook", "instagram", "messenger",
    "telegram", "whatsapp", "viber", "shopee", "lazada"
]

PHONETIC_MAP = {
    "ticktock": "tiktok",
    "ticktok": "tiktok",
    "tik tok": "tiktok",
    "face book": "facebook",
    "insta gram": "instagram",
    "whats up": "whatsapp",
    "what's up": "whatsapp"
}

def normalize_word(word):
    clean = word.lower().strip(".,!?'")

    # direct phonetic mapping first
    if clean in PHONETIC_MAP:
        return PHONETIC_MAP[clean]

    # fuzzy match fallback
    match = get_close_matches(clean, TARGET_WORDS, n=1, cutoff=0.7)
    return match[0] if match else clean

MAX_DURATION = 120
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

os.environ['no_proxy'] = '*'

class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

UPLOAD_DIR = "uploads"
DOWNLOAD_DIR = "downloads"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI()

JOB_QUEUE = queue.Queue()
JOB_RESULTS = {}  # job_id -> {status, result?, error?}

NUM_WORKERS = 2  # adjust (2–3 for small server)

def worker():
    while True:
        job_id, func, args = JOB_QUEUE.get()
        try:
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "processing"
            result = func(*args)
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "done"
                job["result"] = result
        except Exception as e:
            print(f"[JOB ERROR] {job_id}: {e}")
            job = JOB_RESULTS.get(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(e)
        finally:
            JOB_QUEUE.task_done()

# start workers
for _ in range(NUM_WORKERS):
    threading.Thread(target=worker, daemon=True).start()

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Slow down."}
    )

def get_ip(request):
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host

limiter = Limiter(key_func=get_ip)
app.state.limiter = limiter

app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://video-transcript-generator.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

def delete_later(path, delay=900):  # 15 minutes
    def _delete():
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=_delete, daemon=True).start()

def download_tiktok(url, target_dir, rapidapi_key=None):

    if rapidapi_key and rapidapi_key.strip():

        endpoint = (
            "https://tiktok-api23.p.rapidapi.com/api/download/video"
        )

        response = requests.get(
            endpoint,
            headers={
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": "tiktok-api23.p.rapidapi.com"
            },
            params={"url": url},
            timeout=30
        )

        data = response.json()

        video_url = (
            data.get("download_url")
            or data.get("play")
        )

        if not video_url:
            raise HTTPException(
                status_code=400,
                detail="RapidAPI could not retrieve video"
            )

        filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(
            target_dir,
            filename
        )

        with requests.get(
            video_url,
            stream=True
        ) as r:

            r.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)

        return output_path

    # fallback existing yt-dlp logic

    unique_id = str(uuid.uuid4())

    output_template = (
        f"{target_dir}/{unique_id}.%(ext)s"
    )

    ydl_opts = {
        "outtmpl": output_template,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=False
        )

    duration = info.get("duration")

    if duration and duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long ({int(duration)}s)"
        )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=True
        )

        filename = ydl.prepare_filename(info)

    return filename

def cleanup_jobs():
    while True:
        time.sleep(1800)  # 30 minutes
        keys_to_delete = []

        for job_id, job in list(JOB_RESULTS.items()):
            if job.get("status") in ["done", "failed"] and "result" in job:
                keys_to_delete.append(job_id)

        for k in keys_to_delete:
            JOB_RESULTS.pop(k, None)

# start cleanup thread
threading.Thread(target=cleanup_jobs, daemon=True).start()

@app.get("/job/{job_id}")
async def get_job(job_id: str):
    job = JOB_RESULTS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job

@app.post("/transcribe-url")
@limiter.limit("5/minute")
async def transcribe_tiktok(request: Request, payload: dict = Body(...)):
    url = payload.get("url")
    language = payload.get("language", "multi")
    elevenlabs_api_key = payload.get("elevenlabs_api_key")
    rapidapi_key = payload.get("rapidapi_key")

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        video_path = download_tiktok(
            url,
            UPLOAD_DIR,
            rapidapi_key
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = os.path.basename(video_path)

    job_id = str(uuid.uuid4())
    JOB_RESULTS[job_id] = {"status": "queued"}

    def job():
        audio_path = None

        try:
            transcript, word_indexes, word_frequencies, audio_filename = process_video(
                video_path,
                filename,
                elevenlabs_api_key,
                language
            )

            audio_path = os.path.join(UPLOAD_DIR, audio_filename)

            return {
                "audio_file": audio_filename,
                "video_file": filename,
                "transcript": transcript,
                "word_indexes": word_indexes,
                "word_frequencies": word_frequencies
            }

        finally:
            # cleanup AFTER processing (safe)
            if video_path and os.path.exists(video_path):
                delete_later(video_path)

            if audio_path and os.path.exists(audio_path):
                delete_later(audio_path, delay=1800)  # 30 mins

    JOB_QUEUE.put((job_id, job, ()))

    return {"job_id": job_id}

@app.post("/transcribe")
@limiter.limit("5/minute")
async def transcribe_video(
    request: Request,
    file: UploadFile = File(...),
    elevenlabs_api_key: str = Form(None),
    language: str = Form("multi")
):
    unique_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    safe_name = f"{unique_id}{ext}"
    video_path = os.path.join(UPLOAD_DIR, safe_name)

    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    if size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")
    
    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job_id = str(uuid.uuid4())
    JOB_RESULTS[job_id] = {"status": "queued"}

    def job():
        audio_path = None

        try:
            transcript, word_indexes, word_frequencies, audio_filename = process_video(
                video_path,
                safe_name,
                elevenlabs_api_key,
                language
            )
            audio_path = os.path.join(UPLOAD_DIR, audio_filename)

            return {
                "audio_file": audio_filename,
                "video_file": safe_name,
                "transcript": transcript,
                "word_indexes": word_indexes,
                "word_frequencies": word_frequencies
            }

        finally:
            # cleanup AFTER processing
            if video_path and os.path.exists(video_path):
                delete_later(video_path)

            if audio_path and os.path.exists(audio_path):
                delete_later(audio_path, delay=1800)  # 30 mins

    JOB_QUEUE.put((job_id, job, ()))

    return {"job_id": job_id}

@app.post("/export-video")
async def export_video(payload: dict = Body(...)):
    filename = payload.get("filename")

    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    mutes = payload.get("mutes")

    if mutes and not isinstance(mutes, list):
        raise HTTPException(status_code=400, detail="Invalid mutes format")

    safe_filename = os.path.basename(filename)

    safe_input = os.path.basename(filename)
    video_path = os.path.join(UPLOAD_DIR, safe_input)

    output_filename = f"edited_{safe_filename}"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")

    apply_mute_edits(video_path, output_path, mutes)

    return {"filename": output_filename}

@app.post("/download-raw")
async def download_raw(payload: dict = Body(...)):
    url = payload.get("url")

    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    try:
        video_path = download_tiktok(url, DOWNLOAD_DIR)
        filename = os.path.basename(video_path)

        if video_path and os.path.exists(video_path):
            delete_later(video_path, delay=900)

        return {"filename": filename}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{filename}")
async def download_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, safe_name)

    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type='application/octet-stream'
        )

    raise HTTPException(status_code=404, detail="File not found")

def process_video(video_path, filename, user_api_key=None, language="multi"):
    duration = get_video_duration(video_path)

    if duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long ({int(duration)}s). Max allowed is {MAX_DURATION}s"
        )

    audio_filename = f"{uuid.uuid4()}.wav"
    audio_path = os.path.join(UPLOAD_DIR, audio_filename)
    extract_audio(video_path, audio_path)

    key = (
        user_api_key
        or ELEVENLABS_API_KEY
    )

    if not key:
        raise HTTPException(
            status_code=400,
            detail="ElevenLabs API key required"
        )

    transcript = transcribe_elevenlabs(
        audio_path,
        key
    )
            
    if not transcript:
        raise HTTPException(status_code=500, detail="Empty transcript")
    

    word_indexes = {}

    i = 0
    while i < len(transcript):
        word_obj = transcript[i]
        current = word_obj["word"].lower().strip(".,!?'")

        # try combining with next word
        if i < len(transcript) - 1:
            next_word = transcript[i + 1]["word"].lower().strip(".,!?'")
            combined = f"{current} {next_word}"

            # check phonetic combined
            if combined in PHONETIC_MAP:
                normalized = PHONETIC_MAP[combined]

                if normalized not in word_indexes:
                    word_indexes[normalized] = []

                word_indexes[normalized].append(i)

                i += 2
                continue

        # normal single word
        normalized = normalize_word(current)

        if normalized not in word_indexes:
            word_indexes[normalized] = []

        word_indexes[normalized].append(i)

        i += 1

    freq = []
    for w in word_indexes:
        pair = (-len(word_indexes[w]), w)
        heapq.heappush(freq, pair)
    
    word_frequencies = []
    for i in range(min(10, len(freq))):
        word_frequencies.append(heapq.heappop(freq))

    return transcript, word_indexes, word_frequencies, audio_filename

def apply_mute_edits(input_path, output_path, mutes):
    if not mutes:
        shutil.copy(input_path, output_path)
    else:
        filter_parts = []
        for m in mutes:
            s = max(0, m['start'] - 0.1)
            e = max(0, m['end'] - 0.1)
            filter_parts.append(f"volume=enable='between(t,{s},{e})':volume=0")
        
        audio_filter = ",".join(filter_parts)

        command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", audio_filter,
            "-c:v", "copy",
            "-c:a", "aac",
            output_path
        ]

        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            print(result.stderr)
            raise HTTPException(status_code=500, detail="Video export failed")

def extract_audio(video_path, output_path):
    command = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        #"-af", "highpass=f=200,lowpass=f=3000",
        #"-af", "afftdn",
        output_path
    ]
    
    subprocess.run(
        command, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        check = True
        )

def transcribe_elevenlabs(
    wav_path,
    api_key
):
    client = ElevenLabs(
        api_key=api_key
    )

    with open(wav_path, "rb") as f:

        result = client.speech_to_text.convert(
            file=f,
            model_id="scribe_v2",
            diarize=False,
            timestamps_granularity="word"
        )

    words = []

    for w in result.words:

        if w.type != "word":
            continue

        words.append({
            "word": w.text,
            "start": w.start,
            "end": w.end
        })

    return words


from vosk import Model, KaldiRecognizer
from pydub import AudioSegment
import wave

vosk_model = Model("model")

def split_audio(wav_path, chunk_ms=30000):
    audio = AudioSegment.from_wav(wav_path)
    chunks = []

    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = f"{wav_path[:-4]}_chunk{i//chunk_ms}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    return chunks

def transcribe_vosk_wrapper(audio_path):
    chunks = split_audio(audio_path, chunk_ms=10000)

    transcript = []
    offset = 0.0

    for chunk_path in chunks:
        for w in transcribe_vosk(chunk_path):
            transcript.append({
                "word": w["word"],
                "start": w["start"] + offset,
                "end": w["end"] + offset
            })
        offset += 10.0

        if os.path.exists(chunk_path):
            os.remove(chunk_path)

    return transcript


def transcribe_vosk(wav_path):
    wf = wave.open(wav_path, "rb")
    recognizer = KaldiRecognizer(vosk_model, wf.getframerate())
    recognizer.SetWords(True)

    words_with_timestamps = []
        
    while True:
        data = wf.readframes(16000)

        if len(data) == 0:
            break

        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            if "result" in result:
                words_with_timestamps.extend(result["result"])


    final_result = json.loads(recognizer.FinalResult())
    if "result" in final_result:
        words_with_timestamps.extend(final_result["result"])
    
    wf.close()
    return words_with_timestamps


def get_video_duration(video_path):
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except:
        raise HTTPException(
            status_code=400,
            detail="Could not read video duration"
        )

'''
cd "D:\MJ\Coding\Resume Projects/Tiktok Transcript"
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\venv\Scripts\activate

python -m uvicorn main:app --reload

http://127.0.0.1:8000

Open a SECOND terminal
cd frontend

npm run dev
http://localhost:5173/

Ctrl + Shift + P
Python: Select Interpreter

deactivate
git rm -r --cached venv

'''
