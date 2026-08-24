import shutil, os, subprocess
import json
import uuid
import logging

from fastapi import HTTPException
from config.settings import MAX_VIDEO_DURATION

logger = logging.getLogger(__name__)

MAX_DURATION = MAX_VIDEO_DURATION


def trim_video(input_path, output_dir, max_duration=MAX_VIDEO_DURATION):
    """Trim a video to max_duration seconds (from start) if it's longer"""
    duration = get_video_duration(input_path)
    if duration <= max_duration:
        return input_path
    
    ext = os.path.splitext(input_path)[1]
    output_filename = f"trimmed_{uuid.uuid4()}{ext}"
    output_path = os.path.join(output_dir, output_filename)
    
    command = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-t", str(max_duration),
        "-c:v", "copy",
        "-c:a", "copy",
        output_path
    ]
    
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True
    )
    
    return output_path

def get_video_duration(video_path):
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except:
        raise HTTPException(
            status_code=400,
            detail="Could not read video duration"
        )

def extract_audio(video_path, output_path):
    command = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    
    subprocess.run(
        command, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        check = True
        )

def apply_mute_edits(input_path, output_path, mutes):
    if not mutes:
        shutil.copy(input_path, output_path)
        return

    check_video_cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path
    ]
    check_result = subprocess.run(check_video_cmd, capture_output=True, text=True)
    has_video = len(check_result.stdout.strip()) > 0

    filter_parts = []
    for m in mutes:
        s = max(0, m['start'] - 0.1)
        e = max(0, m['end'] - 0.1)
        filter_parts.append(f"volume=enable='between(t,{s},{e})':volume=0")

    audio_filter = ",".join(filter_parts)

    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-threads", "2",
        "-i", input_path,
        "-af", audio_filter
    ]
    if has_video:
        command.extend(["-c:v", "copy"])
    else:
        command.extend([
            "-f", "lavfi",
            "-i", "color=c=black:s=640x480:r=30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-shortest"
        ])
    command.extend(["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", output_path])

    with open(os.devnull, "wb") as devnull:
        result = subprocess.run(
            command,
            stdout=devnull,
            stderr=subprocess.PIPE
        )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "ignore")
        logger.error("FFmpeg export failed: %s", err)
        raise HTTPException(status_code=500, detail="Video export failed")
