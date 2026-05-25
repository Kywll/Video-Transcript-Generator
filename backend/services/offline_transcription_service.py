from vosk import Model, KaldiRecognizer
from pydub import AudioSegment
import wave, os, json

vosk_model = Model("model")

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
    recognizer = KaldiRecognizer(vosk_model, wf.getframerate())
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