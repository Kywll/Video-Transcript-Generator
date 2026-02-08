import { useState, useRef, useEffect } from "react";
import { transcribeVideo } from "./api/transcribe";

import FileUpload from "./components/FileUpload";
import AudioPlayer from "./components/AudioPlayer";
import Transcript from "./components/Transcript";

function App() {
  const [file, setFile] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [wordIndexes, setWordIndexes] = useState(null);
  const [audioFile, setAudioFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [mutedIndexes, setMutedIndexes] = useState([]);

  const audioRef = useRef(null);

  const handleUpload = async () => {
    if (!file) return;
    
    setLoading(true);
    setError(null);
    setTranscript(null);

    try {
      const data = await transcribeVideo(file);
      setTranscript(data.transcript);
      setWordIndexes(data.word_indexes);
      setAudioFile(
        `http://127.0.0.1:8000/uploads/${data.audio_file}`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const jumpTo = (time) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time;
      audioRef.current.play();
    }
  };

  const toggleMute = (index) => {
    setMutedIndexes((prev) =>
      prev.includes(index) ? prev.filter(i => i !== index) : [...prev, index]
    );
  }

  useEffect(() => {
    if (!audioRef.current || !transcript) return;

    const isMuted = transcript.some((w, i) => {
      return currentTime >= (w.start -0.1) && currentTime <= (w.end -0.1) && mutedIndexes.includes(i);
    });

    audioRef.current.muted = isMuted;

  }, [currentTime, mutedIndexes, transcript]);

  const handleExportVideo = async () => {
    if (!transcript || !file) return;

    setLoading(true);

    const mutes = mutedIndexes.map(idx => ({
      start: transcript[idx].start,
      end: transcript[idx].end
    }));

    try {
      const res = await fetch("http://127.0.0.1:8000/export-video", {
        method: "POST",
        headers: { "Content-Type": "application/json"},
        body: JSON.stringify({
          filename: file.name,
          mutes: mutes
        }),
      });

      const data = await res.json();

      if (data.filename) {
        window.location.href = `http://127.0.0.1:8000/download/${data.filename}`;
      } else {
        throw new Error("No filename received from server")
      }

    } catch (err) {
      setError("Export failed: " + err.message);
    } finally {
      setLoading(false);
    }
  };


  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Video Transcriber</h1>

      <FileUpload
        onFileSelect={setFile}
        onUpload={handleUpload}
        loading={loading}
        disabled={!file}
      />

      {error && <p style={{ color: "red" }}>{error}</p>}

      <AudioPlayer 
        ref={audioRef} 
        controls
        src={audioFile} 
        onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
      />

      <Transcript 
        transcript={transcript}
        onWordClick={jumpTo} 
        currentTime={currentTime}
        mutedIndexes={mutedIndexes}
        onToggleMute={toggleMute}
      />

      {transcript && (
        <button
          onClick={handleExportVideo}
          disabled={loading}
          style={{ marginLeft: "10px", backgroundColor: "green", color: "white" }}
        >
          {loading ? "Processing..." : "Export Edited Video"}
        </button>
      )}

    </div>
  );
}

export default App;
