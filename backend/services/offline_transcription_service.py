from vosk import Model, KaldiRecognizer
from pydub import AudioSegment
import wave, os, json

# Lazy-load Vosk model only when needed
vosk_model = None

def get_vosk_model():
    global vosk_model
    if vosk_model is None:
        # Try possible model paths
        possible_paths = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model"),  # Local: backend/../model
            "/app/model",  # Docker: /app/model
            "model"  # Fallback: current directory
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                print(f"Loading Vosk model from: {path}")
                vosk_model = Model(path)
                return vosk_model
        
        raise FileNotFoundError(f"Vosk model not found in any of: {possible_paths}")
    return vosk_model

def split_audio(wav_path, chunk_ms=30000):
    audio = AudioSegment.from_wav(wav_path)
    chunks = []

    for i in range(0, len(audio), chunk_ms):
        chunk = audio[i:i + chunk_ms]
        chunk_path = f"{wav_path[:-4]}_chunk{i//chunk_ms}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    return chunks

def transcribe_vosk_wrapper(audio_path):
    chunks = split_audio(audio_path, chunk_ms=10000)

    transcript = []
    offset = 0.0

    for chunk_path in chunks:
        for w in transcribe_vosk(chunk_path):
            transcript.append({
                "word": w["word"],
                "start": w["start"] + offset,
                "end": w["end"] + offset
            })
        offset += 10.0

        if os.path.exists(chunk_path):
            os.remove(chunk_path)

    return transcript


def transcribe_vosk(wav_path):
    wf = wave.open(wav_path, "rb")
    recognizer = KaldiRecognizer(get_vosk_model(), wf.getframerate())
    recognizer.SetWords(True)

    words_with_timestamps = []
        
    while True:
        data = wf.readframes(16000)

        if len(data) == 0:
            break

        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            if "result" in result:
                words_with_timestamps.extend(result["result"])


    final_result = json.loads(recognizer.FinalResult())
    if "result" in final_result:
        words_with_timestamps.extend(final_result["result"])
    
    wf.close()
    return words_with_timestamps