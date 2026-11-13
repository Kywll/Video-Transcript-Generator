#!/usr/bin/env python3
"""End-to-end smoke test for the backend pipeline.

Starts the real FastAPI backend from backend/ (or uses --base-url), uploads a
small synthetic speech video, and checks transcription, job polling, static
media serving, mute export, and the exported file (ffprobe + volumedetect).

Standard library only. ffmpeg/ffprobe must be on PATH. Endpoint contracts
mirror backend/routes/transcription_routes.py; see docs/data-flow.md.

Exit code: 0 if no check FAILed, 1 otherwise.

    python scripts/smoke_test.py --python venv/Scripts/python.exe
    python scripts/smoke_test.py --help
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
UPLOAD_DIR = BACKEND / "uploads"
DOWNLOAD_DIR = BACKEND / "downloads"
SETTINGS = BACKEND / "config" / "settings.py"

MUTE_OFFSET = 0.1  # apply_mute_edits shifts both bounds by -0.1 s
SPEECH_PHRASE = (
    "Hello. This is an automated smoke test. "
    "TikTok and Facebook are popular apps. One, two, three, four, five."
)
EXPECTED_WORDS = {"hello", "smoke", "test", "one", "two", "three", "four", "five"}

# (pip name, importable module names tried in order)
REQUIRED_MODULES = [
    ("fastapi", ["fastapi"]),
    ("uvicorn", ["uvicorn"]),
    ("python-multipart", ["python_multipart", "multipart"]),
    ("vosk", ["vosk"]),
    ("pydub", ["pydub"]),  # fails on 3.13+ without audioop-lts
    ("requests", ["requests"]),
    ("yt-dlp", ["yt_dlp"]),
    ("slowapi", ["slowapi"]),
    ("supabase", ["supabase"]),
    ("python-dotenv", ["dotenv"]),
    ("cryptography", ["cryptography"]),
]

PLACEHOLDER_SUPABASE = {
    "SUPABASE_URL": "https://placeholder.supabase.co",
    "SUPABASE_SERVICE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic21va2UifQ.placeholder",
}


# --------------------------------------------------------------------------- reporting

class Report:
    def __init__(self):
        self.results = []
        self.secrets = set()

    def redact(self, text):
        for s in self.secrets:
            if s and len(s) >= 6:
                text = text.replace(s, "***")
        # key-shaped values the backend itself prints or logs (e.g. generated ENCRYPTION_KEY, payloads)
        text = re.sub(r"(\w*(?:KEY|TOKEN|SECRET)\w*=)\S+", r"\1***", text, flags=re.I)
        text = re.sub(r"(['\"]\w*(?:api_key|rapidapi_key|token)['\"]\s*:\s*)['\"][^'\"]+['\"]", r"\1'***'", text)
        return text

    def add(self, status, name, detail=""):
        self.results.append((status, name, detail))
        line = f"[{status}] {name}"
        if detail:
            line += f" - {detail}"
        print(self.redact(line), flush=True)

    def section(self, title):
        print(f"\n== {title} ==", flush=True)

    def failed(self):
        return any(s == "FAIL" for s, _, _ in self.results)

    def summary(self):
        counts = {}
        for s, _, _ in self.results:
            counts[s] = counts.get(s, 0) + 1
        order = ["PASS", "FAIL", "WARN", "SKIP", "INFO"]
        print("\n== Summary ==")
        print("  ".join(f"{k}={counts.get(k, 0)}" for k in order))
        for s, name, detail in self.results:
            if s in ("FAIL", "WARN"):
                print(self.redact(f"  {s}: {name}" + (f" - {detail}" if detail else "")))
        print("RESULT:", "FAIL" if self.failed() else "PASS")


class Abort(Exception):
    """A check failed in a way that makes later checks meaningless."""


# --------------------------------------------------------------------------- helpers

def read_max_duration():
    m = re.search(r"^MAX_VIDEO_DURATION\s*=\s*(\d+)", SETTINGS.read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else 60


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ffprobe_json(path):
    r = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout)


def media_duration(info):
    return float(info.get("format", {}).get("duration", 0) or 0)


def max_volume(path, start, length):
    """Max volume in dB of an audio window, or None if it couldn't be measured."""
    r = run([
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
        "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-",
    ])
    m = re.search(r"max_volume:\s*(-?inf|-?[\d.]+) dB", r.stderr)
    if not m:
        return None
    return float("-inf") if "inf" in m.group(1) else float(m.group(1))


