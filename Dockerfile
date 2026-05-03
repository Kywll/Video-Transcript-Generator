# Use lightweight Python base
FROM python:3.10-slim

# 🔹 Install system dependencies (ffmpeg + required libs)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    unzip \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 🔹 Set working directory
WORKDIR /app

# 🔹 Copy requirements first (better Docker caching)
COPY requirements.txt .

# 🔹 Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 🔹 Download Vosk model (small, fast)
RUN wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && \
    unzip vosk-model-small-en-us-0.15.zip && \
    mv vosk-model-small-en-us-0.15 model && \
    rm vosk-model-small-en-us-0.15.zip

# 🔹 Copy your app code
COPY . .

# 🔹 Create required folders
RUN mkdir -p uploads downloads

# 🔹 Expose port (Render uses this)
EXPOSE 8000

# 🔹 Start FastAPI server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]