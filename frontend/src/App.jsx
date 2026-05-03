import { useState, useRef, useEffect } from "react";
import { transcribeVideo } from "./api/transcribe";
import { transcribeUrl } from "./api/transcribe";

import FileUpload from "./components/FileUpload";
import AudioPlayer from "./components/AudioPlayer";
import Transcript from "./components/Transcript";
import UrlInput from "./components/InputUrl";

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [transcript, setTranscript] = useState(null);
  const [wordIndexes, setWordIndexes] = useState(null);
  const [audioFile, setAudioFile] = useState(null);
  const [error, setError] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [mutedIndexes, setMutedIndexes] = useState([]);
  const [muteMode, setMuteMode] = useState(false);
  const [apiKey, setApiKey] = useState("");

  const audioRef = useRef(null);

  const handleUpload = async () => {
    if (!file || loading) return;
    
    setLoading(true);
    setError(null);
    setTranscript(null);

    try {
      const data = await transcribeVideo(file, apiKey);
      setTranscript(data.transcript);
      setFile(null);
      setWordIndexes(data.word_indexes);
      setAudioFile(
        `${import.meta.env.VITE_API_URL}/uploads/${data.audio_file}`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUrlTranscribe = async (url) => {
      if (loading) return;

      if (!url.includes("tiktok.com")) {
          alert("Please enter a valid TikTok URL");
          return;
      }

      try {
          setLoading(true);
          setError(null);
          setTranscript(null);

          const data = await transcribeUrl(url, apiKey);

          console.log("URL DATA:", data);

          setTranscript(data.transcript);
          setWordIndexes(data.word_indexes);

          setAudioFile(`${import.meta.env.VITE_API_URL}/uploads/${data.audio_file}`);

      } catch (err) {
          console.error(err);
          setError(err.message || "URL transcription failed");
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
    if (!transcript || !audioFile) return;

    const filename = audioFile?.split("/").pop()?.replace(".wav", ".mp4");

    if (!filename) return;

    setLoading(true);

    const mutes = mutedIndexes.map(idx => ({
      start: transcript[idx].start,
      end: transcript[idx].end
    }));

    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL}/export-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json"},
        body: JSON.stringify({
          filename: filename,
          mutes: mutes
        }),
      });

      const data = await res.json();

      if (data.filename) {
        window.location.href = `${import.meta.env.VITE_API_URL}/download/${data.filename}`;
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
    <div className="container py-5">
      <div className="row justify-content-center">
        <div className="col-lg-10 col-xl-9">

          <div className="text-center mb-5">
            <h1 className="fw-bold mb-3">
              Video Transcriber & Editing
            </h1>

            <p className="text-secondary fs-5">
              Upload a video, search words, mute moments, export a clean cut
            </p>

            <p className="text-warning small mt-3">
              ⚠️ Large or long videos may take longer to process and could fail due to server limitations.
            </p>
          </div>
          
          <div className="text-center mb-3">
            <input
              type="text"
              placeholder="Optional: Enter Deepgram API Key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="form-control"
              style={{ maxWidth: "400px", margin: "0 auto" }}
            />
          </div>

          <div className="card shadow-sm mb-">
            <div className="card-body py-4">
              <FileUpload
                onFileSelect={setFile}
                onUpload={handleUpload}
                loading={loading}
                disabled={!file || transcript}
              />

              {error && (
                <div className="alert alert-danger mt-3">
                  {error}
                </div>
              )}
            </div>
          </div>
          
          <UrlInput
            onSubmit={handleUrlTranscribe}
            loading={loading || transcript}
          />

          <AudioPlayer
            ref={audioRef}
            src={audioFile}
            onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
          />

          {transcript && (
            <>
              {/* MUTE MODE BUTTON */}
              <div className="text-center mt-3">
                <button
                  className={`btn ${
                    muteMode ? "btn-danger" : "btn-outline-danger"
                  } px-4`}
                  onClick={() => setMuteMode((prev) => !prev)}
                >
                  {muteMode
                    ? "Mute Mode ON (Click words to mute)"
                    : "Mute Mode OFF"}
                </button>

                <p className="small mt-2">
                  {muteMode
                    ? "Click words to mute/unmute"
                    : "Click words to jump"}
                </p>
              </div>

              <Transcript
                transcript={transcript}
                onWordClick={jumpTo}
                currentTime={currentTime}
                mutedIndexes={mutedIndexes}
                onToggleMute={toggleMute}
                muteMode={muteMode}
              />

              <div className="text-center mt-4">
                <button
                  className="btn btn-success px-4"
                  onClick={handleExportVideo}
                  disabled={loading}
                >
                  {loading ? "Processing..." : "Export Edited Video"}
                </button>
              </div>
            </>
          )}
            {transcript && (
              <button
              className="text-center btn btn-secondary mt-3"
              onClick={() => {
                setTranscript(null);
                setFile(null);
                setAudioFile(null);
                setError(null);
                setWordIndexes(null);
                setMutedIndexes([]);
              }}
            >
              New Transcription
            </button>
            )}

          {error && <div className="alert alert-danger mt-3">{error}</div>}
        </div>
      </div>
    </div>
  );


}

export default App;