def parse_env_file(path):
    """Return (values, encoding_problem). Values are never printed."""
    if not path.exists():
        return {}, None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        problem = None
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-16")
            problem = "file is UTF-16; python-dotenv reads UTF-8, so the backend will not see these values"
        except UnicodeDecodeError:
            return {}, "file is not valid UTF-8 or UTF-16"
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip("'\"")
    return values, problem


def resolve_env(names):
    """Mimic backend precedence: process env > backend/.env > repo-root .env."""
    files = [("backend/.env", BACKEND / ".env"), (".env", REPO / ".env")]
    parsed = [(label, *parse_env_file(p)) for label, p in files]
    out = {}
    for name in names:
        if os.environ.get(name):
            out[name] = (os.environ[name], "process environment")
            continue
        out[name] = (None, None)
        for label, values, problem in parsed:
            if values.get(name) and not problem:
                out[name] = (values[name], label)
                break
    return out, [(label, problem) for label, _, problem in parsed if problem]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def http_json(method, url, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    status, hdrs, body = http(method, url, data, headers, timeout)
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        parsed = None
    return status, hdrs, parsed, body


def http_multipart(url, fields, file_field, file_path, content_type, timeout=120):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
         f'filename="smoke_test{Path(file_path).suffix}"\r\nContent-Type: {content_type}\r\n\r\n').encode()
        + Path(file_path).read_bytes() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    status, hdrs, body = http(
        "POST", url, b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout,
    )
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        parsed = None
    return status, parsed, body


def poll_job(base, job_id, timeout):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        status, _, data, _ = http_json("GET", f"{base}/job/{job_id}", timeout=15)
        if status == 404:
            return "missing", None, time.time() - start
        if status != 200 or not isinstance(data, dict):
            return "http_error", {"status": status}, time.time() - start
        last = data
        if data.get("status") in ("done", "failed"):
            return data["status"], data, time.time() - start
        time.sleep(2)
    return "timeout", last, time.time() - start


# --------------------------------------------------------------------------- steps

def check_tools(report):
    report.section("Tools")
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            ver = run([tool, "-version"]).stdout.splitlines()[0:1]
            report.add("PASS", f"{tool} on PATH", ver[0] if ver else path)
        else:
            report.add("FAIL", f"{tool} on PATH", "not found; the backend and this script both need it")
            ok = False
    if not ok:
        raise Abort("ffmpeg/ffprobe missing")


