import os
import uuid
import heapq 

from fastapi import HTTPException
from elevenlabs.client import ElevenLabs

from utils.normalization import (
    normalize_word,
    PHONETIC_MAP
)

from services.video_service import (
    extract_audio,
    get_video_duration,
    MAX_DURATION
)

from services.offline_transcription_service import transcribe_vosk_wrapper

UPLOAD_DIR = "uploads"

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

def transcribe_elevenlabs(
    wav_path,
    api_key
):
    client = ElevenLabs(
        api_key=api_key
    )

    with open(wav_path, "rb") as f:

        result = client.speech_to_text.convert(
            file=f,
            model_id="scribe_v2",
            diarize=False,
            timestamps_granularity="word"
        )

    words = []

    for w in result.words:

        if w.type != "word":
            continue

        words.append({
            "word": w.text,
            "start": w.start,
            "end": w.end
        })

    return words

def process_video(video_path, filename, user_api_key=None, language="multi"):
    duration = get_video_duration(video_path)

    if duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long ({int(duration)}s). Max allowed is {MAX_DURATION}s"
        )

    audio_filename = f"{uuid.uuid4()}.wav"
    audio_path = os.path.join(UPLOAD_DIR, audio_filename)
    extract_audio(video_path, audio_path)

    key = (
        user_api_key
        or ELEVENLABS_API_KEY
    )

    if key:
        try:
            transcript = transcribe_elevenlabs(
                audio_path,
                key
            )
        except Exception as e:
            # Fallback to Vosk if ElevenLabs fails
            print(f"ElevenLabs failed, falling back to Vosk: {e}")
            transcript = transcribe_vosk_wrapper(audio_path)
    else:
        # No API key, use Vosk directly
        transcript = transcribe_vosk_wrapper(audio_path)
            
    if not transcript:
        raise HTTPException(status_code=500, detail="Empty transcript")
    

    word_indexes = {}

    i = 0
    while i < len(transcript):
        word_obj = transcript[i]
        current = word_obj["word"].lower().strip(".,!?'")

        # try combining with next word
        if i < len(transcript) - 1:
            next_word = transcript[i + 1]["word"].lower().strip(".,!?'")
            combined = f"{current} {next_word}"

            # check phonetic combined
            if combined in PHONETIC_MAP:
                normalized = PHONETIC_MAP[combined]

                if normalized not in word_indexes:
                    word_indexes[normalized] = []

                word_indexes[normalized].append(i)

                i += 2
                continue

        # normal single word
        normalized = normalize_word(current)

        if normalized not in word_indexes:
            word_indexes[normalized] = []

        word_indexes[normalized].append(i)

        i += 1

    freq = []
    for w in word_indexes:
        pair = (-len(word_indexes[w]), w)
        heapq.heappush(freq, pair)
    
    word_frequencies = []
    for i in range(min(10, len(freq))):
        word_frequencies.append(heapq.heappop(freq))

    return transcript, word_indexes, word_frequencies, audio_filename








