Video Transcription MVP
A full-stack video transcription and editing tool built using Python, FastAPI, Vosk, FFmpeg, and React (Vite).

This project extracts audio from uploaded videos, transcribes each word with timestamps, and provides an interactive interface to navigate, search, mute, and export edited videos.

This is a work-in-progress MVP designed to explore:
Audio processing pipelines
Timestamp mapping and synchronization
Word-level indexing
Interactive media interfaces
Backend–frontend integration
Deployment using Docker, Render, and Vercel

Live Demo
Frontend (Vercel):
https://video-transcript-generator.vercel.app/

Repository:
https://github.com/Kywll/Video-Transcript-Generator

Current Features:
Extract audio from videos automatically using FFmpeg
Noise reduction and audio normalization
Chunk-based transcription using Vosk
Word-level timestamps
Click a word to jump to that exact moment
Real-time current word highlighting
Search for words and instantly highlight matches
Alt + Click (Desktop) / Long Press (Mobile) to mute words
Export edited video with selected words muted
Dockerized backend
Deployed frontend (Vercel) + backend (Render)

Planned Features:
Cut video segments entirely (not just mute)
Add sound effects to selected words or phrases
Merge overlapping mute ranges for cleaner export
Polished UI and improved visuals
Optional support for direct video URLs
Performance optimization for longer videos

Deployment:
Frontend:
Hosted on Vercel
Uses environment variables to connect to backend API

Backend:
Hosted on Render
Docker-based deployment
Handles file uploads, transcription, and video exporting

CORS is configured to allow:
http://localhost:5173
https://video-transcript-generator.vercel.app

Usage:
1. Upload a video file
2. Wait for transcription to complete
3. Click any word to jump to its timestamp
4. Search for specific words
5. Alt + Click (Desktop) or Long Press (Mobile) to mute words
6. Export the edited video

⚠️Large or long videos may take longer to process due to server limitations.

Learning Outcomes:
This project has been a strong practical exercise in:
Audio extraction and processing with FFmpeg
Chunked speech recognition using Vosk
Managing word-level timestamps
Building interactive React interfaces
Synchronizing UI state with media playback
Designing REST APIs using FastAPI
Handling file uploads and downloads
Creating Dockerized production environments
Deploying full-stack applications (Render + Vercel)
Debugging real-world timing and synchronization issues

Tech Stack:
Backend:
Python 3.10+
FastAPI
Vosk
FFmpeg
Pydub

Frontend:
React (Vite)
Bootstrap 5

Infrastructure:
Docker
Render
Vercel

License:
MIT License © 2026 Michael Napoles