def check_python(report, python):
    report.section("Backend Python")
    r = run([python, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"])
    if r.returncode != 0:
        report.add("FAIL", "interpreter runs", f"{python}: {r.stderr.strip()[:200]}")
        raise Abort("backend interpreter unusable")
    version = r.stdout.strip()
    major, minor = (int(x) for x in version.split(".")[:2])
    if (major, minor) < (3, 10):
        report.add("FAIL", "Python version", f"{version} < 3.10 (utils/encryption.py uses `str | None`)")
    elif (major, minor) <= (3, 12):
        report.add("PASS", "Python version", f"{version} (Docker uses 3.10)")
    else:
        report.add("WARN", "Python version", f"{version}; Docker uses 3.10 and pydub needs audioop-lts on 3.13+")

    missing = []
    for pip_name, modules in REQUIRED_MODULES:
        code = (
            "import importlib,sys\n"
            f"mods={modules!r}\n"
            "for m in mods:\n"
            "    try:\n        importlib.import_module(m); sys.exit(0)\n"
            "    except Exception as e:\n        err=f'{type(e).__name__}: {e}'\n"
            "print(err); sys.exit(1)\n"
        )
        r = run([python, "-c", code])
        if r.returncode != 0:
            missing.append(f"{pip_name} ({r.stdout.strip()[:120]})")
    if missing:
        report.add("FAIL", "backend dependencies import", "; ".join(missing))
        raise Abort("dependencies missing")
    report.add("PASS", "backend dependencies import", f"{len(REQUIRED_MODULES)} modules")


def check_env(report, args):
    report.section("Environment variables (values never shown)")
    names = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "ENCRYPTION_KEY", "GLADIA_API_KEY"]
    resolved, problems = resolve_env(names)
    for label, problem in problems:
        report.add("FAIL", f"{label} readable", problem)
    for value, _ in resolved.values():
        if value:
            report.secrets.add(value)

    inject = {}
    for name in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        value, source = resolved[name]
        if value:
            report.add("PASS", name, f"set ({source})")
        elif args.allow_placeholder_supabase:
            inject[name] = PLACEHOLDER_SUPABASE[name]
            report.add("WARN", name, "missing; placeholder injected into the test backend only "
                                     "(profile/API-key routes will not work)")
        else:
            report.add("FAIL", name, "missing; backend/database/supabase_client.py needs it at import "
                                     "(or rerun with --allow-placeholder-supabase)")

    value, source = resolved["ENCRYPTION_KEY"]
    if value:
        report.add("PASS", "ENCRYPTION_KEY", f"set ({source})")
    else:
        report.add("WARN", "ENCRYPTION_KEY", "missing; backend will generate a throwaway key (not used by this test)")

    gladia_key = None
    gladia_source = None
    if args.gladia_key_env:
        gladia_key = os.environ.get(args.gladia_key_env)
        if gladia_key:
            report.secrets.add(gladia_key)
            gladia_source = f"sent as gladia_api_key from ${args.gladia_key_env}"
        else:
            report.add("FAIL", "--gladia-key-env", f"${args.gladia_key_env} is empty or unset")
    server_key, source = resolved["GLADIA_API_KEY"]
    if not gladia_source and server_key:
        gladia_source = f"server default GLADIA_API_KEY ({source})"
    report.add("INFO", "expected STT provider",
               f"Gladia ({gladia_source})" if gladia_source else "Vosk (no Gladia key configured)")
    if args.require_gladia and not gladia_source:
        report.add("FAIL", "--require-gladia", "no Gladia key configured")
    return inject, gladia_key, bool(gladia_source)


def synth_speech(wav_path):
    """Write a WAV of SPEECH_PHRASE using the OS text-to-speech engine. Returns engine name or None."""
    env = dict(os.environ, SMOKE_WAV=str(wav_path), SMOKE_TEXT=SPEECH_PHRASE)
    if sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = -1; "
              "$s.SetOutputToWaveFile($env:SMOKE_WAV); $s.Speak($env:SMOKE_TEXT); $s.Dispose()")
        r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env)
        return "Windows SAPI" if r.returncode == 0 and wav_path.exists() else None
    if sys.platform == "darwin" and shutil.which("say"):
        aiff = wav_path.with_suffix(".aiff")
        r = run(["say", "-o", str(aiff), SPEECH_PHRASE])
        if r.returncode == 0 and run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), str(wav_path)]).returncode == 0:
            return "macOS say"
        return None
    for engine in ("espeak-ng", "espeak"):
        if shutil.which(engine):
            r = run([engine, "-w", str(wav_path), SPEECH_PHRASE])
            if r.returncode == 0 and wav_path.exists():
                return engine
    return None


