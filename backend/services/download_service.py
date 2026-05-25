import os, uuid, requests
import json
import yt_dlp

from fastapi import HTTPException

MAX_DURATION = 120

def download_tiktok(url, target_dir, rapidapi_key=None):

    if rapidapi_key and rapidapi_key.strip():

        endpoint = (
            "https://tiktok-api23.p.rapidapi.com/api/download/video"
        )

        response = requests.get(
            endpoint,
            headers={
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": "tiktok-api23.p.rapidapi.com"
            },
            params={"url": url},
            timeout=30
        )

        data = response.json()

        video_url = (
            data.get("download_url")
            or data.get("play")
        )

        if not video_url:
            raise HTTPException(
                status_code=400,
                detail="RapidAPI could not retrieve video"
            )

        filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(
            target_dir,
            filename
        )

        with requests.get(
            video_url,
            stream=True
        ) as r:

            r.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)

        return output_path

    # fallback existing yt-dlp logic

    unique_id = str(uuid.uuid4())

    output_template = (
        f"{target_dir}/{unique_id}.%(ext)s"
    )

    ydl_opts = {
        "outtmpl": output_template,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=False
        )

    duration = info.get("duration")

    if duration and duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long ({int(duration)}s)"
        )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=True
        )

        filename = ydl.prepare_filename(info)

    return filename




