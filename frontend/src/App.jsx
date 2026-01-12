import { useState } from "react";

function App() {
  const [file, setFile] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleUpload = async () => {
    if (!file) return;

    setLoading(true);
    setError(null);
    setTranscript(null);

    const formData = new FormData();
    formData.append("file", file);

    try{
      const res = await fetch("http://127.0.0.1:8000/transcribe", {
        method: "POST",
        body: formData
      });

      if (!res.ok) {
        throw new Error("Upload Failed");
      }

      const data = await res.json();

      const text = data.transcript
        .map(w => w.word)
        .join(" ");
      setTranscript(text);
    } catch(err) {
      setError(err.message);
    } setLoading(false);

  };


  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif"}}>
      <h1>Video Transcriber</h1>

      <input 
        type="file" 
        accept="video/*"
        onChange={(e) => setFile(e.target.files[0])}
      />

      <br /><br />

      <button onClick={handleUpload} disabled={loading || !file}>
        {loading ? "Transcribing..." : "Upload & Transcribe"}
      </button>

      <br /><br />

      {error && <p style={{ color: "red" }}>{error}</p>}
      
      {transcript && (
        <>
          <h2>Transcript</h2>
          <p style={{ whiteSpace: "pre-wrap" }}>{transcript}</p>
        </>

      )}
    </div>
  );
}

export default App;