def make_sample(report, args, workdir, max_dur):
    report.section("Sample media")
    if args.video:
        path = Path(args.video).resolve()
        if not path.exists():
            report.add("FAIL", "sample video", f"{path} not found")
            raise Abort("no sample")
        report.add("INFO", "sample video", f"using provided file {path.name}")
        return path, False

    wav = workdir / "speech.wav"
    engine = synth_speech(wav)
    if not engine:
        report.add("FAIL", "synthesize speech",
                   "no text-to-speech engine found (Windows SAPI, macOS say, espeak-ng/espeak); "
                   "pass --video PATH with a short clip of clear English speech")
        raise Abort("no sample")

    out = workdir / "sample.mp4"
    audio_opts = ["-af", "apad", "-t", str(max_dur + 2)] if args.check_trim else ["-shortest"]
    for vcodec in (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:v", "mpeg4"]):
        r = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-i", str(wav),
                 *audio_opts, *vcodec, "-c:a", "aac", "-b:a", "128k", str(out)])
        if r.returncode == 0:
            break
    else:
        report.add("FAIL", "build sample video", r.stderr.strip()[:300])
        raise Abort("no sample")
    dur = media_duration(ffprobe_json(out))
    report.add("PASS", "build sample video", f"{engine} speech + test pattern, {dur:.1f}s")
    return out, True


class Backend:
    def __init__(self, python, port, extra_env, log_path):
        # UTF-8 output: on Windows, redirected stdout defaults to cp1252 and the emoji print in
        # utils/encryption.py (missing ENCRYPTION_KEY) would crash startup.
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1", **extra_env)
        self.log_path = log_path
        self.log = open(log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
             "--port", str(port), "--workers", "1"],
            cwd=str(BACKEND), env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )

    def text(self):
        self.log.flush()
        return Path(self.log_path).read_text(encoding="utf-8", errors="replace")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.log.close()


def start_backend(report, args, inject, workdir):
    report.section("Backend startup")
    port = args.port or free_port()
    backend = Backend(args.python, port, inject, workdir / "backend.log")
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + args.startup_timeout
    while time.time() < deadline:
        if backend.proc.poll() is not None:
            report.add("FAIL", "backend starts", f"process exited with code {backend.proc.returncode}")
            print_log_tail(report, backend.text())
            raise Abort("backend did not start")
        try:
            status, _, data, _ = http_json("GET", f"{base}/test", timeout=3)
            if status == 200 and data == {"message": "Hello World"}:
                report.add("PASS", "backend starts", f"uvicorn main:app from backend/ on {base}, 1 worker")
                break
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)
    else:
        report.add("FAIL", "backend starts", f"GET /test not healthy after {args.startup_timeout}s")
        print_log_tail(report, backend.text())
        backend.stop()
        raise Abort("backend did not start")

    for d in (UPLOAD_DIR, DOWNLOAD_DIR):
        report.add("PASS" if d.is_dir() else "FAIL", f"{d.relative_to(REPO)} exists")
    return backend, base


def print_log_tail(report, text, lines=40):
    tail = text.splitlines()[-lines:]
    if tail:
        print("    --- backend log (tail, secrets redacted) ---")
        for line in tail:
            print("    " + report.redact(line))


def check_contracts(report, base):
    report.section("Error contracts")
    status, _, _, _ = http_json("GET", f"{base}/job/{uuid.uuid4()}")
    report.add("PASS" if status == 404 else "FAIL", "GET /job/<unknown> -> 404", f"got {status}")
    status, _, _, _ = http_json("POST", f"{base}/export-video",
                                {"filename": f"smoke-missing-{uuid.uuid4().hex}.mp4", "mutes": []})
    report.add("PASS" if status == 404 else "FAIL", "POST /export-video missing file -> 404", f"got {status}")


def validate_transcription_result(result):
    problems = []
    for key, typ in (("audio_file", str), ("video_file", str), ("transcript", list),
                     ("word_indexes", dict), ("word_frequencies", list), ("export_available", bool)):
        if not isinstance(result.get(key), typ):
            problems.append(f"{key} missing or not {typ.__name__}")
    for i, w in enumerate(result.get("transcript") or []):
        if not (isinstance(w, dict) and isinstance(w.get("word"), str)
                and isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))
                and w["start"] <= w["end"]):
            problems.append(f"transcript[{i}] malformed: {w!r}"[:120])
            break
    if result.get("transcript") == []:
        problems.append("transcript is empty")
    return problems


