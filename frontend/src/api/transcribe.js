async function pollJob(jobId) {
    const base = import.meta.env.VITE_API_URL;

    const start = Date.now();
    const TIMEOUT = 120000; // 2 minutes

    while (true) {
        if (Date.now() - start > TIMEOUT) {
            throw new Error("Processing timed out");
        }

        if (import.meta.env.DEV) {
            console.log("Polling job:", jobId);
        }

        let res;

        try {
            res = await fetch(`${base}/job/${jobId}`);
        } catch {
            const delay = Math.min(2000 + (Date.now() - start) / 20, 5000);
            await new Promise((r) => setTimeout(r, delay));
            continue;
        }

        if (res.status === 404) {
            throw new Error("Job expired or not found");
        }

        if (!res.ok) {
            throw new Error("Failed to fetch job status");
        }

        let data;
        try {
            data = await res.json();
        } catch {
            throw new Error("Invalid server response");
        }

        if (data.status === "done") {
            return data.result;
        }

        if (data.status === "failed") {
            throw new Error(data.error || "Processing failed");
        }

        // queued or processing → wait
        const delay = Math.min(2000 + (Date.now() - start) / 20, 5000);
        await new Promise((r) => setTimeout(r, delay));
    }
}

export async function transcribeVideo(file, apiKey, language) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", language || "multi");

    if (apiKey) {
        formData.append("gladia_api_key", apiKey);
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
            throw new Error("Invalid Gladia API key");
        }

        throw new Error(err.detail || "Upload failed");
    }

    const { job_id } = await res.json();
    return pollJob(job_id);
}

export async function transcribeUrl(
    url,
    gladiaKey,
    rapidApiKey,
    language
) {
    console.log("transcribeUrl called with:", {
        url,
        gladiaKey: gladiaKey ? "provided" : "not provided",
        rapidApiKey: rapidApiKey ? "provided" : "not provided",
        language
    });
    console.log("VITE_API_URL:", import.meta.env.VITE_API_URL);
    
    const res = await fetch(
        `${import.meta.env.VITE_API_URL}/transcribe-url`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                url,
                gladia_api_key: gladiaKey || null,
                rapidapi_key: rapidApiKey || null,
                language: language || "multi"
            }),
        }
    );
    
    console.log("transcribeUrl response status:", res.status);

    if (!res.ok) {
        let err;
        try {
            err = await res.json();
        } catch {
            throw new Error("Server error");
        }

        if (err.detail?.toLowerCase().includes("auth")) {
            throw new Error("Invalid Gladia API key");
        }

        throw new Error(err.detail || "Upload failed");
    }
    
    const { job_id } = await res.json();
    return pollJob(job_id);
}