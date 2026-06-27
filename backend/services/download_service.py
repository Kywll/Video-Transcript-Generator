import os, uuid, requests
import json
import yt_dlp
import logging
import subprocess
from urllib.parse import urlparse

from fastapi import HTTPException
from config.settings import MAX_VIDEO_DURATION
from services.video_service import trim_video

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

def clean_url(u):
    """Super thorough URL cleaning - remove all accidental extra characters"""
    if not u:
        return u
    u = u.strip()
    # Remove backticks, quotes, any order
    while u.startswith(('`', '"', "'", ' ')):
        u = u[1:].strip()
    while u.endswith(('`', '"', "'", ' ')):
        u = u[:-1].strip()
    return u

def resolve_tiktok_url(url):
    """
    Resolve TikTok short URLs (vt.tiktok.com, vm.tiktok.com) to their
    canonical www.tiktok.com URL.

    Returns:
        str: Resolved TikTok URL, or None if resolution fails.
    """
    url = clean_url(url)

    logger.info(f"Resolving TikTok URL: {url}")

    try:
        # HEAD is faster and usually sufficient
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=10
        )

        # Some servers return 405/403 for HEAD
        if response.status_code in (403, 405):
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                stream=True
            )
            response.close()

        final_url = response.url

        logger.info(f"Resolved TikTok URL: {url} → {final_url}")

        return final_url

    except requests.RequestException as e:
        logger.warning(
            f"Failed to resolve TikTok URL '{url}': {e}. Using original URL."
        )
        return None

def download_tiktok(url, target_dir, rapidapi_key=None):
    tiktok_metadata = {"description": ""}  # Initialize safely
    original_url = clean_url(url)
    resolved_url = resolve_tiktok_url(original_url)
    if resolved_url:
        url = resolved_url
    logger.info(f"Processing TikTok URL after thorough cleaning: {url}")
    
    # Get TikTok metadata with yt-dlp
    logger.info("Getting TikTok metadata with yt-dlp...")
    try:
        ydl_opts_meta = {
            "quiet": True,
            "noplaylist": True
        }
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(url, download=False)
            desc = (
                info.get("description") or
                info.get("desc") or
                info.get("title") or
                ""
            )
            tiktok_metadata["description"] = desc
            logger.info(f"✅ Final TikTok metadata: {tiktok_metadata}")
    except Exception as e:
        logger.warning(f"yt-dlp metadata extraction failed: {str(e)}")
    
   # RapidAPI execution route - try resolved URL first, then original URL (avoid duplicates)
    if rapidapi_key and rapidapi_key.strip():
        attempt_urls = [url]
        if original_url != url:
            attempt_urls.append(original_url)
        for attempt_url in attempt_urls:
            try:
                logger.info(f"Attempting RapidAPI download with URL: {repr(attempt_url)}")
                
                # VERIFY URL AND KEY FIRST!
                logger.info(f"RapidAPI key starts with: {repr(rapidapi_key[:10])}")
                
                # EXACT WORKING CODE FROM USER'S STANDALONE SCRIPT
                endpoint = "https://tiktok-api23.p.rapidapi.com/api/download/video"
                querystring = {"url": attempt_url}
                headers = {
                    "x-rapidapi-key": rapidapi_key,
                    "x-rapidapi-host": "tiktok-api23.p.rapidapi.com"
                }
                
                response = requests.get(
                    endpoint,
                    headers=headers,
                    params=querystring,
                    timeout=30
                )
                
                # LOG EXACT REQUEST URL
                logger.info(f"EXACT RapidAPI request URL: {response.request.url}")
                
                logger.info(f"RapidAPI response status: {response.status_code}")
                logger.info(f"RapidAPI response text (raw): {repr(response.text)}")

                response.raise_for_status()
                
                # CHECK FOR EMPTY RESPONSE BEFORE PARSING
                if not response.text.strip():
                    raise Exception("RapidAPI returned empty response")

                data = response.json()
                logger.info(f"RapidAPI parsed data: {data}")

                # Use NON-WATERMARKED video ONLY - prioritize "play"
                video_url = data.get("play") or data.get("download_url")

                if not video_url:
                    raise Exception("RapidAPI response missing non-watermarked 'play' or 'download_url'")

                # Get file extension from video URL
                parsed_url = urlparse(video_url)
                path = parsed_url.path
                ext = os.path.splitext(path)[1]
                if not ext or len(ext) > 5:
                    ext = ".mp4"  # Fallback to mp4 if no valid extension
                filename = f"{uuid.uuid4()}{ext}"
                output_path = os.path.join(target_dir, filename)
                
                # Download the video with User-Agent header (as per working example)
                download_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                with requests.get(video_url, headers=download_headers, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    with open(output_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                logger.info(f"RapidAPI download succeeded: {output_path}")
                
                # Trim RapidAPI video if needed
                trimmed_path = trim_video(output_path, target_dir)
                
                if trimmed_path != output_path and os.path.exists(output_path):
                    os.remove(output_path)
                    
                return trimmed_path, True, tiktok_metadata, "rapidapi"  # Return metadata and download method
            except Exception as e:
                logger.warning(f"RapidAPI download failed with URL {repr(attempt_url)}: {e}")
        logger.warning("All RapidAPI attempts failed, falling back to yt-dlp")

    # Fallback to yt-dlp logic
    unique_id = str(uuid.uuid4())
    output_template = f"{target_dir}/{unique_id}.%(ext)s"

    ydl_opts = { 
        "outtmpl": output_template, 
        "format": "bestvideo+bestaudio/best", 
        "noplaylist": True 
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        
        # Guard against unmerged format extensions mismatched by prepare_filename
        if not os.path.exists(filename):
            base_path = os.path.splitext(filename)[0]
            for ext in ['.mp4', '.mkv', '.webm']:
                if os.path.exists(base_path + ext):
                    filename = base_path + ext
                    break



    is_video = is_video_file(filename)
    
    trimmed_path = trim_video(filename, target_dir)
    
    if trimmed_path != filename and os.path.exists(filename):
        os.remove(filename)
    
    return trimmed_path, is_video, tiktok_metadata, "yt-dlp"
