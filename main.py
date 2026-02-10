from fastapi import FastAPI, UploadFile, File, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from vosk import Model, KaldiRecognizer
from pydub import AudioSegment

import shutil, os, subprocess, wave
import json
import heapq 
import re

model = Model("model")

UPLOAD_DIR = "uploads"
DOWNLOAD_DIR = "downloads"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI()

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

@app.post("/transcribe")
async def transcribe_video(file: UploadFile = File(...)):
    video_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    audio_filename = os.path.splitext(file.filename)[0] + ".wav"
    audio_path = os.path.join(UPLOAD_DIR, audio_filename)
    extract_audio(video_path, audio_path)

    chunks = split_audio(audio_path, chunk_ms=30000)

    transcript = []
    offset = 0.0

    for chunk_path in chunks:
        for w in transcribe_vosk(chunk_path):
            w["start"] += offset
            w["end"] += offset
            transcript.append(w)
        
        offset += 30.0

    word_indexes = {}
    for idx, word_obj in enumerate(transcript):
        w = word_obj["word"].lower().strip(".,!?'")
        if w not in word_indexes:
            word_indexes[w] = []
        word_indexes[w].append(idx)

    freq = []
    for w in word_indexes:
        pair = (-len(word_indexes[w]), w)
        heapq.heappush(freq, pair)
    
    word_frequencies = []
    for i in range(10):
        word_frequencies.append(heapq.heappop(freq))

    return {
        "audio_file": audio_filename,
        "transcript": transcript,
        "word_indexes": word_indexes,
        "word_frequencies": word_frequencies
        
    }

@app.post("/export-video")
async def export_video(payload: dict = Body(...)):
    filename = payload.get("filename")
    mutes = payload.get("mutes")

    safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    video_path = os.path.join(UPLOAD_DIR, filename)
    output_filename = f"edited_{safe_filename}"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)

    apply_mute_edits(video_path, output_path, mutes)

    return {"filename": output_filename}

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type='application/octet-stream'
        )
    raise HTTPException(status_code=404, detail="File not found")

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

        subprocess.run(command, check=True)

def extract_audio(video_path, output_path):
    command = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-af", "afftdn",
        output_path
    ]
    
    subprocess.run(
        command, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        check = True
        )

def split_audio(wav_path, chunk_ms=30000):
    audio = AudioSegment.from_wav(wav_path)
    chunks = []

    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = f"{wav_path[:-4]}_chunk{i//chunk_ms}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    return chunks

def transcribe_vosk(wav_path):
    wf = wave.open(wav_path, "rb")
    recognizer = KaldiRecognizer(model, wf.getframerate())
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

npm run dev

Python + FastAPI + FFmpeg + Whisper + Vanilla JS


--- MVP GOAL (Reminder) ---
Paste TikTok URL
Decode audio
Transcribe with timestamps
Build word -> timestamps index
Search & jump
Export transcript


deactivate
git rm -r --cached venv

git add main.py templates/index.html static/

git add .
git commit -m "Notes"
git push -u origin main



'''
