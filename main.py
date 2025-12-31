'''
cd "D:\MJ\Coding\Resume Projects/Tiktok Transcript"
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\venv\Scripts\activate

python -m uvicorn main:app --reload

http://127.0.0.1:8000

Ctrl + Shift + P
Python: Select Interpreter

Python + FastAPI + FFmpeg + Whisper + Vanilla JS


--- MVP GOAL (Reminder) ---
Paste TikTok URL
Decode audio
Transcribe with timestamps
Build word -> timestamps index
Search & jump
Export transcript

'''



from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from vosk import Model, KaldiRecognizer
import shutil, os, subprocess, wave, json
from pydub import AudioSegment

model = Model("model")
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "transcript": "This is the transcript",
            "count": 5
        }
    )

@app.post("/", response_class=HTMLResponse)

async def handle_submission(
    request: Request,
    url: str = Form(None),
    file: UploadFile = File(None)

):

    transcript = ""
    if url:
        print("User submitted URL:", url)
        transcript = f"Transcript for: {url}"

    elif file:
        print("User uploaded:", file.filename)
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        audio_filename = os.path.splitext(file.filename)[0] + ".wav"
        audio_path = os.path.join(UPLOAD_DIR, audio_filename)
        extract_audio(file_path, audio_path)

        chunks = split_audio(audio_path, chunk_ms=30000)

        full_transcript = ""
        for chunk_path in chunks:
            full_transcript += transcribe_vosk(chunk_path) + " "
        transcript = full_transcript.strip()

        transcript = transcribe_vosk(audio_path)

    else:
        transcript = "No input received"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "transcript": transcript,
            "count": 5,
            "submitted_url": url,
            "uploaded_file": file.filename if file else None
        }
    )


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
    subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check = True)

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

    text = ""
        
    while True:
        data = wf.readframes(16000)

        if len(data) == 0:
            break
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text += result.get("text", "") + " "


    final_result = json.loads(recognizer.FinalResult())
    text += final_result.get("text", "")

    return text.strip() 









