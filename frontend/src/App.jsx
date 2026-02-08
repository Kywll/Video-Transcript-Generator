import { useState, useRef } from "react";
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
      />

    </div>
  );
}

export default App;
