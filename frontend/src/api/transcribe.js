export async function transcribeVideo(file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(
        `${import.meta.env.VITE_API_URL}/transcribe`,
        {
            method: "POST",
            body: formData,
        }
    );

    if (!res.ok) {
        throw new Error("Upload failed");
    }

    return res.json();
}

export async function transcribeUrl(url) {
    const res = await fetch(
        `${import.meta.env.VITE_API_URL}/transcribe-url`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ url }),
        }
    );

    if (!res.ok) {
        throw new Error("URL transcription failed");
    }

    return res.json();
}