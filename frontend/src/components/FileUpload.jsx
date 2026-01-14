function FileUpload({ onFileSelect, onUpload, loading, disabled }) {
    return (
        <>
            <input 
                type="file" 
                accept="video/*"
                onChange={(e) => onFileSelect(e.target.files[0])}
            />
            <br /><br />

            <button onClick={onUpload} disabled={loading || disabled}>
                {loading ? "Transcribing..." : "Upload & Transcribe"}
            </button>
        </>
    );
}

export default FileUpload;