def run_transcription(report, args, base, sample, gladia_key, workdir, created, max_dur, synthetic):
    report.section("Transcription (/transcribe)")
    fields = {"language": "multi"}
    if gladia_key:
        fields["gladia_api_key"] = gladia_key
    status, data, body = http_multipart(f"{base}/transcribe", fields, "file", sample, "video/mp4")
    if status != 200 or not isinstance(data, dict) or "job_id" not in data:
        report.add("FAIL", "POST /transcribe", f"HTTP {status}: {body[:300]!r}")
        raise Abort("transcribe request failed")
    report.add("PASS", "POST /transcribe", "returned job_id")

    state, job, elapsed = poll_job(base, data["job_id"], args.job_timeout)
    if state != "done":
        report.add("FAIL", "transcription job", f"state={state} after {elapsed:.0f}s; job={json.dumps(job)[:300]}")
        raise Abort("transcription job failed")
    report.add("PASS", "transcription job", f"done in {elapsed:.0f}s")

    result = job.get("result") or {}
    for key in ("video_file", "audio_file"):
        if isinstance(result.get(key), str):
            created.append(UPLOAD_DIR / result[key])
    problems = validate_transcription_result(result)
    if problems:
        report.add("FAIL", "result shape", "; ".join(problems))
        raise Abort("bad result")
    report.add("PASS", "result shape", f"{len(result['transcript'])} words, "
               f"{len(result['word_indexes'])} index keys, top={result['word_frequencies'][:3]}")
    report.add("PASS" if result["export_available"] else "FAIL", "export_available is true for a video upload")

    if synthetic:
        words = {re.sub(r"[^\w]", "", w["word"].lower()) for w in result["transcript"]}
        hits = EXPECTED_WORDS & words
        report.add("PASS" if len(hits) >= 3 else "WARN", "recognized expected words",
                   f"{len(hits)}/{len(EXPECTED_WORDS)}: {sorted(hits)}")

    # static media serving
    served = workdir / ("served_" + result["video_file"])
    status, _, body = http("GET", f"{base}/uploads/{result['video_file']}")
    if status == 200:
        served.write_bytes(body)
        report.add("PASS", "GET /uploads/<video_file>", f"{len(body)} bytes")
    else:
        report.add("FAIL", "GET /uploads/<video_file>", f"HTTP {status}")
        served = None
    status, _, _ = http("GET", f"{base}/uploads/{result['audio_file']}")
    report.add("PASS" if status == 200 else "FAIL", "GET /uploads/<audio_file>", f"HTTP {status}")

    if args.check_trim and served:
        dur = media_duration(ffprobe_json(served))
        ok = result["video_file"].startswith("trimmed_") and dur <= max_dur + 0.5
        report.add("PASS" if ok else "FAIL", f"trim to {max_dur}s",
                   f"video_file={result['video_file']}, served duration {dur:.1f}s")
    return result, served


def check_provider(report, log_text, expect_gladia, require_gladia):
    report.section("STT provider (from backend log)")
    fallback = re.search(r"Gladia failed, falling back to Vosk: (.*)", log_text)
    gladia_ok = "Gladia transcription completed!" in log_text
    vosk_loaded = "Loading Vosk model from" in log_text
    if fallback:
        status = "FAIL" if require_gladia else "WARN"
        report.add(status, "Gladia -> Vosk fallback occurred", fallback.group(1)[:200])
    elif gladia_ok:
        report.add("PASS", "provider", "Gladia")
    elif vosk_loaded:
        report.add("PASS" if not expect_gladia else "WARN", "provider",
                   "Vosk" + ("" if not expect_gladia else " (expected Gladia; no fallback line found)"))
    else:
        report.add("WARN", "provider", "could not determine from log")


