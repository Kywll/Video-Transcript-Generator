import { useState } from "react";

function UrlInput({ onSubmit, loading }) {
    const [url, setUrl] = useState("");

    return (
        <div className="text-center mt-3">
            <input
                type="text"
                placeholder="Paste TikTok URL..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="form-control mb-2"
                style={{ maxWidth: "400px", margin: "0 auto" }}
            />

            <button
                onClick={() => onSubmit(url)}
                disabled={loading || !url}
                className="btn btn-success px-4"
            >
                {loading ? "Processing..." : "Transcribe URL"}
            </button>
        </div>
    );
}

export default UrlInput;