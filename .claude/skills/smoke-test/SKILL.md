---
name: smoke-test
description: Validate backend changes end to end by running the real FastAPI pipeline (upload, job polling, Vosk/Gladia transcription, static media, mute export, ffprobe checks) with scripts/smoke_test.py. Use after changing anything in backend/ that touches uploads, TikTok downloads, transcription, the job queue, trimming or export; when asked to smoke test, verify the pipeline, or check the backend still works; and before committing such changes. Not needed for frontend-only or docs-only changes.
---

# smoke-test

Runs [scripts/smoke_test.py](../../../scripts/smoke_test.py). It starts its own backend from `backend/` (single worker, free port), uploads a synthesized speech video, and reports PASS / FAIL / WARN / SKIP for each check. Exit code 1 means at least one FAIL. Endpoint contracts and pipeline details are in [CLAUDE.md](../../../CLAUDE.md) and [docs/data-flow.md](../../../docs/data-flow.md); this skill only covers running and interpreting the test.

## 1. Find the environment (ask, don't guess)

- **Backend interpreter**: a Python 3.10–3.12 venv with `requirements.txt` installed. Look for `venv/` or `.venv/`. If there isn't one, ask the user which interpreter to use. Don't create venvs or install system packages (Python, ffmpeg) without asking.
- **ffmpeg/ffprobe** must be on PATH. On Windows, winget installs may not be on PATH in an already-open shell; prepend the `bin` folder for this run only.
- **Secrets**: never read `.env` files aloud or print values. The script reports only set/missing.

Quick check first:

```bash
python scripts/smoke_test.py --python <venv python> --preflight-only
```

## 2. Run

```bash
python scripts/smoke_test.py --python <venv python>
```

Add flags only for a reason:

| Flag | When |
|---|---|
| `--allow-placeholder-supabase` | No Supabase credentials locally. The pipeline doesn't use them, but the backend can't import without them. Profile routes are not tested. |
| `--check-trim` | Change touches `trim_video` or `MAX_VIDEO_DURATION` (sample becomes about 62 s) |
| `--gladia-key-env VAR` / `--require-gladia` | Change touches Gladia; turns a Gladia→Vosk fallback from WARN into FAIL |
| `--tiktok-url URL [--rapidapi-key-env VAR]` | Change touches `download_service.py` or `/transcribe-url`. Calls TikTok/RapidAPI, so get the URL from the user. On failure, switch to the `tiktok-download-triage` skill. |
| `--video PATH` | No text-to-speech engine available. Use only synthetic or user-approved non-private media. |
| `--keep-files` / `--keep-log` | Debugging only. The log can contain secrets: delete it afterwards. |

## 3. Report

- Quote the **Summary** block and exit code. List every FAIL and WARN. Never describe a SKIP or a run that stopped early as a pass.
- Read FAIL details before blaming the change. The backend log tail is printed (redacted) on failure.
- **Known current failure:** on a local (non-Docker) run without a Gladia key, transcription FAILs with `Vosk model not found ... backend\model`. `offline_transcription_service.get_vosk_model()` resolves to `backend/model`, but the model is at repo-root `model/`; only Docker's `/app/model` works. This is an existing app bug, not your change. Report it, and don't patch app code or move files to get a green run unless the user asks.
- A Gladia→Vosk fallback WARN means transcription "worked" but Gladia didn't run. Check the detail (e.g. 401 invalid key).

## 4. Keep the script in sync

If the change alters an endpoint, a request field, the job result shape, the export naming (`edited_<file>`), or the −0.1 s mute offset, update `scripts/smoke_test.py` in the same change. Also update the docs, per the Documentation Maintenance rules in CLAUDE.md.
