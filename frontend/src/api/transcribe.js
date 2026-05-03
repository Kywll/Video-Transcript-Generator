export async function transcribeVideo(file, apiKey) {
    const formData = new FormData();
    formData.append("file", file);

    if (apiKey) {
        formData.append("api_key", apiKey);
    }

    const res = await fetch(
        `${import.meta.env.VITE_API_URL}/transcribe`,
        {
            method: "POST",
            body: formData,
        }
    );

    if (!res.ok) {
        const err = await res.json();

        if (err.detail?.toLowerCase().includes("auth")) {
            throw new Error("Invalid Deepgram API key");
        }

        throw new Error(err.detail || "Upload failed");
    }

    return res.json();
}

export async function transcribeUrl(url, apiKey) {
    const res = await fetch(
        `${import.meta.env.VITE_API_URL}/transcribe-url`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ url, api_key: apiKey || null  }),
        }
    );

    if (!res.ok) {
        let err;
        try {
            err = await res.json();
        } catch {
            throw new Error("Server error");
        }

        if (err.detail?.toLowerCase().includes("auth")) {
            throw new Error("Invalid Deepgram API key");
        }

        throw new Error(err.detail || "Upload failed");
    }
    
    return res.json();
}