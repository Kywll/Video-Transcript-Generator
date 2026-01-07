Video Transcription MVP
A video transcription tool built using Python, FastAPI, Vosk, and FFmpeg. This project extracts audio from videos, transcribes each word with timestamps, and provides an interactive interface to navigate and highlight words in the transcript.
This is a work-in-progress MVP designed to explore audio processing, timestamp mapping, and interactive web interfaces.

Features:
Current features:
Extract audio from videos automatically
Transcribe audio into words with timestamps
Click a word in the transcript to jump to that moment in the audio
Search for words and highlight all occurrences instantly

Planned features:
Cut video parts or mute based on words in the transcript
Add sound effects to selected words or phrases
Polished UI and improved visuals
Optional support for direct video URLs

Installation:
Clone the repository:
git clone https://github.com/yourusername/video-transcription-mvp.git
cd video-transcription-mvp

Create and activate a virtual environment:
python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

Install dependencies:
pip install -r requirements.txt

Download the Vosk model and place it in the model/ directory:
[Vosk Models](https://alphacephei.com/vosk/models)

Usage:
Run the FastAPI app:
python main.py


Open your browser and go to:
http://127.0.0.1:8000


Upload a video file to generate the transcript. Click words to jump to their timestamps or search for specific words to highlight them.
Project Structure
.
├── main.py             # FastAPI application
├── templates/
│   └── index.html      # Frontend HTML
├── static/
│   └── index.css       # CSS for styling
├── uploads/            # Uploaded videos and audio files
├── model/              # Vosk model
└── requirements.txt    # Python dependencies

Learning Outcomes:
This project has been a great way to practice:
Audio processing and transcription with Vosk and FFmpeg
Building interactive web interfaces using FastAPI and JavaScript
Managing timestamps and mapping text to audio
Integrating backend and frontend features in a lightweight MVP

Dependencies:
Python 3.10+
FastAPI
Vosk
FFmpeg
Pydub
Jinja2
License

MIT License © 2026 Michael Napoles