def run_export(report, args, base, result, served, workdir, created):
    report.section("Export (/export-video)")
    words = result["transcript"]
    target = next((w for w in words if w["end"] - w["start"] >= 0.2 and w["start"] >= 0.3), words[0])
    mutes = [{"start": target["start"], "end": target["end"]}]
    status, _, data, body = http_json("POST", f"{base}/export-video",
                                      {"filename": result["video_file"], "mutes": mutes})
    if status != 200 or not isinstance(data, dict) or "job_id" not in data:
        report.add("FAIL", "POST /export-video", f"HTTP {status}: {body[:300]!r}")
        raise Abort("export request failed")
    out_name = data.get("output_filename")
    expected = f"edited_{result['video_file']}"
    report.add("PASS" if out_name == expected else "FAIL", "POST /export-video",
               f"output_filename={out_name} (expected {expected})")
    if out_name:
        created.append(DOWNLOAD_DIR / out_name)

    state, job, elapsed = poll_job(base, data["job_id"], args.job_timeout)
    if state != "done":
        report.add("FAIL", "export job", f"state={state} after {elapsed:.0f}s; job={json.dumps(job)[:300]}")
        raise Abort("export job failed")
    report.add("PASS", "export job", f"done in {elapsed:.0f}s")

    status, hdrs, body = http("GET", f"{base}/download-file/{out_name}")
    disposition = {k.lower(): v for k, v in hdrs.items()}.get("content-disposition", "")
    if status != 200:
        report.add("FAIL", "GET /download-file/<output>", f"HTTP {status}")
        raise Abort("download failed")
    report.add("PASS" if "attachment" in disposition else "FAIL", "GET /download-file/<output>",
               f"{len(body)} bytes, Content-Disposition: {disposition or 'missing'}")
    exported = workdir / out_name
    exported.write_bytes(body)

    report.section("Exported file (ffprobe)")
    try:
        info = ffprobe_json(exported)
    except (RuntimeError, ValueError) as e:
        report.add("FAIL", "ffprobe exported file", str(e))
        raise Abort("invalid export")
    streams = info.get("streams", [])
    vids = [s for s in streams if s.get("codec_type") == "video"]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    report.add("PASS" if vids else "FAIL", "has video stream", vids[0].get("codec_name", "") if vids else "none")
    report.add("PASS" if auds and auds[0].get("codec_name") == "aac" else "FAIL", "audio stream is AAC",
               auds[0].get("codec_name", "") if auds else "none")
    if served:
        src_dur, out_dur = media_duration(ffprobe_json(served)), media_duration(info)
        report.add("PASS" if abs(src_dur - out_dur) <= 0.5 else "FAIL", "duration matches source",
                   f"source {src_dur:.2f}s, export {out_dur:.2f}s")

    a = max(0.0, target["start"] - MUTE_OFFSET) + 0.03
    b = max(0.0, target["end"] - MUTE_OFFSET) - 0.03
    if b - a < 0.05:
        report.add("WARN", "muted window is silent", f"word '{target['word']}' too short to measure")
        return
    out_vol = max_volume(exported, a, b - a)
    src_vol = max_volume(served, a, b - a) if served else None
    detail = (f"word '{target['word']}' window {a:.2f}-{b:.2f}s: export max {out_vol} dB, "
              f"source max {src_vol} dB")
    if out_vol is None:
        report.add("FAIL", "muted window is silent", "volumedetect failed; " + detail)
    elif out_vol > -50:
        report.add("FAIL", "muted window is silent", detail)
    elif src_vol is not None and src_vol < -40:
        report.add("WARN", "muted window is silent", "source is also quiet there, so mute not proven; " + detail)
    else:
        report.add("PASS", "muted window is silent", detail)


