import os, uuid, requests
import json
import yt_dlp
import logging
import subprocess

from fastapi import HTTPException
from config.settings import MAX_VIDEO_DURATION

logger = logging.getLogger(__name__)

MAX_DURATION = MAX_VIDEO_DURATION

def is_video_file(file_path):
    try:
        check_cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        return len(result.stdout.strip()) > 0
    except:
        return False

def extract_tiktok_video_id(url):
    """Extract video ID from TikTok URL (support various formats)"""
    import re
    # Patterns like https://www.tiktok.com/@username/video/1234567890123456789, https://vm.tiktok.com/ZMabcde123/, etc.
    patterns = [
        r'/video/(\d+)',
        r'(\d{17,19})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None

def get_tiktok_post_detail(video_id, rapidapi_key):
    """Get TikTok post details using RapidAPI"""
    endpoint = "https://tiktok-api23.p.rapidapi.com/api/post/detail"
    
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "tiktok-api23.p.rapidapi.com",
        "Content-Type": "application/json"
    }
    
    querystring = {"videoId": video_id}
    
    try:
        response = requests.get(endpoint, headers=headers, params=querystring, timeout=30)
        if response.ok:
            data = response.json()
            aweme_detail = data.get("data", {}).get("aweme_detail", {})
            return {
                "description": aweme_detail.get("desc", ""),
                "play_count": aweme_detail.get("statistics", {}).get("play_count", 0),
                "digg_count": aweme_detail.get("statistics", {}).get("digg_count", 0),
                "comment_count": aweme_detail.get("statistics", {}).get("comment_count", 0),
                "share_count": aweme_detail.get("statistics", {}).get("share_count", 0)
            }
    except Exception as e:
        logger.error(f"Failed to get TikTok post detail: {str(e)}")
    return None

def download_tiktok(url, target_dir, rapidapi_key=None):
    tiktok_metadata = None
    
    if rapidapi_key and rapidapi_key.strip():
        try:
            # Try to get post detail first
            video_id = extract_tiktok_video_id(url)
            if video_id:
                tiktok_metadata = get_tiktok_post_detail(video_id, rapidapi_key)
                logger.info(f"Got TikTok metadata: {tiktok_metadata}")
            
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
            from urllib.parse import urlparse
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
            
            # Trim RapidAPI video if needed
            from services.video_service import trim_video
            trimmed_path = trim_video(output_path, target_dir)
            
            if trimmed_path != output_path and os.path.exists(output_path):
                os.remove(output_path)
                
            return trimmed_path, True, tiktok_metadata  # Return metadata too
        except Exception as e:
            logger.warning(f"RapidAPI download failed: {e}, falling back to yt-dlp")

    # fallback existing yt-dlp logic

    unique_id = str(uuid.uuid4())

    output_template = (
        f"{target_dir}/{unique_id}.%(ext)s"
    )

    ydl_opts = { 
        "outtmpl": output_template, 
        "format": "bestvideo+bestaudio/best", 
        "noplaylist": True 
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            url,
            download=True
        )

        filename = ydl.prepare_filename(info)

    # Check if yt-dlp downloaded a video file
    is_video = is_video_file(filename)
    
    # Import trim_video here to avoid circular import
    from services.video_service import trim_video
    trimmed_path = trim_video(filename, target_dir)
    
    # If trimmed, clean up the original file
    if trimmed_path != filename and os.path.exists(filename):
        os.remove(filename)
    
    return trimmed_path, is_video, tiktok_metadata
