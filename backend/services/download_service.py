import os, uuid, requests
import json
import yt_dlp
import logging
from urllib.parse import urlparse

from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_DURATION = 120

def download_tiktok(url, target_dir, rapidapi_key=None):

    if rapidapi_key and rapidapi_key.strip():
        try:
            logger.info("Attempting RapidAPI download...")
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
            logger.info(f"RapidAPI response status: {response.status_code}")
            logger.info(f"RapidAPI response: {response.text}")

            if not response.ok:
                raise Exception(f"RapidAPI request failed with status {response.status_code}")

            data = response.json()

            video_url = (
                data.get("download_url")
                or data.get("play")
            )

            if not video_url:
                raise Exception("RapidAPI response missing download_url or play")

            # Get file extension from video URL
            parsed_url = urlparse(video_url)
            path = parsed_url.path
            ext = os.path.splitext(path)[1]
            if not ext or len(ext) > 5:
                ext = ".mp4"  # Fallback to mp4 if no valid extension
            filename = f"{uuid.uuid4()}{ext}"
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
            logger.info(f"RapidAPI download succeeded: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"RapidAPI download failed: {e}, falling back to yt-dlp")

    # fallback existing yt-dlp logic

    unique_id = str(uuid.uuid4())

    output_template = (
        f"{target_dir}/{unique_id}.%(ext)s"
    )

    ydl_opts = {
        "outtmpl": output_template,
        # Force video stream: must have at least one video track
        "format": "bestvideo+bestaudio/best[ext=mp4]/best",
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
        # Ensure the file has a video extension
        ext = os.path.splitext(filename)[1].lower()
        video_exts = ['.mp4', '.mkv', '.webm', '.mov']
        if ext not in video_exts:
            # If not, raise an error and try again? Or just return it and let apply_mute_edits handle it
            logger.warning(f"Downloaded file {filename} is not a video, but proceeding anyway")

    return filename




