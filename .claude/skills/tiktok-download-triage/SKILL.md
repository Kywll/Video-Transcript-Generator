---
name: tiktok-download-triage
description: Diagnose TikTok download failures layer by layer (URL resolution, yt-dlp, RapidAPI) with scripts/tiktok_triage.py before changing any code. Use when /transcribe-url or TikTok downloads fail, yt-dlp raises extraction errors, the RapidAPI downloader errors or returns unexpected data, the TikTok description is missing, or when asked to update yt-dlp or the TikTok downloader.
---

# tiktok-download-triage

Diagnose first, then make the smallest fix. Don't edit `backend/services/download_service.py` until a specific layer has been shown to fail. How the integration works (endpoints, fallback order, return tuple) is in [docs/api-integrations.md](../../../docs/api-integrations.md#rapidapi-tiktok-video-downloader); don't re-derive it.

## Constraints (keep unless the investigation proves they must change, then ask)

- `download_tiktok` keeps returning the 4-tuple `(path, export_available, tiktok_metadata, method)`.
- Fallback order stays the same: RapidAPI (only with a user key), then yt-dlp metadata, then yt-dlp download, then `trim_video`.
- Outdated extraction → upgrade yt-dlp before touching app logic.
- **Never switch API providers without the user's approval.**
- Never print, log or commit API keys. Pass them by env var name (`--rapidapi-key-env`), never on the command line.
- If integration behaviour changes, update `docs/api-integrations.md` (and CLAUDE.md if a summary line changes).

## Sequence

1. **Read the implementation**: `download_tiktok`, `resolve_tiktok_url` and `clean_url` in `backend/services/download_service.py`, and the `/transcribe-url` handler in `backend/routes/transcription_routes.py`. Note anything that changed since the docs were written.
2. **Get a known public test URL.** Ask the user for one. If they have none, use a URL from yt-dlp's own TikTok test cases:
   ```bash
   <venv python> -c "import re,inspect,yt_dlp.extractor.tiktok as t; print(re.findall(r\"'url': '(https://www\.tiktok\.com/@[^']+/video/\d+)'\", inspect.getsource(t.TikTokIE))[:3])"
   ```
   If the failure came from a specific user URL, test that URL as well, without saving the downloaded media.
3. **Run the triage script** with the backend interpreter. Steps 2–5 of the diagnosis are in the script: resolution with the app's own functions, yt-dlp version vs. PyPI plus extraction, RapidAPI exactly as the app builds it (structure only), and an optional real download.
   ```bash
   <venv python> scripts/tiktok_triage.py --url <url>                       # env + resolve + yt-dlp
   <venv python> scripts/tiktok_triage.py --url <url> --download            # + real download to a temp dir, ffprobe
   <venv python> scripts/tiktok_triage.py --url <url> --rapidapi-key-env RAPIDAPI_KEY   # + RapidAPI
   <venv python> scripts/tiktok_triage.py --url <url> --step rapidapi ...   # one layer only
   ```
   Only test RapidAPI if the user gives you the env var name holding their key.
4. **Name the failing layer** from the Verdict section (`url`, `network`, `extractor`, `content`, RapidAPI HTTP status / structure). If every layer passes in isolation, the problem is in the app path. Run `scripts/smoke_test.py --tiktok-url <url>` (see the `smoke-test` skill) to reproduce through the real endpoint.
5. **Recommend the smallest fix**, and wait for the user's approval before editing:

| Finding | Smallest fix |
|---|---|
| `network`: "IP address is blocked" | No code change. TikTok blocks that IP, and datacenter IPs such as Render's are often blocked. Results from this machine are inconclusive; re-test elsewhere. RapidAPI is the existing mitigation. |
| `extractor` + yt-dlp outdated | Upgrade yt-dlp locally and re-run. For deploys, the Dockerfile's `pip install -U yt-dlp` layer is cached by Docker until an earlier layer changes. Rebuild without cache or touch `requirements.txt` (UTF-16 file: keep the encoding). |
| `extractor` on latest yt-dlp | Wait for or track a yt-dlp fix. Don't write a custom scraper. |
| `url` / `content` | Bad, expired, private or removed post. Fix the input. |
| RapidAPI 401/403/429 | Key, subscription or quota problem on the user's side. No code change. |
| RapidAPI 2xx but `downloadUrl` missing | The provider's response format changed. Update the field mapping in the RapidAPI branch to the structure the script printed, then update docs. |
| RapidAPI provider gone | Present options to the user. Switching providers needs approval. |

After any fix, re-run the triage script and then the smoke test. Report what was tested, which layer failed, the evidence, and what changed.
