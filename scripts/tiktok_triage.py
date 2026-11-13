#!/usr/bin/env python3
"""Layer-by-layer diagnosis of TikTok download failures. Read-only: changes no app code.

Tests each layer used by backend/services/download_service.py::download_tiktok in isolation:
  env      yt-dlp version vs. PyPI latest, curl_cffi availability
  resolve  the app's clean_url + resolve_tiktok_url
  ytdlp    yt-dlp metadata extraction (and optionally a real download + ffprobe)
  rapidapi the RapidAPI request exactly as the app builds it (endpoint parsed from the app source);
           prints response *structure* only, never the key or full signed URLs

Run with the backend's interpreter (needs yt-dlp, requests, fastapi installed):
    python scripts/tiktok_triage.py --url <public TikTok video URL>
    python scripts/tiktok_triage.py --url <url> --rapidapi-key-env RAPIDAPI_KEY --download
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
DOWNLOAD_SERVICE = BACKEND / "services" / "download_service.py"

results = []
secrets = set()
ytdlp_errors = []

# yt-dlp error text -> (layer, meaning, smallest fix). First match wins.
YTDLP_ERROR_CLASSES = [
    (r"IP address is blocked|blocked from accessing", "network",
     "TikTok blocks this machine's IP (common for datacenter IPs such as Render). Not a code or yt-dlp bug; "
     "re-test from another network. The RapidAPI path is the existing mitigation."),
    (r"Unsupported URL", "url",
     "yt-dlp does not see a TikTok video URL. Usually an invalid/expired short link that resolved to the "
     "homepage (check the resolve step) or a non-video page. Fix the input, not the code."),
    (r"Unable to extract|unable to find|KeyError|JSONDecodeError", "extractor",
     "yt-dlp's TikTok extractor no longer matches TikTok. Upgrade yt-dlp; if already latest, wait for a yt-dlp fix."),
    (r"private|log ?in|sign ?in|comfortable for some audiences|age", "content",
     "The post is private, age/login-restricted, or sensitive. Use a different public URL; no code change."),
    (r"404|not available|removed|does not exist|deleted", "content",
     "The post is unavailable or removed. Use a different public URL; no code change."),
    (r"timed out|Connection|Temporary failure|getaddrinfo|SSL", "network",
     "Network/DNS/TLS problem reaching TikTok. Check connectivity before anything else."),
]


def classify(message):
    for pattern, layer, advice in YTDLP_ERROR_CLASSES:
        if re.search(pattern, message, re.I):
            return layer, advice
    return "unknown", "Unclassified yt-dlp error; read the message and check yt-dlp's issue tracker."


class _QuietLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def redact(text):
    text = str(text)
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "***")
    return text


def add(status, name, detail=""):
    results.append((status, name, detail))
    print(redact(f"[{status}] {name}" + (f" - {detail}" if detail else "")), flush=True)


def section(title):
    print(f"\n== {title} ==", flush=True)


def describe(value, depth=0):
    """Structure of a JSON value: key names and types, no contents."""
    if isinstance(value, dict):
        if depth >= 2:
            return f"object({len(value)} keys)"
        return {k: describe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return f"list[{len(value)}]" + (f" of {describe(value[0], depth + 1)}" if value else "")
    if isinstance(value, str):
        return f"str({len(value)})"
    return type(value).__name__


def step_env():
    section("Environment")
    add("INFO", "Python", sys.version.split()[0])
    try:
        import yt_dlp
        installed = yt_dlp.version.__version__
    except Exception as e:
        add("FAIL", "yt-dlp importable", f"{type(e).__name__}: {e}")
        return None
    latest = None
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as r:
            latest = json.load(r)["info"]["version"]
    except Exception as e:
        add("WARN", "yt-dlp latest version", f"could not query PyPI: {e}")
    if latest:
        norm = lambda v: tuple(int(x) for x in re.findall(r"\d+", v))
        status = "PASS" if norm(installed) >= norm(latest) else "WARN"
        add(status, "yt-dlp version", f"installed {installed}, latest {latest}"
            + ("" if status == "PASS" else " -> upgrade before changing app code"))
    else:
        add("INFO", "yt-dlp version", installed)
    try:
        import curl_cffi  # noqa: F401  (requirements.txt asks for yt-dlp[curl-cffi])
        add("PASS", "curl_cffi installed", "yt-dlp browser impersonation available")
    except Exception:
        add("WARN", "curl_cffi installed", "missing; requirements.txt expects yt-dlp[curl-cffi]")
    return installed


def step_resolve(url):
    section("URL resolution (app's clean_url + resolve_tiktok_url)")
    from services.download_service import clean_url, resolve_tiktok_url
    cleaned = clean_url(url)
    if cleaned != url:
        add("INFO", "clean_url changed input", f"{url!r} -> {cleaned!r}")
    resolved = resolve_tiktok_url(cleaned)
    if resolved is None:
        add("WARN", "resolve_tiktok_url", "returned None (request failed); app falls back to the cleaned URL")
        return cleaned, cleaned
    host = urlparse(resolved).netloc
    looks_video = "/video/" in resolved
    add("PASS" if looks_video else "WARN", "resolve_tiktok_url",
        f"{resolved.split('?')[0]} (host {host})" + ("" if looks_video else "; no /video/ in final URL"))
    return cleaned, resolved


def step_ytdlp(raw_url, api_url, download):
    section("yt-dlp")
    import yt_dlp
    ok = False
    # metadata exactly as download_tiktok does (uses the resolved api_url)
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "no_warnings": True,
                               "logger": _QuietLogger()}) as ydl:
            info = ydl.extract_info(api_url, download=False)
        formats = info.get("formats") or []
        video_formats = [f for f in formats if f.get("vcodec") not in (None, "none")]
        desc = info.get("description") or info.get("desc") or info.get("title") or ""
        add("PASS", "metadata extraction",
            f"extractor={info.get('extractor_key')}, id={info.get('id')}, duration={info.get('duration')}, "
            f"formats={len(formats)} ({len(video_formats)} with video), description length {len(desc)}")
        if not video_formats:
            add("WARN", "video formats", "none; app would mark export_available=False")
        ok = True
    except Exception as e:
        ytdlp_errors.append(str(e))
        add("FAIL", "metadata extraction", f"{type(e).__name__}: {str(e)[:300]}")

    if raw_url != api_url:
        add("INFO", "note", "download_tiktok downloads with the raw input URL, not the resolved one")
    if not download:
        add("SKIP", "real download", "not requested (--download)")
        return ok
    tmp = Path(tempfile.mkdtemp(prefix="vtg-triage-"))
    try:
        opts = {"outtmpl": f"{tmp}/%(id)s.%(ext)s", "format": "bestvideo+bestaudio/best",
                "noplaylist": True, "quiet": True, "no_warnings": True,
                "logger": _QuietLogger()}  # same format/noplaylist as the app
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(raw_url, download=True)
        files = [p for p in tmp.iterdir() if p.is_file()]
        if not files:
            add("FAIL", "real download", "yt-dlp reported success but wrote no file")
            return False
        f = files[0]
        streams = probe_streams(f)
        add("PASS" if "video" in streams else "WARN", "real download",
            f"{f.suffix}, {f.stat().st_size} bytes, streams={streams}")
        return ok
    except Exception as e:
        ytdlp_errors.append(str(e))
        add("FAIL", "real download", f"{type(e).__name__}: {str(e)[:300]}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probe_streams(path):
    if not shutil.which("ffprobe"):
        return "ffprobe not on PATH"
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                        "-of", "json", str(path)], capture_output=True, text=True)
    try:
        return {s["codec_type"]: s.get("codec_name") for s in json.loads(r.stdout)["streams"]}
    except Exception:
        return f"ffprobe failed: {r.stderr.strip()[:120]}"


def app_rapidapi_contract():
    """Read the endpoint, host and query param the app uses, so this test cannot drift silently."""
    src = DOWNLOAD_SERVICE.read_text(encoding="utf-8")
    endpoint = re.search(r'endpoint\s*=\s*"(https://[^"]+)"', src)
    host = re.search(r'"x-rapidapi-host"\s*:\s*"([^"]+)"', src)
    param = re.search(r'querystring\s*=\s*\{\s*"(\w+)"', src)
    field = re.search(r'data\.get\("(\w+)"\)\s*\n\s*if not video_url', src)
    if not (endpoint and host and param):
        return None
    return endpoint.group(1), host.group(1), param.group(1), field.group(1) if field else "downloadUrl"


def step_rapidapi(api_url, key_env, download):
    section("RapidAPI (as built by download_tiktok)")
    if not key_env:
        add("SKIP", "RapidAPI", "no --rapidapi-key-env given (app only uses RapidAPI when the user supplies a key)")
        return None
    key = os.environ.get(key_env)
    if not key:
        add("FAIL", "RapidAPI key", f"${key_env} is empty or unset")
        return False
    secrets.add(key)
    contract = app_rapidapi_contract()
    if not contract:
        add("FAIL", "read app contract", "could not parse endpoint/host/param from download_service.py; "
                                         "update this script to match the app")
        return False
    endpoint, host, param, field = contract
    add("INFO", "app contract", f"GET {endpoint} ?{param}=<url>, host header {host}, video field '{field}'")

    import requests
    try:
        r = requests.get(endpoint, params={param: api_url}, timeout=30, headers={
            "x-rapidapi-key": key, "x-rapidapi-host": host, "Content-Type": "application/json"})
    except Exception as e:
        add("FAIL", "RapidAPI request", f"{type(e).__name__}: {str(e)[:200]}")
        return False
    hints = {401: "key invalid", 403: "not subscribed to this API / key not allowed",
             429: "quota or rate limit exhausted", 404: "endpoint path changed or video not found"}
    detail = f"HTTP {r.status_code}, {r.headers.get('content-type', '?')}, {len(r.content)} bytes"
    if r.status_code >= 400:
        add("FAIL", "RapidAPI request", detail + (f" ({hints[r.status_code]})" if r.status_code in hints else ""))
    else:
        add("PASS", "RapidAPI request", detail)
    try:
        data = r.json()
    except ValueError:
        add("FAIL", "response is JSON", f"body starts {r.text[:80]!r}" if r.text.strip() else "empty body")
        return False
    print("    response structure:", redact(json.dumps(describe(data), indent=2)).replace("\n", "\n    "))
    if r.status_code >= 400:
        return False
    video_url = data.get(field) if isinstance(data, dict) else None
    if not video_url:
        add("FAIL", f"response has '{field}'", "missing; provider response format changed (see structure above)")
        return False
    add("PASS", f"response has '{field}'", f"host {urlparse(video_url).netloc}")
    add("PASS" if isinstance(data, dict) and data.get("description") else "WARN", "response has 'description'")
    if download:
        try:
            with requests.get(video_url, stream=True, timeout=30, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as v:
                first = next(v.iter_content(65536), b"")
                add("PASS" if v.ok and first else "FAIL", f"fetch '{field}'",
                    f"HTTP {v.status_code}, {v.headers.get('content-type', '?')}, first chunk {len(first)} bytes")
        except Exception as e:
            add("FAIL", f"fetch '{field}'", f"{type(e).__name__}: {str(e)[:200]}")
    return True


def verdict(env_ok_version, ytdlp_ok, rapid_ok):
    section("Verdict")
    outdated = any(s == "WARN" and n == "yt-dlp version" for s, n, _ in results)
    if ytdlp_ok is False:
        layer, advice = classify(" ".join(ytdlp_errors))
        print(f"  yt-dlp fails: failing layer = {layer}. {advice}")
        if outdated and layer in ("extractor", "unknown"):
            print("  yt-dlp is also outdated -> upgrade it first (pip install -U yt-dlp), then re-run this script.")
    elif ytdlp_ok:
        print("  yt-dlp works for this URL.")
    if rapid_ok is False:
        print("  RapidAPI layer fails -> see status/structure above. Key/quota problems need no code change; "
              "a changed response field is a mapping fix in download_service.py; a dead provider needs approval to switch.")
    elif rapid_ok:
        print("  RapidAPI works for this URL.")
    elif rapid_ok is None:
        print("  RapidAPI not tested.")
    if ytdlp_ok and rapid_ok is not False:
        print("  Download layers work in isolation -> look at the app path instead (trim_video, is_video_file, "
              "/transcribe-url handling) or run scripts/smoke_test.py --tiktok-url <url>.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="a known public TikTok video URL")
    ap.add_argument("--step", choices=["all", "env", "resolve", "ytdlp", "rapidapi"], default="all")
    ap.add_argument("--rapidapi-key-env", metavar="VAR", help="name of env var holding the RapidAPI key")
    ap.add_argument("--download", action="store_true", help="also perform real downloads (temp dir, deleted)")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    sys.path.insert(0, str(BACKEND))
    logging.basicConfig(level=logging.WARNING)  # app logs would include raw responses
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.dont_write_bytecode = True

    version = ytdlp_ok = rapid_ok = None
    raw_url, api_url = args.url, args.url
    if args.step in ("all", "env"):
        version = step_env()
    if args.step in ("all", "resolve", "ytdlp", "rapidapi"):
        _, api_url = step_resolve(args.url)  # raw_url stays the uncleaned input, as in download_tiktok
    if args.step in ("all", "ytdlp"):
        ytdlp_ok = step_ytdlp(raw_url, api_url, args.download)
    if args.step in ("all", "rapidapi"):
        rapid_ok = step_rapidapi(api_url, args.rapidapi_key_env, args.download)
    verdict(version, ytdlp_ok, rapid_ok)
    return 1 if any(s == "FAIL" for s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
