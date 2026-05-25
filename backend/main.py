from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import os

from config.settings import UPLOAD_DIR, DOWNLOAD_DIR
from utils.file_utils import ensure_dir_exists
from routes.profile_routes import router as profile_router
from routes.transcription_routes import router as transcription_router

os.environ['no_proxy'] = '*'

class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

ensure_dir_exists(UPLOAD_DIR)
ensure_dir_exists(DOWNLOAD_DIR)

app = FastAPI()

# CORS MIDDLEWARE FIRST - THIS IS CRITICAL!
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://video-transcript-generator.vercel.app",
        "https://video-transcript-generator-kywlls-projects.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Global OPTIONS handler
@app.options("{path:path}")
async def options_handler(request: Request, path: str):
    response = JSONResponse(content={"success": True}, status_code=200)
    response.headers["Access-Control-Allow-Origin"] = "https://video-transcript-generator-kywlls-projects.vercel.app"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

@app.get("/test")
async def test_endpoint():
    return {"message": "Hello World"}

app.include_router(profile_router)
app.include_router(transcription_router)



'''
cd "D:\MJ\Coding\Resume Projects/Tiktok Transcript"
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\venv\Scripts\activate

cd backend
..\venv\Scripts\activate
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
