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

def extract_tiktok_video_id(url):
    """Extract video ID from TikTok URL (support various formats, including short URLs)"""
    url = clean_url(url)
    import re
    
    logger.info(f"Starting video ID extraction from URL: {url}")
    
    try:
        # Follow redirects for short URLs (vm.tiktok.com, vt.tiktok.com, etc.)
        response = requests.head(url, allow_redirects=True, timeout=10)
        final_url = response.url
        logger.info(f"Original URL: {url} → Final URL after redirect: {final_url}")
        
        # Patterns like https://www.tiktok.com/@username/video/1234567890123456789
        patterns = [
            r'/video/(\d+)',
            r'/(\d{17,19})(?:/?$|\?)'
        ]
        
        # Check both final URL and original URL
        for check_url in [final_url, url]:
            logger.info(f"Checking URL for video ID: {check_url}")
            for pattern in patterns:
                match = re.search(pattern, check_url)
                if match:
                    video_id = match.group(1)
                    logger.info(f"✅ Extracted video ID: {video_id}")
                    return video_id
    except Exception as e:
        logger.error(f"⚠️ Error extracting video ID from URL {url}: {str(e)}", exc_info=True)
        # Fallback: try original URL without redirect
        import re
        patterns = [r'/video/(\d+)', r'/(\d{17,19})(?:/?$|\?)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                logger.info(f"✅ Fallback extracted video ID: {video_id}")
                return video_id
    
    logger.warning(f"Could not extract video ID from URL: {url}")
    return None

def get_tiktok_post_detail(video_id, rapidapi_key):
    """Get TikTok description using RapidAPI"""
    endpoint = "https://tiktok-api23.p.rapidapi.com/api/post/detail"
    
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "tiktok-api23.p.rapidapi.com",
    }
    
    querystring = {"videoId": video_id}
    
    try:
        logger.info(f"Calling RapidAPI post/detail with videoId: {video_id}")
        response = requests.get(endpoint, headers=headers, params=querystring, timeout=30)
        logger.info(f"RapidAPI post/detail status: {response.status_code}")
        
        if response.status_code == 204 or not response.text.strip():
            return None
            
        if response.ok:
            data = response.json()
            logger.info(f"Parsed RapidAPI data: {data}")
            
            aweme_detail = (
                data.get("data", {}).get("aweme_detail", {}) or
                data.get("aweme_detail", {}) or
                data.get("data", {})
            )
            logger.info(f"aweme_detail: {aweme_detail}")
            
            description = (
                aweme_detail.get("desc", "") or
                aweme_detail.get("description", "") or
                aweme_detail.get("text", "") or
                data.get("desc", "") or
                data.get("description", "") or
                ""
            )
            
            metadata = {"description": description}
            logger.info(f"✅ Final extracted TikTok metadata: {metadata}")
            return metadata
    except Exception as e:
        logger.error(f"Failed to get TikTok post detail: {str(e)}", exc_info=True)
    return None

def download_tiktok(url, target_dir, rapidapi_key=None):
    tiktok_metadata = {"description": ""}  # Initialize safely
    url = clean_url(url)
    logger.info(f"Processing TikTok URL after thorough cleaning: {url}")
    
    # Get TikTok metadata with yt-dlp first
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
    
    # RapidAPI execution route - using working version!
    if rapidapi_key and rapidapi_key.strip():
        try:
            logger.info("Attempting RapidAPI download...")
            endpoint = "https://tiktok-api23.p.rapidapi.com/api/download/video"

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
            logger.info(f"RapidAPI response text: {response.text}")

            if not response.ok:
                raise Exception(f"RapidAPI request failed with status {response.status_code}")

            data = response.json()

            # Use NON-WATERMARKED video ONLY - prioritize "play"
            video_url = data.get("play") or data.get("download_url")

            if not video_url:
                raise Exception("RapidAPI response missing non-watermarked 'play' or 'download_url'")

            # Get file extension from video URL
            from urllib.parse import urlparse
            parsed_url = urlparse(video_url)
            path = parsed_url.path
            ext = os.path.splitext(path)[1]
            if not ext or len(ext) > 5:
                ext = ".mp4"  # Fallback to mp4 if no valid extension
            filename = f"{uuid.uuid4()}{ext}"
            output_path = os.path.join(target_dir, filename)

            # Extract description from RapidAPI response if needed
            if not tiktok_metadata or not tiktok_metadata.get("description"):
                desc = data.get("desc") or data.get("title") or data.get("data", {}).get("desc") or data.get("data", {}).get("title") or ""
                if desc:
                    tiktok_metadata = {"description": desc}
                    logger.info(f"Got TikTok description from RapidAPI: {desc}")
            
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
            from services.video_service import trim_video
            trimmed_path = trim_video(output_path, target_dir)
            
            if trimmed_path != output_path and os.path.exists(output_path):
                os.remove(output_path)
                
            return trimmed_path, True, tiktok_metadata, "rapidapi"  # Return metadata and download method
        except Exception as e:
            logger.warning(f"RapidAPI download failed: {e}, falling back to yt-dlp")

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

        if not tiktok_metadata or not tiktok_metadata.get("description"):
            desc = (
                info.get("description") or
                info.get("desc") or
                info.get("title") or
                ""
            )
            if desc:
                tiktok_metadata = {"description": desc}

    is_video = is_video_file(filename)
    
    from services.video_service import trim_video
    trimmed_path = trim_video(filename, target_dir)
    
    if trimmed_path != filename and os.path.exists(filename):
        os.remove(filename)
    
    return trimmed_path, is_video, tiktok_metadata, "yt-dlp"
