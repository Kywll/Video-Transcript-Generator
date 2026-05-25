import requests
import os
import time
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

GLADIA_BASE_URL = "https://api.gladia.io"
GLADIA_API_KEY = os.getenv("GLADIA_API_KEY")

# Use the target words and phonetic map from normalization
from utils.normalization import TARGET_WORDS, PHONETIC_MAP

def transcribe_gladia(audio_path, api_key=None):
    key = api_key or GLADIA_API_KEY
    if not key:
        logger.warning("No Gladia API key provided")
        raise HTTPException(
            status_code=400,
            detail="Gladia API key required"
        )

    logger.info(f"Starting Gladia transcription for file: {audio_path}")

    # Upload the audio file to Gladia
    headers = {
        "x-gladia-key": key,
        "accept": "application/json",
    }

    filename = os.path.basename(audio_path)
    logger.info(f"Uploading file {filename} to Gladia...")
    with open(audio_path, "rb") as f:
        files = [("audio", (filename, f, "audio/wav"))]
        upload_response = requests.post(
            f"{GLADIA_BASE_URL}/v2/upload/",
            headers=headers,
            files=files,
            timeout=30
        )

    logger.info(f"Gladia upload response status: {upload_response.status_code}")
    if not upload_response.ok:
        logger.error(f"Gladia upload failed: {upload_response.text}")
        raise HTTPException(
            status_code=upload_response.status_code,
            detail=f"Failed to upload audio to Gladia: {upload_response.text}"
        )

    upload_data = upload_response.json()
    audio_url = upload_data.get("audio_url")
    if not audio_url:
        logger.error(f"No audio_url in Gladia upload response: {upload_data}")
        raise HTTPException(
            status_code=500,
            detail="No audio_url received from Gladia"
        )
    logger.info(f"Got audio_url from Gladia: {audio_url}")

    # Prepare transcription request (simplified first to test)
    data = {
        "audio_url": audio_url,
        "translation": False,
        "custom_spelling": False,
        "language_config": {
            "languages": ["en", "tl"],
            "code_switching": True
        },
        "diarization": False,
        "name_consistency": False,
        "punctuation_enhanced": False,
        "sentiment_analysis": True,
        "callback": False
    }

    headers["Content-Type"] = "application/json"
    logger.info("Starting Gladia transcription request...")
    post_response = requests.post(
        f"{GLADIA_BASE_URL}/v2/pre-recorded/",
        headers=headers,
        json=data,
        timeout=30
    )

    logger.info(f"Gladia transcription start response status: {post_response.status_code}")
    if not post_response.ok:
        logger.error(f"Gladia transcription start failed: {post_response.text}")
        raise HTTPException(
            status_code=post_response.status_code,
            detail=f"Failed to start transcription: {post_response.text}"
        )

    post_data = post_response.json()
    result_url = post_data.get("result_url")
    if not result_url:
        logger.error(f"No result_url in Gladia start response: {post_data}")
        raise HTTPException(
            status_code=500,
            detail="No result_url received from Gladia"
        )
    logger.info(f"Got result_url from Gladia: {result_url}")

    # Poll for results
    logger.info("Polling Gladia for results...")
    start_poll_time = time.time()
    while True:
        if time.time() - start_poll_time > 300:  # 5 minute timeout
            logger.error("Gladia polling timed out after 5 minutes")
            raise HTTPException(
                status_code=500,
                detail="Gladia transcription timed out"
            )
        
        poll_response = requests.get(result_url, headers=headers, timeout=10)
        if not poll_response.ok:
            logger.error(f"Gladia poll failed: {poll_response.text}")
            raise HTTPException(
                status_code=poll_response.status_code,
                detail=f"Failed to poll Gladia: {poll_response.text}"
            )
        
        poll_data = poll_response.json()
        status = poll_data.get("status")
        logger.info(f"Gladia poll status: {status}")
        
        if status == "done":
            logger.info("Gladia transcription completed!")
            break
        elif status == "error":
            logger.error(f"Gladia transcription failed: {poll_data}")
            raise HTTPException(
                status_code=500,
                detail=f"Gladia transcription failed: {poll_data}"
            )
        
        time.sleep(2)

    # Extract words from the result
    result = poll_data.get("result", {})
    transcription = result.get("transcription", {})
    utterances = transcription.get("utterances", [])
    
    words = []
    for utterance in utterances:
        for word_obj in utterance.get("words", []):
            words.append({
                "word": word_obj.get("word", ""),
                "start": word_obj.get("start", 0),
                "end": word_obj.get("end", 0)
            })
    
    logger.info(f"Extracted {len(words)} words from Gladia transcription")
    return words