def run_tiktok(report, args, base, gladia_key, created):
    report.section("TikTok URL (/transcribe-url)")
    payload = {"url": args.tiktok_url, "language": "multi"}
    if gladia_key:
        payload["gladia_api_key"] = gladia_key
    if args.rapidapi_key_env:
        key = os.environ.get(args.rapidapi_key_env)
        if not key:
            report.add("FAIL", "--rapidapi-key-env", f"${args.rapidapi_key_env} is empty or unset")
            return
        report.secrets.add(key)
        payload["rapidapi_key"] = key
    status, _, data, body = http_json("POST", f"{base}/transcribe-url", payload, timeout=180)
    if status != 200 or not isinstance(data, dict) or "job_id" not in data:
        report.add("FAIL", "POST /transcribe-url", f"HTTP {status}: {report.redact(body[:300].decode('utf-8', 'replace'))}")
        return
    report.add("PASS", "POST /transcribe-url", "download finished, job queued")
    state, job, elapsed = poll_job(base, data["job_id"], args.job_timeout)
    result = (job or {}).get("result") or {}
    for key in ("video_file", "audio_file"):
        if isinstance(result.get(key), str):
            created.append(UPLOAD_DIR / result[key])
    if state != "done":
        report.add("FAIL", "URL transcription job", f"state={state}; job={json.dumps(job)[:300]}")
        return
    problems = validate_transcription_result(result)
    report.add("FAIL" if problems else "PASS", "URL result shape", "; ".join(problems) or
               f"{len(result['transcript'])} words, export_available={result['export_available']}")
    report.add("PASS" if isinstance(result.get("tiktok_metadata"), dict) else "FAIL",
               "tiktok_metadata present", f"description length {len((result.get('tiktok_metadata') or {}).get('description') or '')}")


def scan_log(report, log_text, tiktok_requested):
    report.section("Backend log scan")
    if tiktok_requested:
        if "RapidAPI download succeeded" in log_text:
            report.add("INFO", "TikTok download method", "RapidAPI")
        elif "RapidAPI download failed" in log_text:
            m = re.search(r"RapidAPI download failed: (.*)", log_text)
            report.add("WARN", "RapidAPI failed, used yt-dlp", (m.group(1) if m else "")[:200])
        else:
            report.add("INFO", "TikTok download method", "yt-dlp")
    issues = []
    for pattern in (r"Traceback \(most recent call last\)", r"\[JOB ERROR\].*", r"FFmpeg export failed.*",
                    r"ERROR:.*"):
        issues += re.findall(pattern, log_text)
    # Gladia errors that ended in the Vosk fallback are already reported by check_provider
    if "Gladia failed, falling back to Vosk" in log_text:
        issues = [i for i in issues if "gladia_service" not in i]
    if issues:
        report.add("FAIL", "no errors in backend log", f"{len(issues)} found; first: {issues[0][:200]}")
    else:
        report.add("PASS", "no errors in backend log")


def snapshot_media():
    return {p for d in (UPLOAD_DIR, DOWNLOAD_DIR) if d.is_dir() for p in d.iterdir()}


