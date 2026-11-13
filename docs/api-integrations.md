# External APIs and Integrations

> Based on the code as of 2026-11-13. Request and response shapes are documented **as the code uses them**, not from vendor documentation. If a provider changes its API, the code is the thing that breaks. No credentials appear in this document.

Summary:

| Integration | Purpose | Implemented in | Auth | Fallback |
|---|---|---|---|---|
| [Gladia](#gladia-speech-to-text) | Primary speech-to-text | `backend/services/gladia_service.py` | `x-gladia-key` header (user key or `GLADIA_API_KEY`) | Vosk |
| [Vosk](#vosk-offline-speech-to-text) | Offline STT | `backend/services/offline_transcription_service.py` | none (local model) | — |
| [RapidAPI TikTok Video Downloader](#rapidapi-tiktok-video-downloader) | TikTok download + description | `backend/services/download_service.py` | `x-rapidapi-key` header (user key) | yt-dlp |
| [yt-dlp](#yt-dlp) | TikTok download + metadata | `backend/services/download_service.py` | none | — |
| [TikTok URL resolution](#tiktok-url-resolution) | Expand short links | `download_service.resolve_tiktok_url` | none | original URL |
| [Supabase](#supabase) | Google OAuth + per-user key storage | `frontend/src/api/supabase.js`, `frontend/src/components/LoginButton.jsx`, `backend/database/supabase_client.py`, `backend/routes/profile_routes.py` | anon key (frontend), service-role key (backend), user JWT | — |
| [FFmpeg / ffprobe](#ffmpeg--ffprobe) | Probe, extract, trim, export | `backend/services/video_service.py`, `download_service.is_video_file` | n/a (binary) | — |
| [SlowAPI](#slowapi-rate-limiting) | Rate limiting | `backend/routes/transcription_routes.py`, `backend/main.py` | n/a | — |
| [Bootstrap CDN](#bootstrap-cdn) | UI styling | `frontend/index.html` | n/a | — |

---

## Gladia (speech-to-text)

**Purpose:** The primary transcriber. It produces word-level timestamps and handles English/Tagalog code switching.

**Where:** `transcribe_gladia(audio_path, api_key=None)` in [`backend/services/gladia_service.py`](../backend/services/gladia_service.py). It is called only from `process_video` in [`transcription_service.py`](../backend/services/transcription_service.py).

**Key selection:** In `process_video`, `key = user_api_key or GLADIA_API_KEY`. The user key comes from the `gladia_api_key` request field. `GLADIA_API_KEY` is the env var, read at module import. With no key at all, Gladia is skipped and Vosk is used.

**SDK:** None. The code uses raw `requests`. Base URL is `https://api.gladia.io`.

### Calls

| # | Method & URL | Headers | Body | Timeout | Response fields used |
|---|---|---|---|---|---|
| 1 | `POST /v2/upload/` | `x-gladia-key`, `accept: application/json` | multipart, field `audio` = `(filename, file, "audio/wav")` | 30 s | `audio_url` |
| 2 | `POST /v2/pre-recorded/` | same + `Content-Type: application/json` | JSON (below) | 30 s | `result_url` |
| 3 | `GET {result_url}` (repeated) | same | — | 10 s each | `status`, `result.transcription.utterances[].words[]` |

Transcription request body (step 2):

```json
{
  "audio_url": "<from step 1>",
  "custom_vocabulary": true,
  "custom_vocabulary_config": {
    "default_intensity": 0.5,
    "vocabulary": [
      { "value": "tiktok", "intensity": 0.5, "language": "en" },
      { "value": "<normalized>", "pronunciations": ["<variant>"], "intensity": 0.5, "language": "en" }
    ]
  },
  "translation": false,
  "custom_spelling": false,
  "language_config": { "languages": ["en", "tl"], "code_switching": true },
  "diarization": false,
  "name_consistency": false,
  "punctuation_enhanced": true,
  "sentiment_analysis": true,
  "callback": false
}
```

The vocabulary is built from `TARGET_WORDS`, followed by `PHONETIC_MAP` entries whose normalized value isn't already present. In practice every map value is already in `TARGET_WORDS`, so the `pronunciations` branch rarely adds anything.

### Response processing
Polling runs every 2 s until `status == "done"`. `status == "error"` raises an error, and so does reaching 300 s since polling started. The words are flattened as `{word, start, end}` from each utterance's `words` array (fields `word`, `start`, `end`, defaulting to `""`/`0`). Punctuation may be attached to words because `punctuation_enhanced` is on; downstream code strips `.,!?'` when indexing.

### Error handling
- Every failure raises `fastapi.HTTPException`, carrying Gladia's status code and body text where available.
- **No retries.**
- **All Gladia exceptions are caught in `process_video`, which falls back to Vosk.** Invalid keys, exhausted quota, timeouts and network errors are all invisible to the user except as lower-quality, English-only output. The fallback is only logged with `print`.

### Considerations
- The `language` request parameter is **not** passed here. Languages are fixed to `en`+`tl`.
- `sentiment_analysis: true` is requested but the result is never used. It may add cost or latency **(unverified)**.
- The total wait can exceed the frontend's 120 s poll timeout.
- To replace Gladia, keep the return contract `list[{"word": str, "start": float, "end": float}]` (seconds). `process_video`, the frontend and export all depend on it.

---

## Vosk (offline speech-to-text)

**Purpose:** A fallback that needs no API key.

**Where:** [`backend/services/offline_transcription_service.py`](../backend/services/offline_transcription_service.py). `transcribe_vosk_wrapper(audio_path)` is called by `process_video`.

**Dependencies:** `vosk` (Kaldi), `pydub` (chunking), stdlib `wave`. The model is in [`model/`](../model/) (Vosk small en-US 0.15). The Dockerfile also downloads the same model into `/app/model`.

**Behaviour:**
- `get_vosk_model()` loads lazily and is cached globally. It tries `backend/model` (computed with two `dirname` calls on the module path; the inline comment's `backend/../model` is wrong), then `/app/model`, then `./model`, and raises `FileNotFoundError` if none exist. Uvicorn runs from `backend/`, so `./model` is also `backend/model`. The model is committed at repo-root `model/`, so **only Docker's `/app/model` path works. Local runs without Gladia fail with `Vosk model not found`** (verified 2026-11-13 with `scripts/smoke_test.py`).
- `split_audio` writes 10-second WAV chunks next to the source (`<name>_chunkN.wav`). Each chunk is recognized with `KaldiRecognizer(model, framerate)` and `SetWords(True)`, reading 16000 frames at a time. Word `start`/`end` values get a `+10.0 * chunk_index` offset, and chunks are deleted afterwards.
- Output is `[{word, start, end}]`. Vosk also returns a `conf` field, which is dropped.

**Limitations:** English only. Words that straddle a 10-second boundary may be split or lost. The model is the "small" variant, so accuracy is lower.

**Python compatibility note:** `pydub` imports the stdlib `audioop` module, which was removed in Python 3.13. Use Python 3.10–3.12 (Docker uses 3.10). Otherwise this fallback will fail to import **(unverified locally)**.

---

## RapidAPI TikTok Video Downloader

**Purpose:** Downloads TikTok videos without the watermark and returns the post description. It is tried before yt-dlp.

**Where:** The first branch of `download_tiktok` in [`backend/services/download_service.py`](../backend/services/download_service.py). It runs only when a non-blank `rapidapi_key` is supplied in the `/transcribe-url` body. There is no server-side default key.

### Calls

| # | Method & URL | Headers / params | Timeout |
|---|---|---|---|
| 1 | `GET https://tiktok-video-downloader-api.p.rapidapi.com/media` | headers `x-rapidapi-key`, `x-rapidapi-host: tiktok-video-downloader-api.p.rapidapi.com`, `Content-Type: application/json`; query `videoUrl=<resolved url>` | 30 s |
| 2 | `GET <downloadUrl>` (streamed, 8 KB chunks) | `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36` | 30 s |

**Response fields used:** `downloadUrl` (required) and `description` (optional; stored in `tiktok_metadata["description"]`). The file extension comes from the `downloadUrl` path; `.mp4` is used if it's missing or longer than 5 characters.

**Result:** The file is saved as `<uuid><ext>` and trimmed to 60 s (the untrimmed original is removed). The function returns `(path, True, metadata, "rapidapi")`. `export_available` is always `True` on this path, because the video stream isn't checked.

**Error handling:** It calls `raise_for_status()` and raises if the body is empty or `downloadUrl` is missing. **Any exception is logged as a warning and falls through to yt-dlp.** There are no retries. A partially written file from step 2 is not cleaned up.

**Logging caution:** The code logs the first 10 characters of the key, the full request URL and the raw response body.

**History:** This provider has been swapped several times (`tiktok-api23` `/api/download/video` ↔ `tiktok-video-downloader-api` `/media`). Check `git log -- backend/services/download_service.py` before changing it. The legacy root `main.py` still uses `tiktok-api23`.

---

## yt-dlp

**Purpose:** The fallback TikTok downloader (or the primary one when no RapidAPI key is given), plus a metadata source.

**Where:** The second half of `download_tiktok`. The package is `yt-dlp[curl-cffi]` (`curl-cffi` enables browser impersonation). The Dockerfile runs `pip install -U yt-dlp` on every build to stay current with TikTok changes.

**Steps:**
1. **Metadata** (only if no description yet): `YoutubeDL({"quiet": True, "noplaylist": True}).extract_info(api_url, download=False)`. The description is the first of `description`, `desc` or `title`. Failures are logged and ignored.
2. **Download:** `YoutubeDL({"outtmpl": "<target_dir>/<uuid>.%(ext)s", "format": "bestvideo+bestaudio/best", "noplaylist": True}).extract_info(url, download=True)`. **Note:** this uses the raw `url` argument, not the cleaned and resolved `api_url`. If `prepare_filename` points to a file that doesn't exist (merge changed the extension), it probes `.mp4`, `.mkv` and `.webm`.
3. `is_video_file` sets `export_available` (false for audio-only results), then `trim_video` runs.

**Error handling:** Exceptions in step 2 propagate. `/transcribe-url` converts them to HTTP 500 with `detail=str(e)`. There are no retries and no explicit timeout.

**Note:** `merge_output_format` is not set, so merged output may be `.mkv`/`.webm`. The browser's `<video>` element may not play every container **(unverified)**.

---

## TikTok URL resolution

`resolve_tiktok_url(url)` cleans the URL (`clean_url` strips surrounding whitespace, backticks and quotes), then sends `HEAD` with redirects followed and a 10 s timeout. On 403/405 it retries with a streamed `GET`. It returns `response.url`, or `None` on any `RequestException`. In that case the caller uses the cleaned original. This expands `vm.tiktok.com`-style short links before they go to RapidAPI.

---

## Supabase

**Purpose:** User login (Google OAuth) and storage of each user's Gladia/RapidAPI keys.

### Frontend (`@supabase/supabase-js` ^2.106.1)
- [`frontend/src/api/supabase.js`](../frontend/src/api/supabase.js): `createClient(VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY)`.
- [`LoginButton.jsx`](../frontend/src/components/LoginButton.jsx): `supabase.auth.signInWithOAuth({ provider: "google" })`. There is no `redirectTo`, so the redirect target is whatever site URL is configured in the Supabase project **(unverified)**.
- `App.jsx`: `auth.getSession()`, `auth.onAuthStateChange(...)`, `auth.signOut()`. `session.access_token` is sent to the backend as `Authorization: Bearer <token>`.

### Backend (`supabase` Python package)
- [`database/supabase_client.py`](../backend/database/supabase_client.py): `create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)` at import. This is a **service-role** client, so it bypasses row-level security. Authorization comes entirely from the route code filtering by the verified user id.
- [`routes/profile_routes.py`](../backend/routes/profile_routes.py):

| Endpoint | Supabase calls | Request | Response |
|---|---|---|---|
| `POST /save-api-keys` | `auth.get_user(token)`; `table("profiles").upsert({id, gladia_api_key: enc, rapidapi_key: enc})` | JSON `{gladia_api_key?, rapidapi_key?}` | `{"success": true}` |
| `GET /get-api-keys` | `auth.get_user(token)`; `table("profiles").select("*").eq("id", user_id)` | — | `{gladia_api_key, rapidapi_key}` (decrypted or `null`) |
| `POST /delete-api-key` | `auth.get_user(token)`; `table("profiles").upsert({id, <key_type>: None})` | JSON `{key_type}` | `{"success": true}` |

**Table (inferred):** `profiles(id uuid = auth user id, gladia_api_key text, rapidapi_key text)`. Values are Fernet ciphertext produced by `utils/encryption.py` with `ENCRYPTION_KEY`.

**Error handling:** A missing header returns 401. Exceptions in save/get become 500 with `detail=str(e)`. `delete-api-key` has no try/except, so a bad token raises an unhandled error and returns 500.

**Considerations:**
- `save-api-keys` upserts **both** columns, and a missing field becomes `NULL`. The frontend therefore re-sends the other saved key.
- `delete-api-key` uses the client-provided `key_type` as a column name without validating it.
- Rotating `ENCRYPTION_KEY` makes every stored key undecryptable, and `get-api-keys` will then return 500.
- Request payloads (containing plaintext keys) and Supabase responses are logged at INFO level.

---

## FFmpeg / ffprobe

These are system binaries called through `subprocess.run`. The Docker image installs them with apt; for local development they must be on `PATH`.

| Function | Command (abridged) | Failure behaviour |
|---|---|---|
| `get_video_duration` | `ffprobe -v error -show_entries format=duration -of json <file>` | JSON parse failure → `HTTPException(400, "Could not read video duration")` |
| `is_video_file` / inline check in `apply_mute_edits` | `ffprobe -v error -select_streams v:0 -show_entries stream=codec_type ...` | Any error → `False` |
| `extract_audio` | `ffmpeg -y -i <video> -ar 16000 -ac 1 <out>.wav` | `check=True` → `CalledProcessError` |
| `trim_video` | `ffmpeg -y -i <in> -t 60 -c:v copy -c:a copy <dir>/trimmed_<uuid><ext>` (only if longer than 60 s) | `check=True` → `CalledProcessError` |
| `apply_mute_edits` | `ffmpeg -y -hide_banner -loglevel error -threads 2 -i <in> -af "volume=enable='between(t,s,e)':volume=0,..." [-c:v copy \| lavfi black 640x480 libx264] -c:a aac -profile:a aac_low -b:a 128k <out>` | Non-zero exit → logs stderr and raises `HTTPException(500, "Video export failed")` |

There are no explicit subprocess timeouts.

---

## SlowAPI (rate limiting)

`Limiter(key_func=get_remote_address)` is defined in `transcription_routes.py` and applied as `@limiter.limit("5/minute")` to `POST /transcribe` and `POST /transcribe-url`. Known issues:
- `backend/main.py` sets `app.state.limiter = None` but registers slowapi's `_rate_limit_exceeded_handler`, which uses `request.app.state.limiter`. In slowapi 0.1.10 that handler calls `request.app.state.limiter._inject_headers(...)` (source confirmed), so a limit breach probably returns 500 instead of 429. This hasn't been exercised at runtime.
- `get_remote_address` uses the socket peer address. Behind Render's proxy, every client may share one limit bucket **(unverified)**.

## Bootstrap CDN

`frontend/index.html` loads `bootstrap@5.3.2` CSS from `cdn.jsdelivr.net` and sets `data-bs-theme="dark"`. Bootstrap's JS bundle is not loaded, so only CSS utilities and components are available.

## Legacy: ElevenLabs

`elevenlabs` is still in `requirements.txt`, but `ElevenLabs.speech_to_text.convert(model_id="scribe_v2")` is only used in the legacy root `main.py`. The live backend replaced it with Gladia (commit `10156bf`).
