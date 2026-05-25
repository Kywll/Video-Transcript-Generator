import requests
import os
import time
from fastapi import HTTPException

GLADIA_BASE_URL = "https://api.gladia.io"
GLADIA_API_KEY = os.getenv("GLADIA_API_KEY")

# Use the target words and phonetic map from normalization
from utils.normalization import TARGET_WORDS, PHONETIC_MAP

def transcribe_gladia(audio_path, api_key=None):
    key = api_key or GLADIA_API_KEY
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Gladia API key required"
        )

    # Upload the audio file to Gladia
    headers = {
        "x-gladia-key": key,
        "accept": "application/json",
    }

    filename = os.path.basename(audio_path)
    with open(audio_path, "rb") as f:
        files = [("audio", (filename, f, "audio/wav"))]
        upload_response = requests.post(
            f"{GLADIA_BASE_URL}/v2/upload/",
            headers=headers,
            files=files
        )

    if not upload_response.ok:
        raise HTTPException(
            status_code=upload_response.status_code,
            detail=f"Failed to upload audio to Gladia: {upload_response.text}"
        )

    upload_data = upload_response.json()
    audio_url = upload_data.get("audio_url")
    if not audio_url:
        raise HTTPException(
            status_code=500,
            detail="No audio_url received from Gladia"
        )

    # Prepare custom vocabulary from our target words and phonetic map
    custom_vocabulary = []
    
    # Add target words
    for word in TARGET_WORDS:
        custom_vocabulary.append({
            "value": word,
            "intensity": 0.5,
            "language": "en"
        })
    
    # Add phonetic map variations
    for pronunciation, normalized_word in PHONETIC_MAP.items():
        # Only add if not already added
        if not any(v["value"] == normalized_word for v in custom_vocabulary):
            custom_vocabulary.append({
                "value": normalized_word,
                "pronunciations": [pronunciation],
                "intensity": 0.5,
                "language": "en"
            })

    # Prepare transcription request
    data = {
        "audio_url": audio_url,
        "custom_vocabulary": True,
        "custom_vocabulary_config": {
            "default_intensity": 0.5,
            "vocabulary": custom_vocabulary
        },
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
    post_response = requests.post(
        f"{GLADIA_BASE_URL}/v2/pre-recorded/",
        headers=headers,
        json=data
    )

    if not post_response.ok:
        raise HTTPException(
            status_code=post_response.status_code,
            detail=f"Failed to start transcription: {post_response.text}"
        )

    post_data = post_response.json()
    result_url = post_data.get("result_url")
    if not result_url:
        raise HTTPException(
            status_code=500,
            detail="No result_url received from Gladia"
        )

    # Poll for results
    while True:
        poll_response = requests.get(result_url, headers=headers)
        if not poll_response.ok:
            raise HTTPException(
                status_code=poll_response.status_code,
                detail=f"Failed to poll Gladia: {poll_response.text}"
            )
        
        poll_data = poll_response.json()
        status = poll_data.get("status")
        
        if status == "done":
            break
        elif status == "error":
            raise HTTPException(
                status_code=500,
                detail=f"Gladia transcription failed: {poll_data}"
            )
        
        time.sleep(1)

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
    
    return words
