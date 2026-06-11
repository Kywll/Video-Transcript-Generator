import { useState, useRef, useEffect } from "react";
import { transcribeVideo } from "./api/transcribe";
import { transcribeUrl } from "./api/transcribe";
import { supabase } from "./api/supabase";

import FileUpload from "./components/FileUpload";
import AudioPlayer from "./components/AudioPlayer";
import Transcript from "./components/Transcript";
import UrlInput from "./components/InputUrl";
import LoginButton from "./components/LoginButton";
import ApiKeyManager from "./components/ApiKeyManager";

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
  const [gladiaKey, setGladiaKey] = useState("");
  const [rapidApiKey, setRapidApiKey] = useState("");
  const [language, setLanguage] = useState("multi");
  const [videoFile, setVideoFile] = useState(null);
  const [urlInput, setUrlInput] = useState("");
  const [exportAvailable, setExportAvailable] = useState(true);
  const [tiktokMetadata, setTiktokMetadata] = useState(null);

  const [session, setSession] = useState(null);
  const [savedGladiaKey, setSavedGladiaKey] = useState(null);
  const [savedRapidApiKey, setSavedRapidApiKey] = useState(null);

  const audioRef = useRef(null);

  const handleUpload = async () => {
  
    if (!file || loading) return;
    
    setLoading(true);
    setError(null);
    setTranscript(null);
    setAudioFile(null);
    setUrlInput("");
    setVideoFile(null);
    setMutedIndexes([]);
    setWordIndexes(null);
    setCurrentTime(0);
    setExportAvailable(true);
    setTiktokMetadata(null);

    try {
      const data = await transcribeVideo(
        file,
        gladiaKey,
        language
      );
      setTranscript(data.transcript);
      setFile(null);
      setWordIndexes(data.word_indexes);
      setAudioFile(
        `${import.meta.env.VITE_API_URL}/uploads/${data.audio_file}`
      );
      setVideoFile(`${import.meta.env.VITE_API_URL}/uploads/${data.video_file}`);
      setExportAvailable(data.export_available);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRawDownload = async () => {
    if (!urlInput) return;

    try {
      setLoading(true);

      const res = await fetch(`${import.meta.env.VITE_API_URL}/download-raw`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: urlInput }),
      });

      const data = await res.json();

      if (data.filename) {
        const url = `${import.meta.env.VITE_API_URL}/download-file/${data.filename}`;
        window.location.href = url;
      } else {
        throw new Error("Download failed");
      }

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
          setAudioFile(null);
          setFile(null);
          setVideoFile(null);
          setMutedIndexes([]);
          setWordIndexes(null);
          setCurrentTime(0);
          setExportAvailable(true);
          setTiktokMetadata(null);

          const data = await transcribeUrl(
            url,
            gladiaKey,
            rapidApiKey,
            language
          );

          console.log("URL DATA:", data);

          setTranscript(data.transcript);
          setWordIndexes(data.word_indexes);
          setTiktokMetadata(data.tiktok_metadata);

          setAudioFile(`${import.meta.env.VITE_API_URL}/uploads/${data.audio_file}`);
          setVideoFile(`${import.meta.env.VITE_API_URL}/uploads/${data.video_file}`);
          setExportAvailable(data.export_available);
          setUrlInput("");

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

  const loadApiKeys = async () => {
    if (!session) return;
    try {
      const token = session.access_token;
      const res = await fetch(`${import.meta.env.VITE_API_URL}/get-api-keys`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      setSavedGladiaKey(data.gladia_api_key);
      setSavedRapidApiKey(data.rapidapi_key);
      if (data.gladia_api_key) setGladiaKey(data.gladia_api_key);
      if (data.rapidapi_key) setRapidApiKey(data.rapidapi_key);
    } catch (err) {
      console.error("Failed to load API keys", err);
    }
  };

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    loadApiKeys();
  }, [session]);

  const saveApiKey = async (keyType, value) => {
    if (!session) return;
    try {
      const token = session.access_token;
      await fetch(`${import.meta.env.VITE_API_URL}/save-api-keys`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          [keyType]: value,
          [keyType === "gladia_api_key" ? "rapidapi_key" : "gladia_api_key"]: 
            keyType === "gladia_api_key" ? savedRapidApiKey : savedGladiaKey
        })
      });
      if (keyType === "gladia_api_key") setSavedGladiaKey(value);
      else setSavedRapidApiKey(value);
    } catch (err) {
      console.error("Failed to save API key", err);
    }
  };

  const deleteApiKey = async (keyType) => {
    if (!session) return;
    try {
      const token = session.access_token;
      await fetch(`${import.meta.env.VITE_API_URL}/delete-api-key`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ key_type: keyType })
      });
      if (keyType === "gladia_api_key") {
        setSavedGladiaKey(null);
        setGladiaKey("");
      } else {
        setSavedRapidApiKey(null);
        setRapidApiKey("");
      }
    } catch (err) {
      console.error("Failed to delete API key", err);
    }
  };

  const logout = async () => {
    await supabase.auth.signOut();
    setSession(null);
    setSavedGladiaKey(null);
    setSavedRapidApiKey(null);
    setGladiaKey("");
    setRapidApiKey("");
  };

  const handleExportVideo = async () => {
    if (!transcript || !videoFile || !exportAvailable) return;

    // Extract filename from URL (get everything after the last /)
    const filename = videoFile.split("/").pop();

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
        const url = `${import.meta.env.VITE_API_URL}/download-file/${data.filename}`;
        window.location.href = url;
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

          <div className="text-center mb-4">
            <div className="d-flex justify-content-end mb-3">
              {session ? (
                <div className="d-flex align-items-center gap-2">
                  <span className="text-muted">
                    {session.user.email}
                  </span>
                  <button className="btn btn-outline-secondary" onClick={logout}>
                    Logout
                  </button>
                </div>
              ) : (
                <LoginButton />
              )}
            </div>
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
          
          <div style={{ maxWidth: "500px", margin: "0 auto" }}>
            <ApiKeyManager
              label="Gladia API Key"
              value={gladiaKey}
              onChange={setGladiaKey}
              onSave={() => saveApiKey("gladia_api_key", gladiaKey)}
              onDelete={() => deleteApiKey("gladia_api_key")}
              saved={!!savedGladiaKey}
            />
            <ApiKeyManager
              label="RapidAPI Key (TikTok URLs)"
              value={rapidApiKey}
              onChange={setRapidApiKey}
              onSave={() => saveApiKey("rapidapi_key", rapidApiKey)}
              onDelete={() => deleteApiKey("rapidapi_key")}
              saved={!!savedRapidApiKey}
            />
          </div>

          <UrlInput
            onSubmit={handleUrlTranscribe}
            onUrlChange={setUrlInput}
            loading={loading || transcript}
          />
          
          <div className="card shadow-sm mt-3">
            <div className="card-body py-4">
              <FileUpload
                onFileSelect={setFile}
                onUpload={handleUpload}
                loading={loading}
                disabled={!file || transcript}
              />

              {error && (
                <div className="alert alert-danger mt-">
                  {error}
                </div>
              )}
            </div>
          </div>
        
          {/* Video Player */}
          {videoFile && (
            <div className="mt-3">
              <video
                controls
                style={{ width: "100%", borderRadius: "8px" }}
                src={videoFile}
                onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
                ref={audioRef}
              />
            </div>
          )}
          {/* Audio Player (fallback if no video) */}
          {!videoFile && (
            <AudioPlayer
              key={audioFile}
              ref={audioRef}
              src={audioFile}
              onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
            />
          )}

          {/* TikTok Description Section (Right After Video/Audio Player) */}
          {tiktokMetadata && tiktokMetadata.description && (
            <div className="mt-3 card shadow-sm p-3">
              <h5 className="fw-semibold mb-2">Description</h5>
              <p className="mb-0">{tiktokMetadata.description}</p>
            </div>
          )}

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
                  disabled={loading || !videoFile || !exportAvailable}
                >
                  {loading ? "Processing..." : "Export Edited Video"}
                </button>
                {!exportAvailable && (
                  <p className="text-danger small mt-2">
                    ⚠️ Export not available (no video file downloaded)
                  </p>
                )}
              </div>
            </>
          )}
            {!transcript && urlInput && !file && (
              <div className="text-center mt-4">
                  <button
                  className="btn btn-outline-success px-4"
                  onClick={handleRawDownload}
                  disabled={loading}
                  >
                  {loading ? "Downloading..." : "Download Video"}
                  </button>
              </div>
            )}

            {transcript && (
              <div className="text-center mt-3">
                <button
                className="btn btn-secondary mt-3"
                onClick={() => {
                  setTranscript(null);
                  setFile(null);
                  setAudioFile(null);
                  setError(null);
                  setWordIndexes(null);
                  setMutedIndexes([]);
                  setVideoFile(null);
                  setTiktokMetadata(null);
                }}
              >
                New Transcription
              </button>
            </div>
            )}

          {error && <div className="alert alert-danger mt-3">{error}</div>}
        </div>
      </div>
    </div>
  );


}

export default App;
