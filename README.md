<<<<<<< HEAD
# speakloudtts
=======
# SpeakLoudTTS

> Convert articles into podcast‑style MP3s with Flask, Google TTS, Firestore & Cloud Storage.

## Features

- Submit URLs (NYT, Atlantic, etc.) and extract full text  
- Google Text‑to‑Speech chunking + FFmpeg merge  
- Firestore for metadata & status  
- Cloud Storage for MP3 hosting  
- `/items` web UI + embedded player  
- `/feed.xml` iTunes‑compatible RSS feed  

## Getting Started

### Prerequisites

- Python 3.8+  
- Homebrew (for ffmpeg)  
- GCP project with Text‑to‑Speech, Firestore & Storage enabled  
- Service‑account JSON credentials  

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/speakloudtts.git
cd speakloudtts
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
>>>>>>> 1a6b7d1 (Initial commit: scaffold speakloudtts app - working)
