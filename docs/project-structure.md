# Project Structure

> Based on the code as of 2026-11-13. Generated and ignored directories (`node_modules/`, `uploads/`, `downloads/`, `venv/`) are not shown.

```
Video-Transcript-Generator/
├── Dockerfile                  # Backend image (python:3.10-slim + ffmpeg + Vosk model), runs backend/main.py
├── requirements.txt            # Backend Python deps (UTF-16 LE encoded, unpinned)
├── .gitignore                  # Secrets, venvs, caches, build output, runtime media, OS/IDE clutter (UTF-8)
├── .dockerignore
├── README.md                   # Partly outdated project overview
├── CLAUDE.md                   # Condensed guide for Claude Code sessions
├── main.py                     # LEGACY single-file backend (not deployed)
├── templates/index.html        # LEGACY Jinja UI (not served)
├── static/index.css            # LEGACY CSS for the Jinja UI
├── model/                      # Vosk small English model (offline STT fallback)
├── docs/                       # This documentation
├── scripts/
│   ├── smoke_test.py           # End-to-end backend pipeline check (stdlib only)
│   └── tiktok_triage.py        # Layer-by-layer TikTok download diagnosis
├── .claude/skills/             # Claude Code skills: smoke-test, tiktok-download-triage, git-workflow
├── backend/
│   ├── main.py                 # FastAPI app: CORS, static mounts, routers
│   ├── job_queue.py            # In-memory queue, worker threads, result store
│   ├── config/settings.py      # Paths and limits
│   ├── database/supabase_client.py
│   ├── routes/
│   │   ├── transcription_routes.py
│   │   └── profile_routes.py
│   ├── services/
│   │   ├── download_service.py
│   │   ├── transcription_service.py
│   │   ├── gladia_service.py
│   │   ├── offline_transcription_service.py
│   │   └── video_service.py
│   └── utils/
│       ├── normalization.py
│       ├── encryption.py
│       └── file_utils.py
└── frontend/
    ├── index.html              # Loads Bootstrap 5.3.2 CSS from CDN, dark theme
    ├── package.json            # React 19, Vite 7, supabase-js, ESLint 9
    ├── vite.config.js          # Default React plugin only (no proxy)
    ├── eslint.config.js
    └── src/
        ├── main.jsx            # React root (StrictMode)
        ├── App.jsx             # All app state and handlers
        ├── App.css             # Unused template leftover
        ├── index.css
        ├── api/transcribe.js   # transcribeVideo, transcribeUrl, pollJob
        ├── api/supabase.js     # Supabase anon client
        └── components/
            ├── Transcript.jsx  # Word rendering, search, mute gestures
            ├── ApiKeyManager.jsx
            ├── AudioPlayer.jsx
            ├── FileUpload.jsx
            ├── InputUrl.jsx    # exports component UrlInput
            └── LoginButton.jsx
```

## Backend modules

### `backend/main.py`
App construction only. It contains no business logic. Notable details:
- CORS uses `allow_origin_regex="https://.*\.vercel\.app"` with credentials. Localhost is **not** allowed.
- `DOWNLOAD_DIR` is mounted twice (`/downloads` and `/download`), and `UPLOAD_DIR` is mounted at `/uploads`.
- `app.state.limiter = None` plus slowapi's `_rate_limit_exceeded_handler` (see architecture fragility table).
- `/test` and `/cors-debug` are diagnostic endpoints. The `TLSAdapter` class is defined but unused.

### `backend/job_queue.py`
- `JOB_QUEUE`: a `queue.Queue` of `(job_id, callable, args)` tuples.
- `JOB_RESULTS`: `dict[job_id, {"status", "result"?, "error"?}]`.
- `worker()`: runs a job, sets the status to `processing`, then `done` or `failed`. Exceptions are printed and stored as `str(e)`.
- `cleanup_jobs()`: every 1800 s it removes all `done`/`failed` jobs.
- `NUM_WORKERS = 2` is hard-coded here; `settings.NUM_WORKERS` is not used.

### `backend/config/settings.py`
| Name | Value | Used? |
|---|---|---|
| `UPLOAD_DIR`, `DOWNLOAD_DIR` | `backend/uploads`, `backend/downloads` | Yes |
| `MAX_FILE_SIZE` | 100 MB | Yes (`/transcribe`) |
| `MAX_VIDEO_DURATION` | 60 s | Yes (trimming) |
| `CLEANUP_DELAY_VIDEO`, `CLEANUP_DELAY_AUDIO` | 900 / 1800 | **No** (routes hard-code 1800) |
| `NUM_WORKERS`, `JOB_TIMEOUT` | 2 / 120000 | **No** |

