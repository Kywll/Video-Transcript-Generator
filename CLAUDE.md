# CLAUDE.md

Development guide for this repo. Facts below were verified against the code on **2026-11-13** unless marked **(unverified)**. **If this file conflicts with the code, trust the code**, and update this file if the difference matters for future work.

## 1. Project overview

A web app that transcribes short videos (uploaded files or TikTok URLs) into word-level timestamped transcripts. The user can click a word to seek, search words, mark words as muted, and export a copy of the video with those words silenced.

- **Backend**: FastAPI app in [backend/](backend/), deployed as a Docker container on Render. Uses FFmpeg/ffprobe.
- **Frontend**: React 19 + Vite SPA in [frontend/](frontend/), deployed on Vercel. Styled with Bootstrap 5 from a CDN link in [frontend/index.html](frontend/index.html), with no React-Bootstrap.
- **Transcription**: Gladia v2 (primary), with Vosk as an offline fallback.
- **TikTok download**: RapidAPI TikTok Video Downloader (when the user supplies a key), with a yt-dlp fallback.
- **Auth/storage**: Supabase (Google OAuth on the frontend; a `profiles` table that stores each user's encrypted API keys).

Detailed docs are in [docs/](docs/): [architecture](docs/architecture.md), [project-structure](docs/project-structure.md), [api-integrations](docs/api-integrations.md), [data-flow](docs/data-flow.md), [setup-and-development](docs/setup-and-development.md). This file holds persistent instructions and condensed context; the docs hold the detail.

[README.md](README.md) is **out of date**: it still describes Vosk/ElevenLabs as the main engine and says CORS allows `localhost:5173`. Neither is true now.

## 2. Live code vs. legacy code

| Path | Status |
|---|---|
| [backend/](backend/) | **Live.** This is what the Dockerfile runs (`WORKDIR /app/backend`, `uvicorn main:app`). |
| [frontend/](frontend/) | **Live.** |
| [main.py](main.py) (repo root) | **Legacy monolith**: the pre-refactor single-file backend (ElevenLabs STT, eager Vosk load). Not deployed. Don't edit it for features, and don't copy patterns from it. |
| [templates/index.html](templates/index.html), [static/index.css](static/index.css) | **Legacy** Jinja UI, not served by anything. |
| [frontend/src/App.css](frontend/src/App.css) | Vite template leftover, not imported anywhere. |
| [model/](model/) | Vosk `vosk-model-small-en-us-0.15`, committed to the repo, used for the offline fallback. |

## 3. Backend architecture ([backend/](backend/))

Imports are **relative to `backend/` as the working directory** (`from config.settings import ...`, `from services.x import ...`), not `backend.config...`. Run uvicorn from inside `backend/`, and keep this import style in new modules.

- [main.py](backend/main.py): creates the app, sets CORS, mounts static dirs, and includes the two routers. Also has `/test` and `/cors-debug` diagnostic endpoints and an unused `TLSAdapter` class.
- [config/settings.py](backend/config/settings.py): `UPLOAD_DIR`/`DOWNLOAD_DIR` (= `backend/uploads`, `backend/downloads`), `MAX_FILE_SIZE` (100 MB), `MAX_VIDEO_DURATION` (60 s). `CLEANUP_DELAY_*`, `NUM_WORKERS` and `JOB_TIMEOUT` are defined here but **unused**. The real values are hard-coded in `job_queue.py` and the routes.
- [job_queue.py](backend/job_queue.py): in-process job system. `JOB_QUEUE` (`queue.Queue`) plus `JOB_RESULTS` dict (`job_id -> {status: queued|processing|done|failed, result?, error?}`). Two daemon worker threads start **at import time**. A cleanup thread drops finished jobs every 30 minutes. **It is in-memory, so it only works with a single uvicorn worker.**
- [routes/transcription_routes.py](backend/routes/transcription_routes.py): `/transcribe`, `/transcribe-url`, `/job/{job_id}`, `/export-video`, `/download-file/{filename}`. Job closures are built by `create_transcription_job()` / `create_export_job()`.
- [routes/profile_routes.py](backend/routes/profile_routes.py): `/save-api-keys`, `/get-api-keys`, `/delete-api-key`. These validate the Supabase JWT from `Authorization: Bearer` via `supabase.auth.get_user`, then read or write `profiles`.
- [services/download_service.py](backend/services/download_service.py): `download_tiktok(url, target_dir, rapidapi_key)` returns a **4-tuple** `(path, export_available, tiktok_metadata, method)`. Preserve that contract unless every caller is updated. It tries RapidAPI ("TikTok Video Downloader API", `/media`, response field `downloadUrl`) when a key is given, then falls back to yt-dlp. In both paths the result goes through `trim_video`. Also has `is_video_file()` (ffprobe), `resolve_tiktok_url()` and `clean_url()`.
- [services/transcription_service.py](backend/services/transcription_service.py): `process_video()` is the core pipeline. It returns `(transcript, word_indexes, word_frequencies, audio_filename)`.
- [services/gladia_service.py](backend/services/gladia_service.py): Gladia v2 (upload, then `pre-recorded`, then poll every 2 s with a 5-minute cap). It sends a custom vocabulary built from `utils/normalization.py`. Languages are hard-coded to `["en", "tl"]` with code switching.
- [services/offline_transcription_service.py](backend/services/offline_transcription_service.py): Vosk fallback. The model loads lazily from the first path that exists:
  - `backend/model`: two `dirname`s of the module path. The inline comment wrongly says `backend/../model`.
  - `/app/model`.
  - `./model`: also `backend/model`, since uvicorn runs from `backend/`.

  The model is committed at the repo-root `model/`, so only Docker's `/app/model` exists. **The fallback works in Docker but fails locally** (verified 2026-11-13). Audio is split into 10-second chunks and offsets are added back.
- [services/video_service.py](backend/services/video_service.py): ffmpeg/ffprobe wrappers (`get_video_duration`, `extract_audio` → 16 kHz mono WAV, `trim_video` → first 60 s with stream copy, `apply_mute_edits`).
- [utils/normalization.py](backend/utils/normalization.py): `TARGET_WORDS` and `PHONETIC_MAP` (social and shopping brand names plus "yellow basket"), and `normalize_word()` (phonetic map, then `difflib` fuzzy match at cutoff 0.7). The same lists feed both word indexing and Gladia's custom vocabulary.
- [utils/encryption.py](backend/utils/encryption.py): Fernet `encrypt_data`/`decrypt_data` for stored API keys.
- [utils/file_utils.py](backend/utils/file_utils.py): `delete_later(path, delay)` (a sleeping daemon thread) and `ensure_dir_exists`.
- [database/supabase_client.py](backend/database/supabase_client.py): module-level `supabase` client. It also calls `load_dotenv` for `backend/.env` and then the repo-root `.env`.

## 4. Key execution flows

**Transcription** (both entry points):
1. `/transcribe` (multipart: `file`, `gladia_api_key`, `language`) saves the upload as `<uuid><ext>` in `UPLOAD_DIR`, runs `trim_video`, and sets `export_available` from `is_video_file`. `/transcribe-url` (JSON: `url`, `gladia_api_key`, `rapidapi_key`, `language`) calls `download_tiktok` **synchronously in the request**, then queues the job.
2. Both create `JOB_RESULTS[job_id] = {"status": "queued"}`, put a closure on `JOB_QUEUE`, and return `{job_id}`.
3. A worker runs `process_video`: ffprobe duration, then extract the WAV, then **Gladia if a key exists (user key or `GLADIA_API_KEY` env), otherwise Vosk**. Any Gladia exception silently falls back to Vosk (English-only, lower quality). After that it builds `word_indexes` (joining adjacent word pairs via `PHONETIC_MAP`) and the top-10 `word_frequencies` (a heap of `(-count, word)` tuples).
4. The job result is `{audio_file, video_file, transcript: [{word, start, end}], word_indexes, word_frequencies, export_available, tiktok_metadata?}`. The video and WAV are scheduled for deletion **30 minutes** after the job finishes.
5. The frontend's `pollJob` ([frontend/src/api/transcribe.js](frontend/src/api/transcribe.js)) polls `/job/{id}` with 2–5 s backoff and a **120 s client timeout**. Media plays from the `/uploads/<file>` static mount.

**Export**: `/export-video` (`{filename, mutes: [{start, end}]}`) queues `apply_mute_edits`.
- ffmpeg uses a chain of `volume=enable='between(t,s,e)':volume=0` filters with **both bounds shifted −0.1 s**. It copies the video and re-encodes the audio as AAC.
- Audio-only input gets a generated black video track.
- The frontend polls the job, then navigates to `/download-file/edited_<filename>`.
- Export only works while the source is still in `uploads/`, so within 30 minutes of transcription.

**API keys**: the frontend holds Gladia and RapidAPI keys in state. Logged-in users can save them: `/save-api-keys` **upserts both columns at once**, so `saveApiKey` in [frontend/src/App.jsx](frontend/src/App.jsx) re-sends the other saved key to avoid nulling it. Keys are sent per request in the body; the backend does not look up stored keys itself.

## 5. Frontend ([frontend/src/](frontend/src/))

- Nearly all state and handlers live in [App.jsx](frontend/src/App.jsx). Components are presentational and receive props: `Transcript` (word rendering, search, Alt+click or 500 ms long-press to mute), `ApiKeyManager`, `FileUpload`, `InputUrl` (exports `UrlInput`), `AudioPlayer` (`forwardRef`), `LoginButton`.
- HTTP goes through raw `fetch` against `import.meta.env.VITE_API_URL`. Only the transcribe and poll calls are in [api/transcribe.js](frontend/src/api/transcribe.js); the save/get/delete-key, export and raw-download fetches are inline in `App.jsx`.
- Mute preview is client-side: `App.jsx` toggles `audioRef.current.muted` using the **same −0.1 s offset** as the backend. Keep the two in sync if you change it.
- `wordIndexes` is stored but never rendered, and `word_frequencies` is unused. Search is done client-side in `Transcript.jsx`. `language` state is always `"multi"` (there is no selector), and the backend ignores `language` anyway.
- URL transcription is gated client-side by `url.includes("tiktok.com")`.

## 6. Environment variables (names only; never commit values)

Backend (`backend/.env` or repo-root `.env`, loaded by `python-dotenv`):
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`: **required at import**. `create_client` runs when `profile_routes` is imported, so the whole app fails to start without them.
- `ENCRYPTION_KEY`: Fernet key. If it's missing, a random key is generated **per process** and printed, so keys saved under it can't be decrypted after a restart.
- `GLADIA_API_KEY`: optional server-side default for Gladia. It is read with `os.getenv` at module import, so it relies on `profile_routes` (which triggers `load_dotenv`) being imported before `transcription_routes` in `main.py`. Don't reorder those imports.
- `PORT`: used by the Docker `CMD` (default 8000).
- `ELEVENLABS_API_KEY` only appears in the legacy root `main.py`.

Frontend (`frontend/.env`, Vite): `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.

Supabase schema (inferred from code; check the actual DB before relying on it): table `profiles` with `id` (= auth user id), `gladia_api_key`, `rapidapi_key` (Fernet ciphertext strings). Git history mentions an older `elevenlabs_api_key` column **(unverified)**.

## 7. Running locally

Commands come from the Dockerfile, `package.json`, and the notes at the bottom of `backend/main.py`:

```powershell
# backend (Python 3.10–3.12; Docker uses 3.10-slim. On 3.13+ pydub breaks because audioop was removed). ffmpeg and ffprobe must be on PATH.
python -m venv venv; .\venv\Scripts\activate
pip install -r requirements.txt
cd backend
python -m uvicorn main:app --reload        # http://127.0.0.1:8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                 # http://localhost:5173
npm run lint                                # ESLint flat config (eslint.config.js)
npm run build
```

```bash
# standard Docker usage (not scripted in the repo; image tag is arbitrary)
docker build -t vtg . && docker run -p 8000:8000 --env-file backend/.env vtg
```

Local-dev gotchas:
- **CORS**: [backend/main.py](backend/main.py) only allows `allow_origin_regex="https://.*\.vercel\.app"`. A local Vite frontend (`http://localhost:5173`) calling a local backend **will be blocked** until localhost is added (a protected area; see §11).
- **Single worker only**: the Dockerfile uses `--workers 1`. With multiple workers, job polling would hit a process that doesn't own the job and return 404.
- `--reload` restarts wipe all jobs and orphan any pending `delete_later` timers.

## 8. Testing and validation

There are no unit tests, no pytest config and no CI.

- **Backend pipeline changes:** run [scripts/smoke_test.py](scripts/smoke_test.py) (see the `smoke-test` skill). It uses only the standard library and starts its own backend with the interpreter you pass:
  `python scripts/smoke_test.py --python <venv python> [--allow-placeholder-supabase]`.
  On a local run without Gladia, it currently FAILs because of the Vosk model-path bug in §3.
- **TikTok download failures:** diagnose before editing code with the `tiktok-download-triage` skill. Run it with the venv interpreter, because it imports yt-dlp; `--url` is required:
  `<venv python> scripts/tiktok_triage.py --url <public TikTok URL> [--download] [--rapidapi-key-env VAR]`.
- **Frontend:** `npm run lint` and `npm run build`. There is no TypeScript and no frontend test suite.
- Check a script's `--help` before relying on the flags listed here.

Validation rules:
- Run the relevant checks after a change, starting with the most targeted one.
- Never claim a check passed unless it actually ran. Say clearly what was automated, what was manual, and what is unverified.
- The pipeline depends on external binaries and services (ffmpeg, Gladia, RapidAPI, TikTok via yt-dlp, Supabase). If a check can't run because a binary, credential or service is unavailable, say so.
- Don't add a test framework or dependency without a reason.

## 9. Known limitations, fragile areas and tech debt

These were known as of 2026-11-13. Re-verify before fixing, since they may have changed.

**Repository and configuration**
- Root [.gitignore](.gitignore) was UTF-16 until 2026-11-13, and git ignored it entirely. It is now UTF-8 and covers `.env*` (except `*.example` templates), venvs, bytecode, `node_modules`, build output, runtime media (`uploads/`, `downloads/`, `*.mp4`), logs, OS clutter and personal IDE state (`.vscode/*` except `extensions.json`, `.idea/`, `.claude/settings.local.json`). `CLAUDE.md`, `docs/`, `.claude/` and `scripts/` stay tracked deliberately. Keep it UTF-8 if you edit it.
- **[requirements.txt](requirements.txt) is still UTF-16 LE with BOM.**
  - Git shows `requirements.txt` as a binary file. pip reads it fine because it detects the BOM.
  - If you edit it, preserve or deliberately fix the encoding, and tell the user. Editing tools may keep an existing UTF-16 encoding, so check the bytes afterwards.
- `requirements.txt` is unpinned (`fastapi`, `yt-dlp[curl-cffi]`, `supabase`, …). The Dockerfile also runs `pip install -U yt-dlp`, because TikTok extraction breaks often. `elevenlabs` is still listed but is only used by the legacy root `main.py`.

**Backend**
- **`/download-raw` is called by the frontend** (`handleRawDownload` in `App.jsx`, the "Download Video" button) **but exists only in the legacy root `main.py`**, so it 404s against the live backend.
- **Rate limiting is likely broken.** The handler source is confirmed in slowapi 0.1.10, but this hasn't been exercised at runtime.
  - The routes use a module-level `slowapi.Limiter` in `transcription_routes.py`.
  - `backend/main.py` sets `app.state.limiter = None` and registers slowapi's `_rate_limit_exceeded_handler`, which calls `request.app.state.limiter._inject_headers(...)`.
  - So a rate-limit hit will probably return 500 instead of 429.
- `get_remote_address` ignores `X-Forwarded-For`, so behind Render's proxy all clients may share one rate-limit bucket. The legacy `main.py` had a `get_ip` helper for this.
- **Windows only:** with stdout redirected (pipe or file), a missing `ENCRYPTION_KEY` crashes startup, because the emoji `print` in `utils/encryption.py` can't be encoded in cp1252. An interactive console and Linux/Docker are unaffected. `scripts/smoke_test.py` sets `PYTHONIOENCODING=utf-8` for this reason.
- `/transcribe-url` downloads in the request thread, which blocks for the whole RapidAPI/yt-dlp download.
- The Gladia poll cap (300 s) exceeds the frontend poll timeout (120 s), so the UI can report a timeout on a job that is still running.
- Exported files in `downloads/` are **never deleted**, while uploads and WAVs are deleted after 30 minutes. `/uploads` is a public static mount (filenames are UUIDs).
- **Secrets in logs:**
  - `/transcribe-url` logs the full payload, including API keys.
  - `profile_routes` logs payloads and Supabase responses.
  - The RapidAPI path logs the key prefix.

  Don't add more of this, and redact if you touch those lines.
- `/delete-api-key` uses the client-supplied `key_type` directly as a column name without an allow-list.
- `trim_video` uses `-c copy` with `-t 60`, so cuts land on keyframes and duration is approximate.
- `process_video` computes `duration` but doesn't use it. The `language` argument is accepted everywhere and ignored.
- `get_video_duration` and `is_video_file` use bare `except:`. `get_video_duration` raises `HTTPException` from service code, which inside a job becomes `error: "400: ..."` in `JOB_RESULTS`.

## 10. Conventions to follow

**Backend**
- **Layering**: routes handle HTTP parsing and validation and enqueue jobs. Services do the work (subprocess calls, external APIs). Long-running work goes on `JOB_QUEUE` through a `create_*_job()` closure and is polled via `/job/{id}`. Don't add synchronous ffmpeg or STT work inside a request handler.
- Services raise `fastapi.HTTPException` directly for user-facing errors. This is the existing pattern, even though they're not route code.
- Logging: new code uses `logger = logging.getLogger(__name__)`, though `print` is still present in places. Prefer `logging`.
- Generated files are named `uuid4()` + extension. Client-provided filenames are always passed through `os.path.basename` before joining with `UPLOAD_DIR`/`DOWNLOAD_DIR`. Keep doing both.
- Use constants from `config/settings.py` rather than new literals. Some existing literals (delete delays, worker count) aren't wired to settings yet.
- Request bodies are untyped `payload: dict = Body(...)` and read with `.get()`. There are no Pydantic models.
- Word-normalization changes belong in `utils/normalization.py` and automatically affect both indexing and the Gladia vocabulary.
- Module-level side effects (threads, clients, `load_dotenv`) run at import, and import order in `backend/main.py` matters.
- Before adding a helper, check whether it already exists. ffprobe and ffmpeg helpers live in `video_service.py`, and `is_video_file` is in `download_service.py` (`apply_mute_edits` duplicates its ffprobe check inline).

**Frontend**
- Function components and hooks. State goes in `App.jsx` unless there's a reason to localize it. Use Bootstrap utility classes plus inline styles. Read the API base URL from `import.meta.env.VITE_API_URL`.
- If you change a job result's shape, update the `App.jsx` consumers too (`audio_file`, `video_file`, `transcript`, `export_available`, `tiktok_metadata`).

**General**
- Change only the live code (`backend/`, `frontend/`). Ignore the root `main.py`, `templates/` and `static/` unless the task is about them, for example deleting them or porting `/download-raw`.
- Commit messages in history mix plain sentences with `feat:`/`fix:` prefixes. Either is fine; keep them descriptive.

## 11. Protected areas and security

Before changing any of the following, explain the implications and **confirm with the user**. They are tied to the Render, Vercel and Supabase deployments:
- CORS configuration.
- The Dockerfile `CMD` or the uvicorn worker count.
- Supabase schema assumptions or database structure.
- The RapidAPI provider or the download integration (the `tiktok-download-triage` skill covers this).
- Production deployment configuration.
- Authentication or API-key storage behaviour.

Security:
- Never expose API keys, tokens or other secrets in logs, responses, commits or docs.
- Before every commit, check `git status` for `.env` files, `uploads/`, `downloads/`, media and other local artifacts. The root `.gitignore` covers these now (§9), but still check.
- Treat downloaded files, external API responses and user-provided URLs as untrusted input.
- Preserve the filename sanitization and path-safety checks.

## 12. Documentation maintenance

Docs are part of the change. Read the relevant doc before modifying existing functionality, and treat the code as the source of truth when they disagree. When a change materially affects documented behaviour, update the docs **in the same task**:

| Change | Update |
|---|---|
| Architecture, modules, responsibilities, system boundaries | `docs/architecture.md` |
| Added, removed or reorganized files and directories | `docs/project-structure.md` |
| External APIs, providers, auth, integration behaviour | `docs/api-integrations.md` |
| Processing sequence, job lifecycle, data transformations | `docs/data-flow.md` |
| Installation, env vars, commands, local development | `docs/setup-and-development.md` |
| Project-wide instructions, constraints, known limitations | this file |

- Don't update docs for trivial internal changes that don't affect documented behaviour.
- Don't copy detailed explanations from `docs/` into this file.
- Don't document planned features as existing.
- Don't fill gaps with assumptions.
- List the doc files you changed in your final summary.
