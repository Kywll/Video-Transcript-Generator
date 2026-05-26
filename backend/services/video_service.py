import shutil, os, subprocess
import json

from fastapi import HTTPException

MAX_DURATION = 120

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
    else:
        filter_parts = []
        for m in mutes:
            s = max(0, m['start'] - 0.1)
            e = max(0, m['end'] - 0.1)
            filter_parts.append(f"volume=enable='between(t,{s},{e})':volume=0")
        
        audio_filter = ",".join(filter_parts)

        command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", audio_filter,
            "-c:v", "copy",
            "-c:a", "aac",
            output_path
        ]

        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode != 0:
            print(result.stderr)
            raise HTTPException(status_code=500, detail="Video export failed")