### `backend/routes/transcription_routes.py`
- `create_transcription_job(video_path, video_filename, gladia_api_key, language, export_available, tiktok_metadata=None)` returns a closure that calls `process_video`, builds the result dict, and always schedules deletion of the video and WAV after 1800 s.
- `create_export_job(video_path, output_path, mutes)` returns a closure that calls `apply_mute_edits`.
- Endpoints: `GET /job/{job_id}`, `POST /transcribe-url`, `POST /transcribe`, `POST /export-video`, `GET /download-file/{filename}`. See [data-flow.md](data-flow.md) for the payloads.

### `backend/routes/profile_routes.py`
`POST /save-api-keys`, `GET /get-api-keys`, `POST /delete-api-key`. Each strips `"Bearer "` from the `Authorization` header and calls `supabase.auth.get_user(token)`, then works on `profiles` keyed by the user id. See [api-integrations.md](api-integrations.md#supabase).

### `backend/services/`
| Module | Key functions |
|---|---|
| `download_service.py` | `download_tiktok(url, target_dir, rapidapi_key=None) -> (path, export_available, tiktok_metadata, method)`; `resolve_tiktok_url`; `clean_url`; `is_video_file` |
| `transcription_service.py` | `process_video(video_path, filename, user_api_key=None, language="multi") -> (transcript, word_indexes, word_frequencies, audio_filename)` |
| `gladia_service.py` | `transcribe_gladia(audio_path, api_key=None) -> [{word, start, end}]` |
| `offline_transcription_service.py` | `get_vosk_model`, `split_audio`, `transcribe_vosk_wrapper(audio_path)`, `transcribe_vosk(wav_path)` |
| `video_service.py` | `get_video_duration`, `extract_audio`, `trim_video(input_path, output_dir, max_duration=60)`, `apply_mute_edits(input_path, output_path, mutes)` |

### `backend/utils/`
| Module | Contents |
|---|---|
| `normalization.py` | `TARGET_WORDS`, `PHONETIC_MAP`, `normalize_word(word)` |
| `encryption.py` | Module-level Fernet `cipher`; `encrypt_data`, `decrypt_data` (both pass `None` and empty values through) |
| `file_utils.py` | `delete_later(path, delay=900)`, `ensure_dir_exists(dir_path)` |

## Frontend modules

- **`App.jsx`**: the single stateful component. Handlers: `handleUpload`, `handleUrlTranscribe`, `handleRawDownload` (calls the missing `/download-raw` route), `handleExportVideo`, `jumpTo`, `toggleMute`, `loadApiKeys`, `saveApiKey`, `deleteApiKey`, `logout`. A `useEffect` mutes the media element whenever playback is inside a muted word's window.
- **`api/transcribe.js`**: `transcribeVideo(file, apiKey, language)`, `transcribeUrl(url, gladiaKey, rapidApiKey, language)`, `pollJob(jobId)`.
- **`components/Transcript.jsx`**: renders each word as a `<span>`. Highlight priority, from lowest to highest: search match (yellow), hover (light blue), muted (red), current word (orange). Click seeks; Alt+click, mute mode or a 500 ms long-press toggles mute.
- The other components are thin presentational wrappers.

## Where to make changes

| Task | Edit here |
|---|---|
| Add or adjust a recognized brand or phrase | `backend/utils/normalization.py` (affects the word index **and** the Gladia vocabulary) |
| Change STT provider logic or fallback order | `backend/services/transcription_service.py` (`process_video`) |
| Change Gladia request options or languages | `backend/services/gladia_service.py` (`data` dict) |
| Support a new URL source or downloader | `backend/services/download_service.py`. Keep the 4-tuple contract or update `transcribe_tiktok` in `transcription_routes.py` |
| Change max duration, upload size or paths | `backend/config/settings.py` |
| Change export or mute rendering | `backend/services/video_service.py` (`apply_mute_edits`) and the matching −0.1 s preview logic in `frontend/src/App.jsx` |
| Add a long-running endpoint | Route in `routes/`, closure via a `create_*_job` helper, enqueue on `JOB_QUEUE`, client polls with `pollJob` |
| Add a stored per-user setting | `profile_routes.py` plus a Supabase `profiles` column, and the `App.jsx` load/save handlers |
| Change job retention or worker count | `backend/job_queue.py` |
| CORS or allowed origins | `backend/main.py` (affects production) |
| Transcript UI behaviour | `frontend/src/components/Transcript.jsx` |
| API base URL or Supabase project | `frontend/.env` (`VITE_*` variables) |

Do **not** make feature changes in the repo-root `main.py`, `templates/` or `static/`; they are not deployed.
