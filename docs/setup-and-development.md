# Setup and Development

> Based on the repository as of 2026-11-13. The commands come from the Dockerfile, `package.json` and the developer notes at the bottom of `backend/main.py`. The repo has no Makefile, task runner or helper scripts.

## Prerequisites

| Tool | Requirement | Source of truth |
|---|---|---|
| Python | **3.10–3.12 recommended.** Docker uses `python:3.10-slim`. ≥3.10 is required (`str \| None` syntax in `utils/encryption.py`). On 3.13+, `pydub` fails to import because the stdlib `audioop` module was removed, which breaks the Vosk fallback **(unverified locally)**. | `Dockerfile` |
| ffmpeg + ffprobe | On `PATH`. Required for every pipeline step. | `Dockerfile` (`apt-get install ffmpeg`) |
| Node.js + npm | A version supported by Vite 7 (Node 20.19+ or 22.12+ per Vite's requirements) **(unverified against this repo)** | `frontend/package.json` |
| Supabase project | Needed even to *start* the backend (the client is created at import) | `backend/database/supabase_client.py` |
| Gladia API key | Optional. Without one, transcription uses the offline Vosk model. | `backend/services/transcription_service.py` |
| RapidAPI key | Optional, for the "TikTok Video Downloader" API. yt-dlp is used without it. | `backend/services/download_service.py` |
| Docker | Optional, to reproduce the production image | `Dockerfile` |

## Backend setup

```powershell
# from the repo root (Windows PowerShell; adapt activation for bash)
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

- `requirements.txt` is **UTF-16 LE with BOM**. pip detects the BOM and reads it, but grep, diff and git treat it as binary. If you edit it, either keep the encoding or convert it to UTF-8 deliberately as a separate change.
- Dependencies are **unpinned**. A fresh install picks up the latest FastAPI, supabase, yt-dlp and so on. The Docker build also runs `pip install -U yt-dlp`.
- `elevenlabs` is installed but only used by the legacy root `main.py`.
- The Vosk model is already committed in `model/`. No download is needed locally.

### Backend environment variables

Create `backend/.env`. A repo-root `.env` is also loaded, after the backend one; `load_dotenv` does not override variables that are already set.

| Variable | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | **Yes** (startup fails without it) | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | **Yes** | Service-role key for `auth.get_user` and `profiles` writes |
| `ENCRYPTION_KEY` | Strongly recommended | Fernet key for stored API keys. If it's missing, a new key is generated and printed on every start, so previously saved keys become unreadable. |
| `GLADIA_API_KEY` | No | Server-wide default Gladia key |
| `PORT` | No (Docker only) | Port for uvicorn in the container (default 8000) |

Generate a Fernet key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> The root `.gitignore` ignores `.env` and `.env.*` files everywhere, except `*.example` templates. To share a template of the variables, commit a `backend/.env.example` or `frontend/.env.example` with names only. Until 2026-11-13 the file was UTF-16, which git cannot parse, so older clones may have untracked `.env` files that showed up in `git status`. Run `git status` before committing anyway.

### Run the backend

```powershell
cd backend
python -m uvicorn main:app --reload      # http://127.0.0.1:8000
```

- You **must** run from `backend/`, because imports such as `from config.settings import ...` are relative to it.
- Keep a single worker. Job state is in memory.
- `--reload` restarts wipe all queued and finished jobs.
- Smoke tests: `GET /test` returns `{"message": "Hello World"}`. FastAPI's interactive docs are at `/docs`.

## Frontend setup

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Create `frontend/.env`:

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Backend base URL with no trailing slash, e.g. `http://127.0.0.1:8000` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon (public) key |

Other scripts: `npm run build` (output in `frontend/dist`), `npm run preview`, `npm run lint` (ESLint 9 flat config with the react-hooks and react-refresh plugins).

### Local CORS caveat

`backend/main.py` only allows origins matching `https://.*\.vercel\.app`. A frontend served from `http://localhost:5173` **will be blocked by CORS** when calling a local backend. `vite.config.js` has no dev proxy. Options for local work: temporarily add `http://localhost:5173` to the CORS config (don't commit it without agreeing on it, since it changes production), or add a Vite proxy.

### Supabase OAuth for local dev

`signInWithOAuth({ provider: "google" })` passes no `redirectTo`, so after login Supabase redirects to the project's configured Site URL. For local login, the Supabase project must allow `http://localhost:5173` as a redirect URL **(configured in the Supabase dashboard, not in this repo)**.

## Docker

```bash
# standard Docker usage; not scripted in the repo, image tag is arbitrary
docker build -t vtg .
docker run -p 8000:8000 --env-file backend/.env vtg
```

What the image does (from the `Dockerfile`):
1. `python:3.10-slim`, plus `ffmpeg wget unzip libgl1 libglib2.0-0`.
2. `pip install -r requirements.txt && pip install -U yt-dlp`.
3. Downloads `vosk-model-small-en-us-0.15` into `/app/model`.
4. `COPY . .` (`.dockerignore` excludes `.env`, `venv/`, `uploads/`, `downloads/`, `.git/`, `node_modules/`, `frontend/.env`).
5. `WORKDIR /app/backend`, then `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 75 --workers 1`.

The image contains the frontend sources too, but doesn't build or serve them.

## Deployment

| Part | Host | Notes |
|---|---|---|
| Backend | Render (Docker) | Env vars are set in the Render dashboard. Render supplies `PORT`. Local disk is ephemeral. |
| Frontend | Vercel (`https://video-transcript-generator.vercel.app` per README) | `VITE_*` env vars are set in Vercel and baked in at build time |
| Auth/DB | Supabase | The `profiles` table must exist with `id`, `gladia_api_key` and `rapidapi_key` columns |

There is no Render or Vercel config file in the repo (`render.yaml`, `vercel.json`); those platforms are configured through their dashboards **(inferred)**.

## Testing and validation

- **No unit tests exist**: no pytest config, test files or CI workflows.
- Frontend: run `npm run lint`.
- Backend: run the end-to-end smoke test. It needs only the standard library, so any Python can run it, and it starts its own backend with the interpreter you pass:
  ```bash
  python scripts/smoke_test.py --python venv/Scripts/python.exe        # full run
  python scripts/smoke_test.py --python <py> --preflight-only          # tools, Python, deps, env only
  python scripts/smoke_test.py --python <py> --allow-placeholder-supabase --check-trim
  python scripts/smoke_test.py --help                                  # all options
  ```
  It synthesizes a speech sample with the OS text-to-speech engine (Windows SAPI, macOS `say`, or `espeak-ng`/`espeak`), or uses `--video PATH`. It checks `/transcribe` → `/job` → `/uploads` → `/export-video` → `/download-file`, then runs ffprobe on the export and measures that the muted window is silent. It detects Gladia→Vosk fallback from the server log and removes the files it created. Exit code 1 = at least one FAIL. On a local run without Gladia, transcription currently FAILs because of the Vosk model-path bug (see [api-integrations.md](api-integrations.md#vosk-offline-speech-to-text)).
- TikTok download problems: `python scripts/tiktok_triage.py --url <public TikTok URL> [--download] [--rapidapi-key-env VAR]` tests URL resolution, yt-dlp and RapidAPI separately and names the failing layer.
- Manual checks with curl:
  ```bash
  curl http://127.0.0.1:8000/test
  curl -F "file=@sample.mp4" http://127.0.0.1:8000/transcribe          # → {"job_id": ...}
  curl http://127.0.0.1:8000/job/<job_id>                              # poll until status=done
  curl -X POST -H "Content-Type: application/json" \
       -d '{"filename":"<video_file>","mutes":[{"start":1.0,"end":1.5}]}' \
       http://127.0.0.1:8000/export-video
  curl -OJ http://127.0.0.1:8000/download-file/edited_<video_file>
  ```
- Without a Gladia key you exercise only the Vosk path. With a key, a Gladia failure still looks like success, because it silently falls back to Vosk. Check the server log for `Gladia failed, falling back to Vosk`.
- TikTok downloads depend on live third-party behaviour and may fail for reasons unrelated to your change.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Backend crashes on start in `supabase_client.py` | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` not set |
| `ModuleNotFoundError: config` | uvicorn started from the repo root instead of `backend/` |
| `FileNotFoundError` for `ffprobe`/`ffmpeg`, or "Could not read video duration" | ffmpeg not on `PATH`, or an unreadable input file |
| Browser shows a CORS error locally | Origin not matching `*.vercel.app` (see above) |
| `GET /job/<id>` returns 404 | Server restarted, job cleaned up, or more than one worker/process |
| Frontend says "Processing timed out" while the server is still working | Frontend 120 s poll limit vs. Gladia's 300 s poll cap |
| Saved API keys fail to load after restart (500) | `ENCRYPTION_KEY` missing or changed |
| Export returns 404 "Video not found" | More than 30 minutes since transcription, so the source was deleted |
| "Download Video" button fails | `/download-raw` exists only in the legacy root `main.py` |
| Rate-limit hits return 500 | slowapi handler / `app.state.limiter = None` mismatch **(unverified)** |
| `pydub`/`audioop` import error | Python 3.13+. Use 3.10–3.12. |
| Job fails with `Vosk model not found ... backend\model` | Known bug: the local model path resolves to `backend/model`; the model is in repo-root `model/` |
| Startup crashes with `UnicodeEncodeError` in `utils/encryption.py` (Windows) | `ENCRYPTION_KEY` unset and stdout redirected. Set the key, or `PYTHONIOENCODING=utf-8` |
| yt-dlp extraction errors for TikTok | yt-dlp out of date: `pip install -U yt-dlp` |
