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
    """Extract video ID from TikTok URL (support various formats, including short URLs)"""
    url = url.strip()
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
    
    logger.warning(f"❌ Could not extract video ID from URL: {url}")
    return None

def get_tiktok_post_detail(video_id, rapidapi_key):
    """Get TikTok description using RapidAPI"""
    endpoint = "https://tiktok-api23.p.rapidapi.com/api/post/detail"
    
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "tiktok-api23.p.rapidapi.com",
        "Content-Type": "application/json"
    }
    
    querystring = {"videoId": video_id}
    
    try:
        logger.info(f"Calling RapidAPI post/detail with videoId: {video_id}")
        response = requests.get(endpoint, headers=headers, params=querystring, timeout=30)
        logger.info(f"RapidAPI post/detail status: {response.status_code}")
        logger.info(f"RapidAPI post/detail FULL RESPONSE: {response.text}")
        
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
    tiktok_metadata = None
    
    # Trim whitespace from URL
    url = url.strip()
    logger.info(f"Processing TikTok URL after trimming: {url}")
    
    # Get TikTok metadata EXCLUSIVELY with yt-dlp (free, no rate limits)
    tiktok_metadata = {"description": ""}  # Initialize with empty string
    logger.info("Getting TikTok metadata with yt-dlp...")
    try:
        ydl_opts_meta = {
            "quiet": True,
            "noplaylist": True
        }
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(url, download=False)
            logger.info(f"yt-dlp metadata info: {info}")
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

            # Check download response for any metadata first
            logger.info(f"RapidAPI download video response: {response.text}")
            try:
                download_data = response.json()
                if not tiktok_metadata:
                    # Try to extract description from download response too
                    desc = download_data.get("desc") or download_data.get("description") or ""
                    if desc:
                        tiktok_metadata = {"description": desc}
                        logger.info(f"Got TikTok description from download response: {desc}")
            except Exception as e:
                logger.warning(f"Could not parse download response for metadata: {str(e)}")
            
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
        logger.info(f"yt-dlp FULL info: {info}")
        filename = ydl.prepare_filename(info)
        # Try to get description from yt-dlp info
        if not tiktok_metadata or (tiktok_metadata and not tiktok_metadata.get("description")):
            desc = (
                info.get("description") or
                info.get("desc") or
                info.get("title") or
                ""
            )
            logger.info(f"yt-dlp extracted desc: {desc}")
            if desc:
                tiktok_metadata = {"description": desc}
                logger.info(f"✅ Got TikTok description from yt-dlp: {desc}")

    # Check if yt-dlp downloaded a video file
    is_video = is_video_file(filename)
    
    # Import trim_video here to avoid circular import
    from services.video_service import trim_video
    trimmed_path = trim_video(filename, target_dir)
    
    # If trimmed, clean up the original file
    if trimmed_path != filename and os.path.exists(filename):
        os.remove(filename)
    
    return trimmed_path, is_video, tiktok_metadata