def cleanup(report, created, before, started_at, keep):
    """Remove files this run produced: names from job results, plus files that appeared in
    uploads/ or downloads/ during the run (failed jobs leave videos, WAVs and Vosk chunks
    behind, and the backend's own delete_later timers die with the process)."""
    report.section("Cleanup")
    new = {p for p in snapshot_media() - before if p.is_file() and p.stat().st_mtime >= started_at - 1}
    targets = sorted(set(p for p in created if p.is_file()) | new)
    if keep:
        report.add("INFO", "test files kept", ", ".join(p.name for p in targets) or "none")
        return
    removed = []
    for p in targets:
        if p.parent in (UPLOAD_DIR, DOWNLOAD_DIR):
            p.unlink()
            removed.append(p.name)
    report.add("INFO", "removed test files", f"{len(removed)} file(s)")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter with backend deps installed (default: this one)")
    ap.add_argument("--base-url", help="test an already-running backend instead of starting one "
                                       "(skips interpreter/env/log checks and cleanup)")
    ap.add_argument("--port", type=int, help="port for the test backend (default: free port)")
    ap.add_argument("--video", help="use this video instead of a synthesized speech sample")
    ap.add_argument("--check-trim", action="store_true", help="make the sample longer than MAX_VIDEO_DURATION")
    ap.add_argument("--gladia-key-env", metavar="VAR", help="send $VAR as gladia_api_key")
    ap.add_argument("--require-gladia", action="store_true", help="FAIL (not WARN) on Gladia->Vosk fallback")
    ap.add_argument("--tiktok-url", help="also test /transcribe-url with this public TikTok URL")
    ap.add_argument("--rapidapi-key-env", metavar="VAR", help="send $VAR as rapidapi_key with --tiktok-url")
    ap.add_argument("--allow-placeholder-supabase", action="store_true",
                    help="inject placeholder SUPABASE_* into the test backend if unset")
    ap.add_argument("--startup-timeout", type=int, default=90)
    ap.add_argument("--job-timeout", type=int, default=360, help="seconds per job (Gladia polls up to 300s)")
    ap.add_argument("--preflight-only", action="store_true", help="only check tools, Python, deps, env")
    ap.add_argument("--keep-files", action="store_true", help="keep files created in backend/uploads|downloads")
    ap.add_argument("--keep-log", action="store_true", help="keep the backend log (may contain secrets)")
    args = ap.parse_args()

    # backend log lines contain emoji; don't crash on legacy Windows console encodings
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    report = Report()
    workdir = Path(tempfile.mkdtemp(prefix="vtg-smoke-"))
    backend = None
    created = []
    media_before = snapshot_media()
    started_at = time.time()
    max_dur = read_max_duration()
    log_text = ""
    try:
        check_tools(report)
        inject, gladia_key, expect_gladia = {}, None, False
        if args.base_url:
            report.section("Backend Python / environment")
            report.add("SKIP", "interpreter, dependency and env checks", "--base-url given; server config unknown")
            if args.gladia_key_env:
                gladia_key = os.environ.get(args.gladia_key_env)
                if gladia_key:
                    report.secrets.add(gladia_key)
                expect_gladia = bool(gladia_key)
        else:
            check_python(report, args.python)
            inject, gladia_key, expect_gladia = check_env(report, args)
            if report.failed():
                raise Abort("preflight failed")
        if args.preflight_only:
            raise Abort("--preflight-only")

        sample, synthetic = make_sample(report, args, workdir, max_dur)
        if args.base_url:
            base = args.base_url.rstrip("/")
            status, _, data, _ = http_json("GET", f"{base}/test", timeout=10)
            report.section("Backend")
            report.add("PASS" if status == 200 else "FAIL", "GET /test", f"HTTP {status}")
            if status != 200:
                raise Abort("backend unreachable")
        else:
            backend, base = start_backend(report, args, inject, workdir)

        check_contracts(report, base)
        result, served = run_transcription(report, args, base, sample, gladia_key, workdir,
                                           created, max_dur, synthetic)
        if backend:
            check_provider(report, backend.text(), expect_gladia, args.require_gladia)
        else:
            report.section("STT provider")
            report.add("SKIP", "provider / fallback detection", "needs the backend log; not available with --base-url")
        run_export(report, args, base, result, served, workdir, created)
        if args.tiktok_url:
            run_tiktok(report, args, base, gladia_key, created)
        else:
            report.section("TikTok URL (/transcribe-url)")
            report.add("SKIP", "/transcribe-url", "not requested (use --tiktok-url; see tiktok-download-triage)")
    except Abort as e:
        report.add("INFO", "stopped", str(e))
    except KeyboardInterrupt:
        report.add("FAIL", "interrupted")
    finally:
        if backend:
            log_text = backend.text()
            scan_log(report, log_text, bool(args.tiktok_url))
            if report.failed():
                print_log_tail(report, log_text)
            backend.stop()
        if args.base_url:
            report.add("SKIP", "cleanup", "--base-url: files live on the server")
        else:
            cleanup(report, created, media_before, started_at, args.keep_files)
    return finish(report, workdir, args, backend)


def finish(report, workdir, args, backend):
    if args.keep_log and backend:
        print(f"\nBackend log kept at {workdir / 'backend.log'} (may contain secrets)")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    report.summary()
    return 1 if report.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
